#!/usr/bin/env python3
"""Winddown judge must backstop the wakeup_registered path too (escapement-lby9).

Follow-up to escapement-51w3. The state-based _wakeup_work_remains closed the
"session-fresh bead left behind" hole on the wakeup path. But the SEMANTIC layer
(the local-MLX winddown judge, via _winddown_override) ran ONLY on the
`conversational` allow — so a session stopping via `wakeup_registered` with a
CLEAN session-scoped bd queue but wind-down-shaped final text (e.g. "shipped it,
want me to tackle the grain work next session?") plus reversible git/bead work
passed uncaught. This widens the judge to the wakeup path.

Business invariant
------------------
- wakeup_registered + wind-down-shaped final text + reversible work remaining
  ⇒ BLOCK (the judge backstops the wakeup path, same as conversational).
- wakeup_registered + NOT a wind-down offer (legit "waiting on CI" report)
  ⇒ ALLOW (never nag a legitimate pause).
- wakeup_registered + clean tree (no reversible work) ⇒ ALLOW, judge not even
  consulted (the reversible-work gate short-circuits first).

Fragile implementations these tests REJECT
-------------------------------------------
- Widening only the main() call site but not _winddown_override's internal
  `reason != "conversational"` guard ⇒ always None for wakeup ⇒
  test_wakeup_winddown_offer_with_work_blocks fails.
- Running the judge regardless of reversible_work_remains ⇒ nags clean-tree
  pauses ⇒ (covered by the conversational suite's _no_work case; mirrored here).
- Over-widening the guard to user_released / verification_passed ⇒
  test_wakeup_widen_does_not_leak_to_other_terminals fails.

Run: python3 -m pytest harness/tests/test_winddown_wakeup_backstop.py -q
"""

import importlib.util
import json
import pathlib
import sys

BIN = pathlib.Path(__file__).resolve().parent.parent / "bin"
sys.path.insert(0, str(BIN))


def _load_stop_hook():
    spec = importlib.util.spec_from_file_location("stop_hook", BIN / "stop_hook.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


sh = _load_stop_hook()


def _write_transcript(tmp_path, text):
    p = tmp_path / "t.jsonl"
    p.write_text(json.dumps({"type": "assistant", "message": {"role": "assistant", "content": text}}))
    return str(p)


def _work_remains(cwd, thread_dir=None):
    return ("block", "implicit_queue_scoped")


def _no_work(cwd, thread_dir=None):
    return ("allow", "implicit_queue_scoped_drained")


def test_wakeup_winddown_offer_with_work_blocks(tmp_path):
    """NEGATIVE CONTROL: wakeup path + wind-down offer + reversible work ⇒ block.
    Rejects any impl that leaves _winddown_override's internal guard at
    'conversational'-only (the whole point of the change)."""
    tp = _write_transcript(
        tmp_path,
        "Shipped PR #262 and it's deploying. Want me to tackle the grain-adaptation "
        "work next session, or is this a good stopping point?",
    )
    disp = sh._winddown_override(
        "wakeup_registered", tp, "/repo", tmp_path,
        work_check=_work_remains, judge=lambda t: True,
    )
    assert disp is not None, "wakeup + wind-down offer + reversible work must block"
    assert "proceed" in disp.lower() and "stop" in disp.lower()  # escape path present


def test_wakeup_legit_pause_not_nagged(tmp_path):
    """POSITIVE CONTROL: wakeup path + NOT a wind-down offer (legit report) ⇒ allow.
    Rejects any impl that nags every wakeup pause."""
    tp = _write_transcript(
        tmp_path,
        "Merged and deploying; registered a wakeup to confirm the Cloud Run revision "
        "goes live. Waiting on the deploy run to finish.",
    )
    disp = sh._winddown_override(
        "wakeup_registered", tp, "/repo", tmp_path,
        work_check=_work_remains, judge=lambda t: False,
    )
    assert disp is None, "a legitimate wakeup report must not be nagged"


def test_wakeup_clean_tree_short_circuits_before_judge(tmp_path):
    """POSITIVE CONTROL: wakeup path + no reversible work ⇒ allow, judge never runs.
    The reversible-work gate must short-circuit before consulting the model."""
    judge_calls = {"n": 0}

    def counting_judge(t):
        judge_calls["n"] += 1
        return True

    tp = _write_transcript(tmp_path, "want me to wrap for the night, or keep going?")
    disp = sh._winddown_override(
        "wakeup_registered", tp, "/repo", tmp_path,
        work_check=_no_work, judge=counting_judge,
    )
    assert disp is None, "clean tree ⇒ legitimate stop, no nag"
    assert judge_calls["n"] == 0, "judge must not be consulted when no reversible work remains"


def test_wakeup_widen_does_not_leak_to_other_terminals(tmp_path):
    """NEGATIVE CONTROL for over-widening: user_released and verification_passed are
    GENUINE terminals — widening to wakeup_registered must not also override them."""
    tp = _write_transcript(tmp_path, "want me to wrap for the night?")
    for terminal in ("user_released", "verification_passed"):
        disp = sh._winddown_override(
            terminal, tp, "/repo", tmp_path,
            work_check=_work_remains, judge=lambda t: True,
        )
        assert disp is None, f"{terminal} is a genuine terminal and must never be overridden"


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
