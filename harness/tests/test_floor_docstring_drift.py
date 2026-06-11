"""Finding N + NOTE 4 — stale 'regex floor' / 'deterministic floor' / bare 'floor'
docstring drift.

ARCHITECTURE: the regex/deterministic floor was deleted (see test_winddown_judge.py
"the regex floor is KILLED"). Wind-down classification is now "semantic or nothing":
the local-LLM judge's verdict is the sole signal; a None verdict fails open to allow.
There is no floor left to "fall back to", "defer to", or have "recall over".

But several docstrings / inline comments in winddown_judge.py and stop_hook.py still
describe the deleted floor — they tell a future reader the code does something it no
longer does. That is documentation drift, not a behavior bug, so there is no behavioral
oracle. This ONE cheap architecture guard pins the cleanup: a docstring/comment must not
AFFIRMATIVELY describe the code falling back to / deferring to a floor that is gone.

NOTE 4 folded in: `winddown_judge.model_verdict`'s comment "...→ defer to floor" uses
the bare word "floor" (not "regex floor"), so it is caught by the fallback-context rule
below, not just the literal-phrase rule.

WHY THIS IS A LEGITIMATE PIN, NOT OVER-PINNING:
- It flags only the AFFIRMATIVE fallback sense ("defers to the regex floor", "falls back
  to the floor", "recall over the regex floor", "the sibling regex floor"). It does NOT
  forbid the word "floor" wholesale — a future `math.floor` or an unrelated "floor" is
  untouched (the fallback-context regexes don't match it).
- It carves out the CORRECT NEGATION ("there is no regex floor to fall back to"), which
  accurately describes the new design — flagging that would push a dev to DELETE accurate
  documentation, the over-pin failure mode.
- It never spuriously fires after the sweep, and it catches future RE-INTRODUCTION of the
  deleted floor vocabulary.

Scoped to the two modules the final review named (winddown_judge.py:72,91;
stop_hook.py:204,218,260) plus the sibling drift sites in the same files the same sweep
should catch (winddown_judge.py:28).

Run: python3 -m pytest harness/tests/test_floor_docstring_drift.py -q
"""

from __future__ import annotations

import pathlib
import re

import pytest

BIN = pathlib.Path(__file__).resolve().parent.parent / "bin"

# Stale-context patterns: the word "floor" used AFFIRMATIVELY as a fallback the code
# relies on. Each pattern is anchored on a fallback verb / qualifier so it does NOT
# match an unrelated "floor" (e.g. math.floor) or the correct negation form. Matched
# case-insensitively against the FULL module text (whitespace-collapsed so wrapped
# docstrings join), which makes line-wrapping irrelevant.
# `_QUAL` matches an optional run of "regex"/"deterministic" qualifiers in any
# order/combination ("regex", "deterministic", "deterministic regex"), so
# "...the deterministic regex floor" is caught as well as the bare "...floor".
_QUAL = r"(?:(?:regex|deterministic) ){0,2}"
_STALE_FALLBACK_PATTERNS = (
    rf"defers? to (?:the )?{_QUAL}floor",      # "defers to the regex floor", "defer to floor"
    rf"falls? back to (?:the )?{_QUAL}floor",  # "falls back to the deterministic regex floor"
    rf"recall over (?:the )?{_QUAL}floor",     # "recall over the regex floor"
    rf"sibling {_QUAL}floor",                  # "the sibling regex floor importable"
)

# Correct negations to EXCLUDE: "no regex floor to fall back to" accurately describes
# the new architecture. We strip these spans before scanning for the stale patterns.
_NEGATION_PATTERNS = (
    rf"no {_QUAL}floor to fall back to",
    rf"no {_QUAL}floor to defer to",
)

# The two modules the final review flagged for the floor-deletion sweep.
_MODULES = ("winddown_judge.py", "stop_hook.py")


def _collapse(text: str) -> str:
    """Lower-case + collapse all runs of whitespace to single spaces, so a docstring
    that wraps "there is no\n regex floor ..." across physical lines reads as one
    string for both the negation carve-out and the stale-pattern scan."""
    return re.sub(r"\s+", " ", text.lower())


@pytest.mark.parametrize("module", _MODULES)
def test_no_stale_floor_fallback_descriptions(module):
    """A module that no longer HAS a floor must not affirmatively describe falling
    back to / deferring to one.

    Asserts on the source text (the documentation surface a future reader sees), not
    on runtime behavior — there is no behavior to assert; the floor is gone. The
    correct negation ("there is no regex floor to fall back to") is allowed. The
    failure message lists the offending fragments so the sweep is mechanical."""
    path = BIN / module
    assert path.is_file(), f"expected harness module not found: {path}"
    collapsed = _collapse(path.read_text(encoding="utf-8"))

    # Remove the correct-negation spans so they cannot match a stale pattern.
    scrubbed = collapsed
    for neg in _NEGATION_PATTERNS:
        scrubbed = re.sub(neg, " [allowed-negation] ", scrubbed)

    offenders = []
    for pat in _STALE_FALLBACK_PATTERNS:
        for m in re.finditer(pat, scrubbed):
            start = max(0, m.start() - 30)
            end = min(len(scrubbed), m.end() + 10)
            offenders.append(f"…{scrubbed[start:end].strip()}…")

    assert not offenders, (
        f"{module} still affirmatively describes a fallback to the DELETED floor "
        f"subsystem (Finding N + NOTE 4); the floor-deletion sweep must remove these:\n  "
        + "\n  ".join(offenders)
    )
