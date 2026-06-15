"""Codex-specific behavioral tests for outcome_assertion_gate.py.

These tests load the hook from the repo path so they run in Codex environments
without ~/.claude/hooks/. They use patch("outcome_assertion_gate.get_test_diff")
to inject test-file content without needing a live git checkout.

The gate fires as PreToolUse on Bash when `gh pr create` is in the command.
It prompts (ask, not deny) when test functions have only structural assertions.

Positive control: a PR create with outcome assertions (specific value checks) is
ALLOWED — proves the gate does not over-block good tests.

Negative control: a PR create with only structural assertions (is not None,
len > 0) triggers an ASK — proves the gate surfaces the quality gap.

Fast-path: non-PR commands and non-Bash tools pass unconditionally.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_HOOK_PATH = Path(__file__).resolve().parents[1] / "outcome_assertion_gate.py"
if not _HOOK_PATH.exists():
    pytest.fail(f"outcome_assertion_gate.py not found at {_HOOK_PATH}")

_spec = importlib.util.spec_from_file_location("outcome_assertion_gate", _HOOK_PATH)
gate = importlib.util.module_from_spec(_spec)
sys.modules["outcome_assertion_gate"] = gate
_spec.loader.exec_module(gate)


# ---------------------------------------------------------------------------
# Test-file content fixtures
# ---------------------------------------------------------------------------

STRUCTURAL_ONLY_TESTS = """\
### FILE: tests/test_result.py
def test_result_exists():
    result = compute()
    assert result is not None
    assert len(result) > 0
"""

OUTCOME_ASSERTION_TESTS = """\
### FILE: tests/test_result.py
def test_result_has_correct_score():
    result = compute()
    assert result is not None
    assert result.score == 75
"""

NO_TEST_FILES = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_main(command: str, diff_content: str = NO_TEST_FILES) -> tuple[int, dict | None]:
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }
    captured = io.StringIO()
    with patch("sys.stdin", io.StringIO(json.dumps(payload))):
        with patch("outcome_assertion_gate.get_test_diff", return_value=diff_content):
            with patch("sys.stdout", captured):
                code = gate.main()
    out = captured.getvalue().strip()
    return code, json.loads(out) if out else None


# ---------------------------------------------------------------------------
# Codex-specific behavioral tests
# ---------------------------------------------------------------------------


def test_codex_pr_create_asks_on_structural_only_tests():
    """Negative control: gh pr create with structural-only tests → ask decision.

    Proves the gate surfaces assertion quality gaps at PR time. An implementation
    that always allows would pass the positive control but fail here.
    """
    code, output = _run_main("gh pr create --title 'add feature'", STRUCTURAL_ONLY_TESTS)

    assert code == 0, "advisory gate signals via JSON, not exit code"
    assert output is not None, "gate must emit a JSON decision for structural-only tests"
    assert output["hookSpecificOutput"]["permissionDecision"] == "ask", (
        "outcome assertion gate is advisory (ask), not a hard block (deny)"
    )
    reason = output["hookSpecificOutput"]["permissionDecisionReason"]
    assert "structural" in reason.lower() or "assertion" in reason.lower(), (
        f"ask reason must explain the assertion quality concern; got: {reason!r}"
    )


def test_codex_pr_create_allows_outcome_assertions():
    """Positive control: gh pr create with specific-value assertions → allow.

    Proves the gate does not block PRs that already have outcome-quality tests.
    """
    code, output = _run_main("gh pr create --title 'add feature'", OUTCOME_ASSERTION_TESTS)

    assert code == 0
    assert output is None, (
        f"outcome assertions must allow without any JSON output; got: {output!r}"
    )


def test_codex_pr_create_allows_when_no_test_files_changed():
    """Fast-path: gh pr create with no changed test files → allow unconditionally."""
    code, output = _run_main("gh pr create --title 'update docs'", NO_TEST_FILES)

    assert code == 0
    assert output is None


def test_codex_non_pr_bash_command_is_allowed():
    """Fast-path: non-PR Bash commands bypass the gate entirely."""
    code, output = _run_main("pytest tests/", STRUCTURAL_ONLY_TESTS)

    assert code == 0
    assert output is None, "non-PR commands must never trigger the assertion gate"


def test_codex_decision_is_single_mechanism():
    """Decision contract: exactly ONE JSON document on stdout AND exit 0.

    A permissionDecision JSON plus a non-zero exit is a contradictory
    double-signal. Asserting exit 0 and parsing stdout as a single JSON document
    rejects both forms of doubling.
    """
    code, output = _run_main("gh pr create --title 'test'", STRUCTURAL_ONLY_TESTS)

    assert code == 0, (
        "decision must be carried by stdout JSON, not by exit code — "
        "permissionDecision=ask plus non-zero exit is a double-signal"
    )
    # json.loads raises on two stacked documents, which rejects a doubled output
    assert output is not None
    assert output["hookSpecificOutput"]["permissionDecision"] in ("ask", "deny", "allow")
