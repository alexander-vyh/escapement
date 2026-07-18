"""Codex-specific behavioral tests for beads_worktree_guard.py.

Loads the hook from the repo path (no ~/.claude/hooks/ dependency) so these run
in Codex environments. The beads-project boundary (`_in_beads_project`) is
patched so tests are hermetic and do not depend on a real .beads/ layout.

The hook fires as PreToolUse on Bash. Its primary contract (B1): `git worktree
add` inside a beads project is blocked and redirected to `bd worktree create`,
which keeps new worktree creation on the repository-managed path.

Positive control: `git worktree add` OUTSIDE a beads project (plain git) -> allow.
Negative control: `git worktree add` INSIDE a beads project -> deny + redirect.
Fast-paths: non-worktree-add git commands and non-Bash tools are allowed.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_HOOK_PATH = Path(__file__).resolve().parents[1] / "beads_worktree_guard.py"
if not _HOOK_PATH.exists():
    pytest.fail(f"beads_worktree_guard.py not found at {_HOOK_PATH}")

_spec = importlib.util.spec_from_file_location("beads_worktree_guard", _HOOK_PATH)
gate = importlib.util.module_from_spec(_spec)
sys.modules["beads_worktree_guard"] = gate
_spec.loader.exec_module(gate)


def _run_main(command: str, in_beads_project: bool = True) -> tuple[int, dict | None]:
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }
    captured = io.StringIO()
    with patch("sys.stdin", io.StringIO(json.dumps(payload))):
        with patch.object(gate, "_in_beads_project", return_value=in_beads_project):
            with patch("sys.stdout", captured):
                try:
                    code = gate.main()
                except SystemExit as exc:
                    code = exc.code or 0
    out = captured.getvalue().strip()
    return code, json.loads(out) if out else None


def assert_denied(code: int, output: dict | None) -> None:
    assert code == 0, "deny is carried by stdout JSON, not exit 2"
    assert output is not None
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_codex_worktree_add_denied_inside_beads_project():
    """Negative control: `git worktree add` in a beads project -> deny + redirect.

    This is the gate's core contract. An implementation that always allows would
    pass the positive control but fail here.
    """
    code, output = _run_main("git worktree add ../wt -b feature", in_beads_project=True)

    assert_denied(code, output)
    reason = output["hookSpecificOutput"]["permissionDecisionReason"]
    assert "beads projects" in reason, f"denial must explain the beads-project rule; got: {reason!r}"
    assert "bd worktree" in reason, f"denial must redirect to bd worktree create; got: {reason!r}"


def test_codex_worktree_add_allowed_outside_beads_project():
    """Positive control: `git worktree add` in a plain git repo -> allow.

    Without this, an implementation that always denies would pass only the
    negative control.
    """
    code, output = _run_main("git worktree add ../wt -b feature", in_beads_project=False)

    assert code == 0
    assert output is None, f"worktree add outside a beads project must be allowed; got: {output!r}"


def test_codex_non_worktree_git_command_allowed():
    """Fast-path: an ordinary git command (not `worktree add`) is not gated by B1."""
    code, output = _run_main("git status", in_beads_project=True)

    assert code == 0
    assert output is None, "non-worktree-add git commands must be allowed"


def test_codex_non_bash_tool_allowed():
    """Fast-path: a non-Bash tool is never gated."""
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Write", "tool_input": {"file_path": "x"}}
    captured = io.StringIO()
    with patch("sys.stdin", io.StringIO(json.dumps(payload))):
        with patch("sys.stdout", captured):
            try:
                code = gate.main()
            except SystemExit as exc:
                code = exc.code or 0
    assert code == 0
    assert captured.getvalue().strip() == "", "non-Bash tools must be allowed silently"
