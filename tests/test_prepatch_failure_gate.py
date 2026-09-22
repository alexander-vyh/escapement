"""Behavioral controls for the pre-patch failure gate.

Every case below runs the real hook against a real synthetic git repository with a
real pytest run inside it. Nothing is mocked, because the property under test *is*
"does executing the tests without the production change reveal anything" — a mocked
verifier would assert the plumbing and prove nothing.

The pairing is deliberate. `test_vacuous_test_is_asked_about` alone would pass an
implementation that asks on every landing; `test_genuinely_failing_test_is_allowed`
kills it. `test_placeholder_waiver_is_rejected` alone would pass an implementation
that ignores the waiver file entirely; `test_substantive_waiver_is_accepted` kills that.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GATE = ROOT / "claude" / "hooks" / "prepatch_failure_gate.py"
VERIFIER_DIR = ROOT / "harness" / "bin"

PRODUCTION_BEFORE = "def discount(total):\n    return total\n"
PRODUCTION_AFTER = "def discount(total):\n    if total is None:\n        return 0\n    return total\n"

# Fails without the production change: None would raise before the guard exists.
DETECTING_TEST = (
    "from app import discount\n\n\n"
    "def test_none_total_is_zero():\n"
    "    assert discount(None) == 0\n"
)

# Passes with or without the production change. This is the shape the gate exists
# to catch: green, plausible, and evidence about nothing.
VACUOUS_TEST = (
    "from app import discount\n\n\n"
    "def test_total_passes_through():\n"
    "    assert discount(10) == 10\n"
)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.update({
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    })
    return subprocess.run(["git", *args], cwd=str(repo), env=env, check=True,
                          capture_output=True, text=True)


def _make_repo(tmp_path: Path, test_body: str, production: str = PRODUCTION_AFTER) -> Path:
    """A repo whose `main` holds the pre-change state and whose feature branch holds
    the production change plus `test_body`."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "app.py").write_text(PRODUCTION_BEFORE)
    (repo / "tests").mkdir()
    (repo / "tests" / "__init__.py").write_text("")
    (repo / "conftest.py").write_text(
        "import sys, pathlib\nsys.path.insert(0, str(pathlib.Path(__file__).parent))\n"
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")

    _git(repo, "checkout", "-q", "-b", "feature")
    (repo / "app.py").write_text(production)
    (repo / "tests" / "test_discount.py").write_text(test_body)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "guard against a missing total")
    return repo


def _run_gate(repo: Path, command: str = "git push origin feature", tmp_path: Path | None = None):
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(repo),
    }
    env = dict(os.environ)
    env["PREPATCH_VERIFY_DIR"] = str(VERIFIER_DIR)
    # Keep the corpus of a test run out of the real signal store.
    env["GATE_SIGNAL_FALLBACK_DIR"] = str((tmp_path or repo) / "signal")
    result = subprocess.run([sys.executable, str(GATE)], input=json.dumps(payload),
                            capture_output=True, text=True, timeout=300, env=env)
    decision = None
    if result.stdout.strip():
        decision = json.loads(result.stdout)["hookSpecificOutput"]
    return result, decision


def test_vacuous_test_is_asked_about(tmp_path):
    """A changed test that passes without the production change is not evidence."""
    repo = _make_repo(tmp_path, VACUOUS_TEST)
    result, decision = _run_gate(repo, tmp_path=tmp_path)
    assert result.returncode == 0
    assert decision is not None, "a vacuous oracle must not land silently"
    assert decision["permissionDecision"] == "ask"
    assert "still PASSES" in decision["permissionDecisionReason"]


def test_genuinely_failing_test_is_allowed(tmp_path):
    """The control that kills an implementation which asks on every landing."""
    repo = _make_repo(tmp_path, DETECTING_TEST)
    result, decision = _run_gate(repo, tmp_path=tmp_path)
    assert result.returncode == 0
    assert decision is None, (
        "a test that fails without the production change is exactly what the gate "
        f"wants; it must not be questioned (got {decision})"
    )


def test_production_change_with_no_test_is_asked_about(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "app.py").write_text(PRODUCTION_BEFORE)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "feature")
    (repo / "app.py").write_text(PRODUCTION_AFTER)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "guard, untested")

    _, decision = _run_gate(repo, tmp_path=tmp_path)
    assert decision is not None and decision["permissionDecision"] == "ask"
    assert "no test file" in decision["permissionDecisionReason"]


def test_docs_only_change_is_allowed(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "README.md").write_text("before\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "checkout", "-q", "-b", "feature")
    (repo / "README.md").write_text("after\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "docs")

    _, decision = _run_gate(repo, tmp_path=tmp_path)
    assert decision is None, "a change with no production python has nothing to verify"


def test_non_landing_command_is_ignored(tmp_path):
    repo = _make_repo(tmp_path, VACUOUS_TEST)
    result, decision = _run_gate(repo, command="git status", tmp_path=tmp_path)
    assert decision is None
    assert result.stdout.strip() == ""


@pytest.mark.parametrize("reason", ["tbd", "n/a", "todo later"])
def test_placeholder_or_short_waiver_is_rejected(tmp_path, reason):
    """Presence of a waiver file is not acceptance (gate-design.md Rule 3)."""
    repo = _make_repo(tmp_path, VACUOUS_TEST)
    (repo / ".beads").mkdir()
    (repo / ".beads" / ".prepatch-waiver").write_text(reason)
    _, decision = _run_gate(repo, tmp_path=tmp_path)
    assert decision is not None and decision["permissionDecision"] == "ask"
    assert "was not accepted" in decision["permissionDecisionReason"]


def test_waiver_that_only_echoes_changed_files_is_rejected(tmp_path):
    """A reason naming only the artifact it excuses teaches the corpus nothing."""
    repo = _make_repo(tmp_path, VACUOUS_TEST)
    (repo / ".beads").mkdir()
    (repo / ".beads" / ".prepatch-waiver").write_text(
        "app.py tests/test_discount.py"
    )
    _, decision = _run_gate(repo, tmp_path=tmp_path)
    assert decision is not None and decision["permissionDecision"] == "ask"


def test_substantive_waiver_is_accepted(tmp_path):
    """The control that kills an implementation which ignores the waiver file."""
    repo = _make_repo(tmp_path, VACUOUS_TEST)
    (repo / ".beads").mkdir()
    (repo / ".beads" / ".prepatch-waiver").write_text(
        "vendored upstream library bump; behavior is covered by the provider's own "
        "conformance suite which we run nightly against their published fixtures"
    )
    _, decision = _run_gate(repo, tmp_path=tmp_path)
    assert decision is None, "a substantive waiver is a first-class escape, not a nudge"


def test_ask_message_carries_the_escape_and_a_reproduction(tmp_path):
    """gate-design.md Rule 1: the way forward is IN the message, not in the source."""
    repo = _make_repo(tmp_path, VACUOUS_TEST)
    _, decision = _run_gate(repo, tmp_path=tmp_path)
    message = decision["permissionDecisionReason"]
    assert "prepatch_verify.py" in message, "must say how to reproduce the verdict"
    assert ".prepatch-waiver" in message, "must name the waiver escape"
    assert "proceed" in message, "must name the zero-friction escape"
