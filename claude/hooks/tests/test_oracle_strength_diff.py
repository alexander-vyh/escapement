"""Behavioral corpus tests for claude/hooks/oracle_strength_diff.py (walking skeleton).

Bead: escapement-esc (skeleton) under epic -gdf.
Oracle brief: .research/flask4045-control-failure-20260619/09-test-oracle-brief.md

Business invariant (revised 2026-06-20 — advisory-only, NO BLOCK tier)
---------------------------------------------------------------------
On a test-file change, ``evaluate(old_src, new_src, path)`` classifies the change
into Level.NONE or Level.WARN such that:

  - Genuine oracle downgrades are surfaced as WARN (the gate emits ``ask``).
  - A net strengthening / no-op classifies NONE — the differ must NOT warn on
    every churn, or the signal is worthless.

The BLOCK tier was REMOVED based on this very corpus: the only signal we hoped
was block-safe (a negative control removed without re-add) false-fires on
legitimate red->green TDD (``sifiaops`` dropped ``not_to include(...)`` precisely
because the placeheld feature was built), mechanically identical to a genuine
restriction-coverage drop (``dwslack``). No mechanical rule separates them from
the test diff alone; the human/agent adjudicates. See decision in
09-test-oracle-brief.md and 08-ev-replay-findings.md.

Independent source of truth
---------------------------
The 9 adjudicated real cases (08-ev-replay-findings.md) + flask-4045. Each
fixture's ``.old`` / ``.new`` was extracted mechanically from the real session
transcript's edit tool_use input (NOT hand-authored) and lives under
``fixtures/oracle_strength/<case>.{old,new}``.

Oracle quality — the fragile implementations these tests reject
--------------------------------------------------------------
1. **Warn on any churn** (the live fragile impl): would WARN ``ioval`` even though
   it STRENGTHENS the oracle. The mandatory negative control ``ioval`` asserts
   NONE and directly kills this implementation.
2. **File-aggregate count** (brief §4): nets out delete+add swaps — refuted.
3. **Warn on any function-level assertion loss**: rejected by the moved-assertion
   test (a re-added/moved assertion must be NONE).
4. **Keyword/rationale matching** on prose (brief §4): language is noise.

A passing run requires the genuine downgrades (flask, dwslack) to WARN and the
strengthening (ioval) to be NONE. If the skeleton cannot separate those, the
design fails and must be revisited before any wiring (brief §9).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

# Import the production module by path, cwd-independent. No skip guard: if the
# module is absent the import MUST fail loudly so the done-oracle goes red.
_HOOKS_DIR = Path(__file__).resolve().parents[1]
_MODULE_PATH = _HOOKS_DIR / "oracle_strength_diff.py"
_spec = importlib.util.spec_from_file_location("oracle_strength_diff", _MODULE_PATH)
osd = importlib.util.module_from_spec(_spec)
sys.modules["oracle_strength_diff"] = osd
_spec.loader.exec_module(osd)

Level = osd.Level

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "oracle_strength"

# The real-corpus fixtures are extracted from private session transcripts and
# carry proprietary code, so they are gitignored (see bead yx3 and
# 09-test-oracle-brief.md). They exist only in a local checkout. The corpus
# tests below skip when absent so the public suite stays green; the synthetic
# unit tests (moved-assertion, is_negative_control, fail-open) always run.
_MANIFEST = _FIXTURES / "corpus_manifest.json"
_FIXTURES_PRESENT = _MANIFEST.is_file() and any(_FIXTURES.glob("*.old"))
_requires_fixtures = pytest.mark.skipif(
    not _FIXTURES_PRESENT,
    reason="real-corpus fixtures gitignored (proprietary); local checkout only",
)


# --------------------------------------------------------------------------- #
# Required-classification table — loaded from the GITIGNORED corpus manifest so
# the committed test carries no private-repo paths/notes (brief §2; advisory-
# only, no BLOCK tier). Levels: "WARN" (genuine downgrade -> must surface),
# "NONE" (strengthening/no-op -> must not warn), "ANY" (legitimate; tolerated).
# LOAD_BEARING = the subset whose verdict carries the design conclusion and must
# be earned (parsed + judged), not granted by a parse-failure fail-open.
# --------------------------------------------------------------------------- #
def _load_corpus() -> "tuple[list, list]":
    """Return (REQUIRED, LOAD_BEARING) from the gitignored manifest, or ([], [])."""
    if not _MANIFEST.is_file():
        return [], []
    cases = json.loads(_MANIFEST.read_text()).get("cases", [])
    required = [(c["case"], c["path"], c["required"], c["note"]) for c in cases]
    load_bearing = [(c["case"], c["path"]) for c in cases if c.get("load_bearing")]
    return required, load_bearing


REQUIRED, LOAD_BEARING = _load_corpus()


def _read_fixture(case: str) -> tuple[str, str]:
    old = (_FIXTURES / f"{case}.old").read_text()
    new = (_FIXTURES / f"{case}.new").read_text()
    return old, new


# --------------------------------------------------------------------------- #
# 1. Corpus replay — the headline oracle (brief §9).
# --------------------------------------------------------------------------- #
@_requires_fixtures
@pytest.mark.parametrize(
    "case,path,required,note",
    REQUIRED,
    ids=[f"{c}-{r}" for c, _p, r, _n in REQUIRED],
)
def test_corpus_replay_classifies_per_oracle(case, path, required, note):
    old, new = _read_fixture(case)
    finding = osd.evaluate(old, new, path)

    assert finding.level in (Level.NONE, Level.WARN), (
        f"{case}: advisory-only — evaluate must return NONE or WARN; "
        f"got {finding.level!r}"
    )

    if required == "WARN":
        assert finding.level == Level.WARN, (
            f"{case} ({note}) must surface as WARN — a genuine downgrade the "
            f"advisory gate exists to flag. Got {finding.level}. "
            f"reasons={getattr(finding, 'reasons', None)}"
        )
    elif required == "NONE":
        assert finding.level == Level.NONE, (
            f"{case} ({note}) must be NONE — a net strengthening must NOT warn, "
            f"else the differ is just 'warn on any churn'. Got {finding.level}. "
            f"reasons={getattr(finding, 'reasons', None)}"
        )
    # required == "ANY": any advisory level (NONE or WARN) is acceptable.


# --------------------------------------------------------------------------- #
# 1b. Earned-not-fail-open guard (QA oracle-integrity caveat, 2026-06-20).
#     The load-bearing classifications MUST come from the differ actually running
#     on parsed functions — not from a parse failure that fail-opens to NONE. A
#     fixture could otherwise go green for the wrong reason (the parser choked on
#     the real edit fragment) and silently hollow out the corpus oracle. This
#     guards exactly the cases whose verdict carries the design conclusion.
# --------------------------------------------------------------------------- #
@_requires_fixtures
@pytest.mark.parametrize("case,path", LOAD_BEARING)
def test_load_bearing_cases_are_earned_not_fail_open(case, path):
    old, new = _read_fixture(case)
    lang = osd.lang_for(path)
    try:
        old_funcs = osd.extract_test_functions(old, lang)
        osd.extract_test_functions(new, lang)
    except Exception as exc:  # _ParseError or anything else
        pytest.fail(
            f"{case}: parsing the real edit fragment raised {exc!r}. Its verdict "
            f"would be a fail-open artifact, not an earned judgment — the corpus "
            f"oracle is hollow for this load-bearing case."
        )
    assert len(old_funcs) >= 1, (
        f"{case}: 0 test functions parsed from the old side — the differ never "
        f"compared anything; a NONE/WARN here is granted by parse failure, not "
        f"judgment."
    )


# --------------------------------------------------------------------------- #
# 2. Named-fragile-implementation rejection: "WARN on any function-level
#    assertion loss". A refactor that MOVES a strong assertion (lost from fn A,
#    re-added in fn B) must classify NONE, not WARN. Synthetic (not corpus) so it
#    isolates the move-detection logic.
# --------------------------------------------------------------------------- #
def test_moved_assertion_is_not_warned():
    old = (
        "def test_a():\n    assert compute() == 42\n\n"
        "def test_b():\n    assert other() == 7\n"
    )
    new = (
        "def test_a():\n    pass\n\n"
        "def test_b():\n    assert other() == 7\n    assert compute() == 42\n"
    )
    finding = osd.evaluate(old, new, "tests/test_move.py")
    assert finding.level == Level.NONE, (
        f"a moved/re-added assertion must not WARN (it is a refactor, not a "
        f"downgrade); got {finding.level} reasons={getattr(finding, 'reasons', None)}"
    )


# --------------------------------------------------------------------------- #
# 3. is_negative_control — unit oracle for the discriminator (brief interface).
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("line", [
    'assert "\'DEV\'" not in query',
    'assert "available_sources = [" not in source',
    'expect(column_names).not_to include(\'processing_started_at\')',
    'expect(stale_order.status).not_to eq(\'processing\')',
    'with pytest.raises(ValueError):',
    'refute user.admin?',
    'self.assertNotIn("x", y)',
])
def test_is_negative_control_positive(line):
    assert osd.is_negative_control(line) is True, (
        f"expected negative-control: {line!r}"
    )


@pytest.mark.parametrize("line", [
    'assert ticket.ticket_key == "DWS-98760"',
    'assert "PARQUET" in ddl',
    'expect(budget_campaign.total_budget).to eq(750.0)',
    'assert client.get("/fe").data.strip() == b"/be"',
    'x = compute_something()',
])
def test_is_negative_control_negative(line):
    assert osd.is_negative_control(line) is False, (
        f"expected NOT a negative-control (plain positive/equality): {line!r}"
    )


# --------------------------------------------------------------------------- #
# 4. Robustness on unparseable source (brief §8): never raise, never escalate;
#    return a valid advisory level (NONE or WARN).
# --------------------------------------------------------------------------- #
def test_unparseable_python_never_raises():
    old = 'def t():\n    assert "\'DEV\'" not in query\n    if True\n'  # syntax error
    new = 'def t(:\n    pass\n'  # also broken
    finding = osd.evaluate(old, new, "tests/garbage.py")
    assert finding.level in (Level.NONE, Level.WARN), (
        "unparseable Python must degrade to an advisory level, never crash."
    )


def test_total_garbage_never_raises():
    finding = osd.evaluate("\x00\x01 not in \xff", "%%% not_to %%%", "tests/garbage.py")
    assert finding.level in (Level.NONE, Level.WARN)


# --------------------------------------------------------------------------- #
# 5. lang_for — small contract helper.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("path,expected", [
    ("tests/test_x.py", "py"),
    ("spec/foo_spec.rb", "rb"),
    ("src/x.test.js", "js"),
    ("src/x.test.ts", "ts"),
    ("README.md", "unknown"),
])
def test_lang_for(path, expected):
    assert osd.lang_for(path) == expected
