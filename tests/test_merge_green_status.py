"""The merge gate must observe green, not just read a declaration.

`.escapement/repo.json` says `auto_merge_on_green`. Until this change the gate resolved
the declaration and allowed the merge without ever looking at a check, which is how this
repository merged with a red pipeline and why `AGENTS.md` carried
`merge-green-status=unsupported`.

Pairing matters here more than usual, because both degenerate implementations look fine
against a single test:

- `test_green_pr_is_allowed` alone passes an implementation that ignores checks entirely
  (the old behavior). `test_failing_pr_is_denied` kills it.
- `test_failing_pr_is_denied` alone passes an implementation that denies every merge.
  `test_green_pr_is_allowed` kills that one.
- `test_unconfigured_repo_is_denied` holds the pre-existing authority half in place, so
  adding the green half cannot quietly drop it.

The gate is driven end to end through a stub `gh` on PATH, so the real subprocess call,
argument construction, and JSON parsing are exercised rather than mocked away.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GATE = ROOT / "claude" / "hooks" / "merge_authorization_gate.py"

sys.path.insert(0, str(ROOT / "claude" / "hooks"))
import _merge_green_status as green  # noqa: E402


def _check(name: str, conclusion: str | None, status: str = "COMPLETED") -> dict:
    entry = {"__typename": "CheckRun", "name": name, "status": status}
    if conclusion is not None:
        entry["conclusion"] = conclusion
    return entry


def _stub_gh(tmp_path: Path, payload: dict | None, exit_code: int = 0, stderr: str = "") -> Path:
    """A `gh` on PATH that answers `pr view --json ...` with a fixed payload."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"payload = {json.dumps(json.dumps(payload) if payload is not None else '')}\n"
        f"sys.stderr.write({json.dumps(stderr)})\n"
        "sys.stdout.write(payload)\n"
        f"sys.exit({exit_code})\n"
    )
    gh.chmod(0o755)
    return bin_dir


def _repo(tmp_path: Path, declaration: dict | None) -> Path:
    repo = tmp_path / "repo"
    (repo / ".escapement").mkdir(parents=True, exist_ok=True)
    if declaration is not None:
        (repo / ".escapement" / "repo.json").write_text(json.dumps(declaration))
    return repo


AUTHORIZED = {"intended_outcome": "merged-and-deployed", "auto_merge_on_green": True}


def _run_gate(repo: Path, command: str, bin_dir: Path | None, tmp_path: Path):
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(repo),
    }
    env = dict(os.environ)
    if bin_dir is not None:
        env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    signal_home = tmp_path / "signal" / ".beads"
    signal_home.mkdir(parents=True, exist_ok=True)
    env["BEADS_DIR"] = str(signal_home)
    env["GATE_SIGNAL_FALLBACK_DIR"] = str(tmp_path / "signal")

    result = subprocess.run([sys.executable, str(GATE)], input=json.dumps(payload),
                            capture_output=True, text=True, timeout=120, env=env)
    decision = None
    if result.stdout.strip():
        decision = json.loads(result.stdout)["hookSpecificOutput"]
    return result, decision


# --------------------------------------------------------------------------
# End-to-end gate behavior
# --------------------------------------------------------------------------

def test_green_pr_is_allowed(tmp_path):
    repo = _repo(tmp_path, AUTHORIZED)
    bin_dir = _stub_gh(tmp_path, {"number": 7, "state": "OPEN", "statusCheckRollup": [
        _check("pytest", "SUCCESS"), _check("gitleaks", "SUCCESS")]})
    _, decision = _run_gate(repo, "gh pr merge 7 --squash", bin_dir, tmp_path)
    assert decision is None, f"a green PR in an authorized repo must merge (got {decision})"


def test_failing_pr_is_denied(tmp_path):
    """The defect this change exists to fix."""
    repo = _repo(tmp_path, AUTHORIZED)
    bin_dir = _stub_gh(tmp_path, {"number": 7, "state": "OPEN", "statusCheckRollup": [
        _check("pytest", "FAILURE"), _check("gitleaks", "SUCCESS")]})
    _, decision = _run_gate(repo, "gh pr merge 7 --squash", bin_dir, tmp_path)
    assert decision is not None and decision["permissionDecision"] == "deny"
    assert "pytest" in decision["permissionDecisionReason"], "must name the failing check"


def test_pending_pr_is_denied(tmp_path):
    """Not green YET is not green. A check with no conclusion is the common in-flight
    shape and the one a naive reader mistakes for a pass."""
    repo = _repo(tmp_path, AUTHORIZED)
    bin_dir = _stub_gh(tmp_path, {"number": 7, "state": "OPEN", "statusCheckRollup": [
        _check("pytest", None, status="IN_PROGRESS"), _check("gitleaks", "SUCCESS")]})
    _, decision = _run_gate(repo, "gh pr merge 7", bin_dir, tmp_path)
    assert decision is not None and decision["permissionDecision"] == "deny"
    assert "not green YET" in decision["permissionDecisionReason"]


def test_pr_without_checks_is_denied(tmp_path):
    repo = _repo(tmp_path, AUTHORIZED)
    bin_dir = _stub_gh(tmp_path, {"number": 7, "state": "OPEN", "statusCheckRollup": []})
    _, decision = _run_gate(repo, "gh pr merge 7", bin_dir, tmp_path)
    assert decision is not None and decision["permissionDecision"] == "deny"
    assert "no checks" in decision["permissionDecisionReason"]


def test_unobservable_state_is_denied(tmp_path):
    """gh failing is not evidence of green; an unresolvable check is never upgraded."""
    repo = _repo(tmp_path, AUTHORIZED)
    bin_dir = _stub_gh(tmp_path, None, exit_code=1, stderr="no pull requests found")
    _, decision = _run_gate(repo, "gh pr merge", bin_dir, tmp_path)
    assert decision is not None and decision["permissionDecision"] == "deny"
    assert "could not be observed" in decision["permissionDecisionReason"]


def test_auto_flag_is_allowed_without_observing(tmp_path):
    """`--auto` hands the same green condition to GitHub, so we honor it rather than
    duplicate it. No stub gh is installed: reaching for one would prove we ignored the
    delegation."""
    repo = _repo(tmp_path, AUTHORIZED)
    _, decision = _run_gate(repo, "gh pr merge 7 --squash --auto", None, tmp_path)
    assert decision is None


def test_unconfigured_repo_is_still_denied(tmp_path):
    """The authority half must survive the addition of the green half."""
    repo = _repo(tmp_path, None)
    bin_dir = _stub_gh(tmp_path, {"number": 7, "state": "OPEN", "statusCheckRollup": [
        _check("pytest", "SUCCESS")]})
    _, decision = _run_gate(repo, "gh pr merge 7", bin_dir, tmp_path)
    assert decision is not None and decision["permissionDecision"] == "deny"
    assert "auto_merge_on_green" in decision["permissionDecisionReason"]


def test_substantive_waiver_still_merges_a_red_pr(tmp_path):
    """gate-design.md Rule 1: the escape must actually work on the new denial path."""
    repo = _repo(tmp_path, AUTHORIZED)
    bin_dir = _stub_gh(tmp_path, {"number": 7, "state": "OPEN", "statusCheckRollup": [
        _check("pytest", "FAILURE")]})
    command = (
        "gh pr merge 7 --squash  "
        "# merge-authorization-waiver: the only red check is a flaky network smoke test "
        "the user confirmed is unrelated to this change"
    )
    _, decision = _run_gate(repo, command, bin_dir, tmp_path)
    assert decision is None


def test_denial_names_every_escape(tmp_path):
    repo = _repo(tmp_path, AUTHORIZED)
    bin_dir = _stub_gh(tmp_path, {"number": 7, "state": "OPEN", "statusCheckRollup": [
        _check("pytest", "FAILURE")]})
    _, decision = _run_gate(repo, "gh pr merge 7", bin_dir, tmp_path)
    reason = decision["permissionDecisionReason"]
    assert "gh pr checks" in reason
    assert "--auto" in reason
    assert "merge-authorization-waiver" in reason


def test_non_merge_command_is_ignored(tmp_path):
    repo = _repo(tmp_path, AUTHORIZED)
    result, decision = _run_gate(repo, "gh pr view 7", None, tmp_path)
    assert decision is None and result.stdout.strip() == ""


# --------------------------------------------------------------------------
# Classification and reference parsing
# --------------------------------------------------------------------------

def test_skipped_and_neutral_do_not_block():
    """Excluding them would make every conditional job an eternal red."""
    status = green.classify_rollup([
        _check("a", "SUCCESS"), _check("b", "SKIPPED"), _check("c", "NEUTRAL")])
    assert status.state == "green"


@pytest.mark.parametrize("conclusion", ["CANCELLED", "TIMED_OUT", "ACTION_REQUIRED",
                                        "STARTUP_FAILURE"])
def test_non_failure_bad_conclusions_are_not_green(conclusion):
    assert green.classify_rollup([_check("a", conclusion)]).state == "failing"


def test_unreadable_rollup_entries_are_not_green():
    """A non-empty rollup we cannot parse must never become an authorization — the one
    direction this module is not allowed to fail in."""
    assert green.classify_rollup(["surprise", 42]).state == "unknown"


def test_legacy_status_context_shape_is_understood():
    """Rollups mix CheckRun and StatusContext; a parser that knows only one silently
    treats the other as green."""
    assert green.classify_rollup(
        [{"__typename": "StatusContext", "context": "ci/circleci", "state": "FAILURE"}]
    ).state == "failing"
    assert green.classify_rollup(
        [{"__typename": "StatusContext", "context": "ci/circleci", "state": "SUCCESS"}]
    ).state == "green"


def test_failing_beats_pending():
    status = green.classify_rollup([
        _check("a", "FAILURE"), _check("b", None, status="QUEUED")])
    assert status.state == "failing"


@pytest.mark.parametrize("command,expected", [
    ("gh pr merge 248 --squash", "248"),
    ("gh pr merge --squash", None),
    ("gh pr merge https://github.com/o/r/pull/9 -m", "https://github.com/o/r/pull/9"),
    ("gh pr merge my-branch --rebase", "my-branch"),
    ("gh pr merge --match-head-commit abc123 --squash", None),
    ("gh pr merge -b 'body text' 12", "12"),
    ("cd /wt && gh pr merge 5 --squash && echo 7", "5"),
])
def test_pr_reference_parsing(command, expected):
    """A flag's value must never be mistaken for the PR reference — checking the wrong
    PR's status is worse than checking none, because it looks authoritative."""
    assert green.extract_pr_ref(command) == expected
