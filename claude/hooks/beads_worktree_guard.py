#!/usr/bin/env python3
"""Claude Code hook: redirect ``git worktree add`` to ``bd worktree create``
inside beads projects.

Registered as a PreToolUse matcher scoped to ``Bash(git worktree add:*)`` in
settings.template.json — so it fires ONLY on that command prefix and adds zero
overhead to every other Bash call.

Why this exists (see the ``beads-worktree`` skill for the full rationale and
recovery steps): in a project with a ``.beads/`` directory, a bare
``git worktree add`` produces a broken worktree — an empty ``.beads/`` with no
Dolt database, ``bd`` commands failing with "database not found", and a
``bd init`` "fix" that shadows the real database. ``bd worktree create`` wires
up the ``.beads/redirect`` so the worktree shares the main repo's database.

This guard is CONDITIONAL, unlike no_direct_send_guard:
  - In a beads project (``.beads/`` found at cwd or any ancestor, or BEADS_DIR
    set) → DENY and redirect to the concrete ``bd worktree create`` command.
  - Anywhere else → ALLOW (exit 0, no output): plain git repos must be able to
    create worktrees normally.

Deny mechanism (canonical single-mechanism contract): a permissionDecision=
"deny" JSON document on stdout, exit 0. NOT exit 2.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import NoReturn, Optional

# Shared signal capture per claude/rules/gate-design.md Rule 2.
sys.path.insert(0, str(Path(__file__).parent))
try:
    from _gate_signal import record as _record_signal
except ImportError:  # pragma: no cover
    def _record_signal(*_args, **_kwargs) -> None:
        return None


_WORKTREE_ADD_RE = re.compile(r"^\s*git\s+worktree\s+add\b")


def _in_beads_project(cwd: Path) -> bool:
    """A beads context: BEADS_DIR exported, or a ``.beads/`` dir at cwd or any
    ancestor (worktree commands aren't always run from the repo root)."""
    if os.environ.get("BEADS_DIR"):
        return True
    try:
        start = cwd.resolve()
    except OSError:
        start = cwd
    for d in (start, *start.parents):
        if (d / ".beads").is_dir():
            return True
    return False


def _parse_path_and_branch(command: str) -> tuple[Optional[str], Optional[str]]:
    """Extract the worktree path and branch from a ``git worktree add`` command
    so the redirect can echo them. Best-effort: returns (path, branch), either
    of which may be None if unparseable."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None, None
    # Drop leading "git worktree add".
    try:
        add_idx = tokens.index("add")
    except ValueError:
        return None, None
    rest = tokens[add_idx + 1 :]

    branch: Optional[str] = None
    path: Optional[str] = None
    i = 0
    while i < len(rest):
        tok = rest[i]
        if tok in ("-b", "-B"):
            if i + 1 < len(rest):
                branch = rest[i + 1]
            i += 2
            continue
        if tok.startswith("-"):
            i += 1
            continue
        if path is None:
            path = tok
        i += 1
    return path, branch


def _suggestion(path: Optional[str], branch: Optional[str]) -> str:
    cmd = "bd worktree create"
    cmd += f" {path}" if path else " <path>"
    if branch:
        cmd += f" -b {branch}"
    else:
        cmd += " -b <branch>"
    return cmd


def deny(command: str, cwd: Path) -> NoReturn:
    path, branch = _parse_path_and_branch(command)
    suggestion = _suggestion(path, branch)
    reason = (
        "`git worktree add` is blocked in beads projects: a bare git worktree "
        "gets an empty `.beads/` with no Dolt database, so `bd` commands fail. "
        f"Use `{suggestion}` instead — it sets up the `.beads/redirect` so the "
        "worktree shares the main repo's database. "
        "(If beads already broke in a worktree, see the `beads-worktree` skill "
        "for recovery — do NOT run `bd init` inside a worktree.)"
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # fail-open: a parse bug must not wedge the tool pipeline

    if data.get("tool_name", "") != "Bash":
        return 0
    tool_input = data.get("tool_input", {})
    if not isinstance(tool_input, dict):
        return 0
    command = tool_input.get("command", "")
    if not command or not _WORKTREE_ADD_RE.match(command):
        return 0  # not a `git worktree add` — allow (defense in depth)

    cwd_raw = data.get("cwd") or data.get("workingDirectory") or os.getcwd()
    cwd = Path(cwd_raw)

    if not _in_beads_project(cwd):
        return 0  # plain git repo — worktree add is fine

    _record_signal(
        gate_name="beads_worktree_guard",
        decision="deny",
        reason="git worktree add redirected to bd worktree create",
        tool="Bash",
    )
    deny(command, cwd)
    return 0  # unreachable


if __name__ == "__main__":
    sys.exit(main())
