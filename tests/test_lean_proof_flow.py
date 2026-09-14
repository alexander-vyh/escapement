"""Contracts for the lean acceptance and review flow.

These checks validate the instructions agents actually receive. The independent
outcome check remains the planted review probe; prose presence alone is not
claimed as proof that a reviewer reasoned correctly.
"""

from __future__ import annotations

from pathlib import Path
import re

import pytest


ROOT = Path(__file__).resolve().parents[1]
ORACLE_SKILLS = (
    Path("claude/skills/behavioral-test-oracle-review/SKILL.md"),
    Path("plugins/escapement-claude/skills/behavioral-test-oracle-review/SKILL.md"),
)
REVIEW_SKILLS = (
    Path("claude/skills/beads-execution/SKILL.md"),
    Path("plugins/escapement-claude/skills/beads-execution/SKILL.md"),
)


def _between(text: str, start: str, end: str) -> str:
    assert start in text
    tail = text.split(start, 1)[1]
    assert end in tail
    return tail.split(end, 1)[0]


def _assert_constructible_acceptance_contract(text: str) -> None:
    review = _between(text, "## Review Rule", "## Common Oracle Smells").casefold()
    assert re.search(
        r"trace.{0,120}literal fixture or input.{0,120}through.{0,120}"
        r"public entry point.{0,120}to.{0,120}final observable assertion",
        review,
        re.DOTALL,
    )
    assert re.search(
        r"(?:if|when).{0,120}cannot be constructed.{0,120}reject",
        review,
        re.DOTALL,
    )


def test_oracle_review_requires_a_constructible_acceptance_path() -> None:
    for path in ORACLE_SKILLS:
        _assert_constructible_acceptance_contract((ROOT / path).read_text())


@pytest.mark.parametrize(
    "missing",
    (
        "literal",
        "fixture or input",
        "public entry point",
        "final observable assertion",
        "cannot be constructed",
        "reject",
    ),
)
def test_reachability_marker_without_the_path_cannot_pass(missing: str) -> None:
    complete = (
        "## Review Rule\nFor every acceptance outcome, trace the literal fixture or input "
        "through the public entry point to the final observable assertion. If the path "
        "cannot be constructed, reject the test plan.\n## Common Oracle Smells\n"
    )
    with pytest.raises(AssertionError):
        _assert_constructible_acceptance_contract(complete.replace(missing, "reachable"))


def test_unordered_acceptance_keywords_cannot_pass_as_a_trace() -> None:
    keyword_soup = (
        "## Review Rule\nLiteral fixture or input; final observable assertion; "
        "public entry point; cannot be constructed; reject; trace; through; to.\n"
        "## Common Oracle Smells\n"
    )

    with pytest.raises(AssertionError):
        _assert_constructible_acceptance_contract(keyword_soup)


def _assert_reference_first_review(text: str) -> None:
    initial = _between(
        text,
        "### 2e. Spec Compliance Review",
        "### 2e-i. Post-verdict claims comparison",
    ).casefold()
    comparison = _between(
        text,
        "### 2e-i. Post-verdict claims comparison",
        "### 2e-ii. Specialist Advisor Routing",
    ).casefold()
    assert "implementer's report" not in initial
    assert "initial verdict" in initial
    assert "requested" in initial
    assert "## implementation under review" in initial
    assert "worktree: <absolute implementer worktree path>" in initial
    assert "base sha: <commit before this task>" in initial
    assert "head sha: <implementer commit>" in initial
    assert re.search(
        r"do not fall back to the coordinator's\s+working directory",
        initial,
    )
    assert "independently authored" in initial
    assert re.search(r"must not\s+claim independent verification", initial)
    assert "same reviewer" in comparison
    assert "implementer's report" in comparison
    assert "discrepanc" in comparison
    assert "must not replace" in comparison


def test_spec_review_forms_a_verdict_before_receiving_author_claims() -> None:
    for path in REVIEW_SKILLS:
        _assert_reference_first_review((ROOT / path).read_text())
