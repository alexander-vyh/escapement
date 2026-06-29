"""Tests for winddown_gate.py — the continuation-harness wind-down rung.

ARCHITECTURE CHANGE (user directive): the REGEX FLOOR IS KILLED. Classification is
semantic — the local-LLM judge is the sole classifier. `winddown_gate` is reduced to
`RECOVERY_PROMPT` + `winddown_decision(text, reversible_work_remains, is_offer)`, where
`is_offer` is the JUDGE'S verdict supplied by the caller. There is no `_WINDDOWN_PATTERNS`
and no `is_winddown_offer` regex to fall back to.

This file therefore pins ONLY the verdict-gated rung logic (is_offer injected) and the
RECOVERY_PROMPT escape contract. The phrase-level true-positive corpus that used to live
here (WINDDOWN_OFFERS, the stopping-point family, the "for today" boundary) is no longer
a hook-level concern — it moves to the JUDGE's fixtures (test_winddown_judge.py /
test_winddown_live.py), because the gate no longer classifies prose.

The old regex tests (is_winddown_offer positives/negatives, stopping-point family,
separate-/same-clause "for today" boundary) are REMOVED, not weakened. Per never-suppress
the replacement oracle is equal-or-stronger: the rung's block/allow decisions are pinned
against an INJECTED verdict, and an architecture guard asserts the regex API is gone.
"""
import importlib.util
import pathlib
import sys

BIN = pathlib.Path(__file__).resolve().parent.parent / "bin"


def _load_winddown_gate():
    spec = importlib.util.spec_from_file_location("winddown_gate", BIN / "winddown_gate.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load harness/bin/winddown_gate.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


wg = _load_winddown_gate()


# ---------------------------------------------------------------------------
# winddown_decision — the rung, driven by the JUDGE's injected `is_offer`.
# (decision, reason). This is the only classification path post-refactor.
# ---------------------------------------------------------------------------

def test_offer_with_work_blocks():
    # POSITIVE CONTROL: judge says offer + reversible work remains → block.
    d, r = wg.winddown_decision(
        "anything at all", reversible_work_remains=True, is_offer=True)
    assert (d, r) == ("block", "winddown_offer_work_remains"), (
        f"judge-flagged offer with work must block; got {d}/{r}"
    )


def test_offer_with_no_work_allows():
    # No reversible work left → legitimate stop; never nag even on a flagged offer.
    d, r = wg.winddown_decision(
        "anything at all", reversible_work_remains=False, is_offer=True)
    assert (d, r) == ("allow", "winddown_but_no_reversible_work"), (
        f"flagged offer with no reversible work must allow; got {d}/{r}"
    )


def test_non_offer_with_work_allows():
    # NEGATIVE CONTROL: judge says not-an-offer → allow, regardless of work.
    d, r = wg.winddown_decision(
        "Should I use Postgres or SQLite?", reversible_work_remains=True, is_offer=False)
    assert (d, r) == ("allow", "no_winddown_offer"), (
        f"judge-cleared non-offer must allow; got {d}/{r}"
    )


def test_decision_is_text_independent_given_verdict():
    # The verdict — not the text — drives the decision. Two opposite texts with the
    # SAME injected verdict must reach the SAME decision (proves no residual prose
    # classification leaks in). A regex-floor remnant would make these diverge.
    block_a, _ = wg.winddown_decision(
        "want me to wrap for the night?", reversible_work_remains=True, is_offer=True)
    block_b, _ = wg.winddown_decision(
        "Postgres or SQLite?", reversible_work_remains=True, is_offer=True)
    assert block_a == block_b == "block", (
        "with is_offer=True the rung must block regardless of the text — any "
        "divergence means a regex remnant is still classifying prose"
    )
    allow_a, _ = wg.winddown_decision(
        "want me to wrap for the night?", reversible_work_remains=True, is_offer=False)
    allow_b, _ = wg.winddown_decision(
        "Postgres or SQLite?", reversible_work_remains=True, is_offer=False)
    assert allow_a == allow_b == "allow"


# ---------------------------------------------------------------------------
# ARCHITECTURE GUARD — the regex floor is GONE.
# ---------------------------------------------------------------------------

def test_regex_floor_api_removed():
    """The user directive KILLS the regex floor. `_WINDDOWN_PATTERNS` and the
    regex-based `is_winddown_offer` must no longer exist on the module — their
    presence means the floor survived the refactor."""
    assert not hasattr(wg, "_WINDDOWN_PATTERNS"), (
        "_WINDDOWN_PATTERNS must be removed — classification is judge-only now"
    )
    assert not hasattr(wg, "is_winddown_offer"), (
        "is_winddown_offer (regex) must be removed — the judge is the sole classifier"
    )


def test_winddown_decision_requires_a_verdict():
    """With the regex floor gone there is no default classifier. Calling
    winddown_decision WITHOUT an explicit is_offer must NOT silently fall back to a
    regex (which no longer exists). The caller (stop_hook/judge) always supplies the
    verdict; pin that the signature reflects judge-only. We accept either: is_offer
    is a required keyword, OR a None default that is treated as 'no offer' (allow) —
    never as 'consult a regex'. A regex-fallback default is the forbidden remnant."""
    import inspect
    sig = inspect.signature(wg.winddown_decision)
    is_offer = sig.parameters.get("is_offer")
    assert is_offer is not None, "winddown_decision must take an is_offer verdict"
    # If is_offer keeps a None default, None must mean 'no offer → allow', NOT
    # 'consult the (now-deleted) regex'.
    if is_offer.default is None or is_offer.default is inspect.Parameter.empty:
        # Calling with is_offer=None must allow (no classifier fired), not crash on a
        # missing regex and not fabricate a block.
        d, r = wg.winddown_decision("want me to wrap for the night?",
                                    reversible_work_remains=True, is_offer=None)
        assert d == "allow", (
            "is_offer=None must mean 'no offer → allow' under judge-only, not a "
            f"regex consult; got {d}/{r}"
        )


# ---------------------------------------------------------------------------
# gate-design Rule 1: the denial names the escape path (UNCHANGED by the refactor).
# ---------------------------------------------------------------------------

def test_recovery_prompt_names_escape_and_userrelease():
    p = wg.RECOVERY_PROMPT.lower()
    # names the affordance: proceed with reversible work + async-flag human-only items
    assert "proceed" in p or "continue" in p
    assert "flag" in p or "async" in p or "note" in p
    # and preserves the user's release valve (don't trap them)
    assert "stop" in p
