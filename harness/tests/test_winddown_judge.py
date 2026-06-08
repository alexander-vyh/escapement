"""Tests for winddown_judge.py — the local-LLM judge layer over the regex floor.

Validated live against Qwen3.6-27B (11/11 on the labeled set). These tests pin the
two load-bearing behaviors that the live run can't guarantee on every machine:
  - FAIL-OPEN: model down / error / garbage verdict → defer to the regex floor, never hang.
  - MODEL EXTENDS RECALL: the judge catches paraphrases the regex misses.
The HTTP call is injected (`post=`) so tests never depend on a running server.
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
# decide — union of regex floor + model verdict, gated by reversible work
# ---------------------------------------------------------------------------

PARAPHRASE_REGEX_MISSES = "I think this is a natural stopping point for today."


def test_model_down_falls_back_to_regex_floor():
    # model_offer=None (server down). Regex floor still catches an obvious offer.
    d, r = wj.decide("want me to wrap for the night, or keep going?",
                     reversible_work_remains=True, model_offer=None)
    assert d == "block" and r == "winddown_offer_work_remains"


def test_model_down_and_regex_misses_allows_documented_floor_gap():
    # Paraphrase the regex can't catch + model unavailable → allow (the floor's
    # known limit; this is exactly why the model layer exists).
    d, r = wj.decide(PARAPHRASE_REGEX_MISSES, reversible_work_remains=True, model_offer=None)
    assert d == "allow" and r == "no_winddown_offer"


def test_model_extends_recall_over_regex():
    # Regex misses the paraphrase, but the model flags it → block (the model's value).
    d, r = wj.decide(PARAPHRASE_REGEX_MISSES, reversible_work_remains=True, model_offer=True)
    assert d == "block" and r == "winddown_offer_work_remains"


def test_work_remains_gate_prevents_overnag_even_when_model_flags():
    # No reversible work left → legitimate stop; do not nag even if the model flags it.
    d, r = wj.decide("want me to wrap for the night?", reversible_work_remains=False,
                     model_offer=True)
    assert d == "allow" and r == "winddown_but_no_reversible_work"


def test_legit_question_not_blocked_when_model_agrees_not_winddown():
    d, r = wj.decide("Should I use Postgres or SQLite?", reversible_work_remains=True,
                     model_offer=False)
    assert d == "allow" and r == "no_winddown_offer"
