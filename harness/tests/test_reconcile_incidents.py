"""Tests for reconcile_incidents.py — closing the `was_correct` loop.

Oracle: the next GENUINE human reaction in the transcript decides whether a Stop
decision was correct. These tests encode the named fragile implementation from the
Test Oracle Brief (treating a `tool_result` as the human reaction) as a control
that a correct implementation must NOT fall for.
"""
import pathlib
import sys

import pytest

BIN = pathlib.Path(__file__).resolve().parent.parent / "bin"
sys.path.insert(0, str(BIN))

# Hard import (NOT importorskip): this module is a sibling in bin/, not a deployed
# dependency. A skip-on-missing here would let CI go green without running the suite.
import reconcile_incidents as ri


# ---------------------------------------------------------------------------
# extract_human_messages: only genuine human prompts survive
# ---------------------------------------------------------------------------

def _u(content, **extra):
    """Build a transcript user-entry."""
    d = {"type": "user", "message": {"role": "user", "content": content}}
    d.update(extra)
    return d


def test_extract_filters_tool_results_and_meta():
    lines = [
        {"type": "assistant", "message": {"content": "..."}, "timestamp": "2026-06-04T00:00:00.000Z"},
        # a tool_result that happens to contain the word "continue" — the trap
        _u([{"type": "tool_result", "content": "build output: continue to next step"}],
           timestamp="2026-06-04T00:00:01.000Z"),
        # an injected meta caveat — not human
        _u("<local-command-caveat>blah</local-command-caveat>", isMeta=True,
           timestamp="2026-06-04T00:00:02.000Z"),
        # a slash-command invocation — not a human prose reaction
        _u("<command-name>/model</command-name>", timestamp="2026-06-04T00:00:03.000Z"),
        # a system-reminder injection wrapped as user — not human
        _u("<system-reminder>do the thing</system-reminder>", timestamp="2026-06-04T00:00:04.000Z"),
        # the REAL human reaction
        _u("continue", timestamp="2026-06-04T00:00:05.000Z"),
    ]
    msgs = ri.extract_human_messages(lines)
    texts = [t for _, t in msgs]
    assert texts == ["continue"], f"only the genuine human prompt should survive, got {texts}"


def test_extract_keeps_interrupt_marker():
    lines = [
        _u([{"type": "text", "text": "[Request interrupted by user]"}],
           timestamp="2026-06-04T00:00:01.000Z"),
    ]
    msgs = ri.extract_human_messages(lines)
    assert any("interrupted by user" in t.lower() for _, t in msgs)


# ---------------------------------------------------------------------------
# classify: the core oracle (pure function)
# ---------------------------------------------------------------------------

def test_allow_then_bare_continue_is_false_allow():
    # KEY metric: work stalled — agent stopped, user had to resume it.
    wc, basis = ri.classify("allow", "queue_drained", "continue")
    assert wc is False
    assert basis == "stalled_user_resumed"


def test_allow_verification_passed_no_reaction_is_true():
    wc, basis = ri.classify("allow", "verification_passed", None)
    assert wc is True
    assert basis == "harness_proved_terminal"


def test_user_reaction_overrides_reason_prior():
    # verification "passed" but the user immediately said continue => oracle too
    # narrow; the allow was still a false allow. User reaction wins over prior.
    wc, basis = ri.classify("allow", "verification_passed", "keep going")
    assert wc is False
    assert basis == "stalled_user_resumed"


def test_block_then_release_is_false_block():
    # KEY metric: over-nag — agent was done, user pushed back to stop.
    wc, basis = ri.classify("block", "tasks_remain_in_queue", "stop")
    assert wc is False
    assert basis == "overnag_user_released"


def test_block_then_interrupt_is_false_block():
    wc, basis = ri.classify("block", "no_completion_or_resumption_proof",
                            "[Request interrupted by user]")
    assert wc is False
    assert basis == "overnag_user_released"


def test_substantive_next_instruction_is_ambiguous_not_a_verdict():
    # "continue, but also refactor X and add tests" is NEW work, not a verdict on
    # the prior stop. Must NOT be read as a bare continuation.
    long_msg = "continue but also refactor the parser and add tests for the edge cases"
    wc, basis = ri.classify("allow", "queue_drained", long_msg)
    assert wc is None
    assert basis == "ambiguous_human"


def test_block_no_reaction_is_none():
    wc, basis = ri.classify("block", "tasks_remain_in_queue", None)
    assert wc is None
    assert basis == "no_human_reaction"


def test_block_is_never_labeled_true():
    # Documented limitation: we measure over-nag (False) and absence (None); we do
    # not claim a block was correct. Any block input must not yield True.
    for reason in ("tasks_remain_in_queue", "no_contract", "all_remaining_tasks_blocked"):
        for nxt in (None, "continue", "do the next thing", "stop"):
            wc, _ = ri.classify("block", reason, nxt)
            assert wc is not True


# ---------------------------------------------------------------------------
# reconcile: idempotency + tool_result trap end-to-end + atomicity of intent
# ---------------------------------------------------------------------------

def _incident(sid, ts, decision, reason):
    return {"timestamp": ts, "session_id": sid, "decision": decision,
            "reason": reason, "was_correct": None, "notes": ""}


def test_reconcile_uses_human_message_not_interleaved_tool_result():
    """The named fragile implementation must fail here.

    A naive 'next user-role line' scan would pick the tool_result (which contains
    'continue') and mislabel. Correct impl reads past it to the human 'stop'.
    """
    incidents = [_incident("S1", "2026-06-04T00:00:00Z", "block", "tasks_remain_in_queue")]
    transcript = {
        "S1": [
            _u([{"type": "tool_result", "content": "...continue building..."}],
               timestamp="2026-06-04T00:00:01.000Z"),
            _u("stop", timestamp="2026-06-04T00:00:02.000Z"),
        ]
    }
    out, stats = ri.reconcile(incidents, lambda sid: transcript.get(sid))
    assert out[0]["was_correct"] is False
    assert out[0]["label_basis"] == "overnag_user_released"


def test_reconcile_is_idempotent():
    incidents = [_incident("S1", "2026-06-04T00:00:00Z", "allow", "verification_passed")]
    out1, _ = ri.reconcile(incidents, lambda sid: None)
    assert out1[0]["was_correct"] is True
    # second pass over already-labeled data changes nothing and relabels 0
    out2, stats2 = ri.reconcile(out1, lambda sid: None)
    assert out2 == out1
    assert stats2["relabeled"] == 0


def test_reconcile_no_transcript_is_none_not_false():
    incidents = [_incident("GONE", "2026-06-04T00:00:00Z", "block", "tasks_remain_in_queue")]
    out, _ = ri.reconcile(incidents, lambda sid: None)
    assert out[0]["was_correct"] is None
    assert out[0]["label_basis"] == "no_transcript"


def test_summary_reports_rates_and_coverage():
    incidents = [
        {"timestamp": "t", "session_id": "S", "decision": "allow",
         "reason": "queue_drained", "was_correct": False, "label_basis": "stalled_user_resumed"},
        {"timestamp": "t", "session_id": "S", "decision": "allow",
         "reason": "verification_passed", "was_correct": True, "label_basis": "harness_proved_terminal"},
        {"timestamp": "t", "session_id": "S", "decision": "block",
         "reason": "x", "was_correct": False, "label_basis": "overnag_user_released"},
        {"timestamp": "t", "session_id": "S", "decision": "block",
         "reason": "x", "was_correct": None, "label_basis": "no_transcript"},
    ]
    s = ri.summarize(incidents)
    assert s["total"] == 4
    assert s["labeled"] == 3
    # Lower-bound rates: demonstrable-false / ALL decisions of that type.
    # stall rate = stalled allows / all allows = 1/2
    assert s["false_allow_rate"] == pytest.approx(0.5)
    # over-nag rate = overnag blocks / all blocks = 1/2  (NOT 1/1 — a rate over
    # only the labeled-False blocks would be pinned at 100% by construction, since
    # blocks are never labeled True. That would be a meaningless oracle.)
    assert s["false_block_rate"] == pytest.approx(0.5)
    assert s["by_basis"]["stalled_user_resumed"] == 1


def test_false_block_rate_is_not_structurally_pinned_to_one():
    # Regression guard for the oracle-downgrade we fixed: many blocks, only some
    # over-nags, must yield a rate well below 100%.
    incidents = [
        {"decision": "block", "reason": "x", "was_correct": False,
         "label_basis": "overnag_user_released"},
    ] + [
        {"decision": "block", "reason": "x", "was_correct": None,
         "label_basis": "no_transcript"} for _ in range(9)
    ]
    s = ri.summarize(incidents)
    assert s["false_block_rate"] == pytest.approx(0.1)
