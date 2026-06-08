"""Tests for winddown_gate.py — the continuation-harness wind-down rung.

The load-bearing oracle: distinguish a WIND-DOWN / WRAP offer (which, with reversible
work remaining, must be blocked into continuation) from a LEGITIMATE clarifying question
(which must NOT be blocked — over-nagging that is the over-correction the research warns
against). A "?"-only or "any-question" detector must FAIL these tests.
"""
import pathlib
import sys

BIN = pathlib.Path(__file__).resolve().parent.parent / "bin"
sys.path.insert(0, str(BIN))

import winddown_gate as wg  # hard import: sibling module, not a deployed dep


# ---------------------------------------------------------------------------
# is_winddown_offer — positive cases (real examples from the user)
# ---------------------------------------------------------------------------

WINDDOWN_OFFERS = [
    "It's late — want me to push the beads and wrap for the night, or keep going into T2?",
    "Two natural next moves: (a) I take the next task now, or (b) we wrap and you handle "
    "the branch-protection toggle + merge when ready. Which way?",
    "Want me to wrap up here, or keep going?",
    "Ready to push when you are.",
    "I'll leave it here for the morning unless you want me to continue.",
    "Should I keep going or call it a night?",
    "We can pick this up tomorrow if you'd prefer.",
    "Happy to run the session-close protocol now, or keep going.",
    # Real veiled-stop from a live cake session (2026-06-04) — regex floor missed all
    # three tells until this case was added; the local-LLM judge is the real backstop.
    "Nothing is outstanding and nothing needs you. It's ~3:40am — that's a wrap. Good night.",
]


def test_winddown_offers_detected():
    for t in WINDDOWN_OFFERS:
        assert wg.is_winddown_offer(t) is True, f"should detect wind-down: {t!r}"


# ---------------------------------------------------------------------------
# is_winddown_offer — negative cases (legit questions / statements)
# ---------------------------------------------------------------------------

NOT_WINDDOWN = [
    "Which auth library should we use — Auth.js or Lucia?",
    "Should I use Postgres or SQLite for this service?",
    "(a) add caching or (b) add pagination first — which has more impact?",
    "I've implemented the parser and all tests pass. Moving on to the validator now.",
    "This needs a design decision: event-sourced or CRUD? I'll proceed with CRUD unless you object.",
    "",
    "Running the migration now.",
]


def test_legit_questions_not_flagged():
    for t in NOT_WINDDOWN:
        assert wg.is_winddown_offer(t) is False, f"should NOT flag as wind-down: {t!r}"


# ---------------------------------------------------------------------------
# winddown_decision — the rung (combines offer + reversible-work-remains)
# ---------------------------------------------------------------------------

def test_offer_with_work_remaining_blocks():
    d, r = wg.winddown_decision(
        "want me to wrap for the night, or keep going?", reversible_work_remains=True)
    assert d == "block"
    assert r == "winddown_offer_work_remains"


def test_offer_with_no_reversible_work_allows():
    # Genuinely blocked on a human-only/irreversible item, nothing reversible left:
    # this is a legitimate stop. Nagging it is the over-correction we must avoid.
    d, r = wg.winddown_decision(
        "want me to wrap for the night, or keep going?", reversible_work_remains=False)
    assert d == "allow"
    assert r == "winddown_but_no_reversible_work"


def test_non_offer_with_work_remaining_does_not_block_on_this_rung():
    d, r = wg.winddown_decision(
        "Should I use Postgres or SQLite?", reversible_work_remains=True)
    assert d == "allow"
    assert r == "no_winddown_offer"


def test_empty_text_allows():
    d, r = wg.winddown_decision("", reversible_work_remains=True)
    assert d == "allow"
    assert r == "no_winddown_offer"


# ---------------------------------------------------------------------------
# gate-design compliance: the denial names the escape path (Rule 1)
# ---------------------------------------------------------------------------

def test_recovery_prompt_names_escape_and_userrelease():
    p = wg.RECOVERY_PROMPT.lower()
    # names the affordance: proceed with reversible work + async-flag human-only items
    assert "proceed" in p or "continue" in p
    assert "flag" in p or "async" in p or "note" in p
    # and preserves the user's release valve (don't trap them)
    assert "stop" in p
