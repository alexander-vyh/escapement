"""Tests for winddown_judge.py — the local-LLM judge is the SOLE classifier.

ARCHITECTURE CHANGE (user directive): the regex floor is KILLED. Wind-down
classification is semantic — the judge's verdict is the only signal. There is no
regex fallback to defer to. `decide(text, work, model_offer)` resolves the offer
purely from `model_offer`:
  - model_offer True  → offer
  - model_offer False → not an offer
  - model_offer None  → judge unavailable/unclear → FAIL-OPEN to allow (semantic
    or nothing), and the outage is SIGNALLED (gate-design Rule 2) at the hook layer.
The HTTP call is injected (`post=`) so tests never depend on a running server.

These tests pin two load-bearing behaviors the live run can't guarantee on every
machine:
  - FAIL-OPEN: model down / error / garbage verdict → None → allow (no fabricated block).
  - JUDGE OWNS RECALL: every offer/non-offer classification comes from the verdict,
    not from any string pattern.
"""
import pathlib
import sys

BIN = pathlib.Path(__file__).resolve().parent.parent / "bin"
sys.path.insert(0, str(BIN))

import winddown_judge as wj


# ---------------------------------------------------------------------------
# model_verdict — parse + fail-open (injected transport)
# ---------------------------------------------------------------------------

def test_verdict_winddown_true():
    assert wj.model_verdict("x", post=lambda payload: "winddown") is True


def test_verdict_not_winddown_false():
    assert wj.model_verdict("x", post=lambda payload: "not_winddown") is False


def test_verdict_unclear_or_garbage_is_none():
    assert wj.model_verdict("x", post=lambda payload: "unclear") is None
    assert wj.model_verdict("x", post=lambda payload: "banana") is None


def test_verdict_fails_open_on_exception():
    def boom(payload):
        raise TimeoutError("server down")
    # FAIL-OPEN: a down/slow model must yield None (defer to floor), never raise.
    assert wj.model_verdict("x", post=boom) is None


# ---------------------------------------------------------------------------
# decide — judge verdict is the SOLE classifier, gated by reversible work
#
# REPLACES the old "union of regex floor + model verdict" suite (and its
# PARAPHRASE_REGEX_MISSES floor-gap cases). Under judge-only there is no floor to
# have a gap. Per never-suppress, the replacement oracle is equal-or-STRONGER: it
# pins that the verdict ALONE decides, and the new fail-open semantics (judge None
# → allow even for an obvious wrap offer) are asserted directly — that is the
# deliberate consequence of "semantic or nothing".
# ---------------------------------------------------------------------------

# A phrase an old regex floor WOULD have caught. Under judge-only it must NOT be
# special-cased: its classification comes entirely from model_offer.
OBVIOUS_WRAP_OFFER = "want me to wrap for the night, or keep going?"
# A phrase no regex floor ever caught — the judge owns it identically.
PARAPHRASE_OFFER = "I think this is a natural stopping point for today."


def test_model_flags_offer_with_work_blocks():
    # POSITIVE CONTROL: judge says offer + work remains → block. Holds for BOTH a
    # phrase the old regex caught and a paraphrase it missed — the judge owns both.
    for text in (OBVIOUS_WRAP_OFFER, PARAPHRASE_OFFER):
        d, r = wj.decide(text, reversible_work_remains=True, model_offer=True)
        assert (d, r) == ("block", "winddown_offer_work_remains"), (
            f"judge-flagged offer with work must block: {text!r}; got {d}/{r}"
        )


def test_model_says_not_offer_allows():
    # NEGATIVE CONTROL: judge says not-offer → allow, regardless of the text.
    for text in (OBVIOUS_WRAP_OFFER, "Should I use Postgres or SQLite?"):
        d, r = wj.decide(text, reversible_work_remains=True, model_offer=False)
        assert (d, r) == ("allow", "no_winddown_offer"), (
            f"judge-cleared text must allow: {text!r}; got {d}/{r}"
        )


def test_judge_unavailable_allows_even_obvious_wrap():
    # THE LOAD-BEARING CHANGE (inverts the old fall-back-to-regex test): with the
    # regex floor removed, judge None means NO classifier fired → allow, even for
    # an obvious wrap offer. "Semantic or nothing." A union/regex-fallback impl
    # would (wrongly) still BLOCK this — that is exactly what this test rejects.
    d, r = wj.decide(OBVIOUS_WRAP_OFFER, reversible_work_remains=True, model_offer=None)
    assert (d, r) == ("allow", "no_winddown_offer"), (
        "judge-only: an unavailable judge must NOT be backstopped by a regex floor; "
        f"got {d}/{r} — a regex fallback survived the refactor"
    )


def test_work_remains_gate_prevents_overnag_even_when_model_flags():
    # No reversible work left → legitimate stop; do not nag even if the judge flags it.
    d, r = wj.decide(OBVIOUS_WRAP_OFFER, reversible_work_remains=False, model_offer=True)
    assert (d, r) == ("allow", "winddown_but_no_reversible_work")


def test_decide_does_not_consult_any_regex(monkeypatch):
    # ARCHITECTURE GUARD: decide() must not call into a regex floor. If
    # winddown_gate still exposes is_winddown_offer, decide must NOT use it — make
    # it explode if called, and confirm decide still works off model_offer alone.
    import winddown_judge as _wj
    if hasattr(_wj, "wg") and hasattr(_wj.wg, "is_winddown_offer"):
        def _boom(*a, **k):
            raise AssertionError("decide() must not consult the regex floor (judge-only)")
        monkeypatch.setattr(_wj.wg, "is_winddown_offer", _boom)
    d, r = _wj.decide(OBVIOUS_WRAP_OFFER, reversible_work_remains=True, model_offer=True)
    assert (d, r) == ("block", "winddown_offer_work_remains")
    d2, r2 = _wj.decide(OBVIOUS_WRAP_OFFER, reversible_work_remains=True, model_offer=None)
    assert (d2, r2) == ("allow", "no_winddown_offer")
