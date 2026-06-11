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


# A1 FIX: the original anchor (^\s*git\s+worktree\s+add) missed `git -C <path>
# worktree add`, `git --git-dir=... worktree add`, `cd ... && git worktree add`,
# and `env ... git worktree add`. The new pattern uses re.search with a non-greedy
# span `[^\n|;&]*?` between `git` and `worktree add`, which:
#   - crosses global flags and space-separated flag args (e.g. `-C /path`)
#   - stops at shell separators (|, ;, &) and newlines so it does not cross
#     into a different command in a pipeline
#   - leaves innocent git commands (log, status, diff, branch, fetch) unmatched
#     because they contain no `worktree add` token
_WORKTREE_ADD_RE = re.compile(r"\bgit\b[^\n|;&]*?\bworktree\s+add\b")


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


# A2: patterns that indicate state-changing git subcommands vs read-only ones.
# State-changing: checkout, switch, pull, merge, commit, rebase, reset, cherry-pick.
# Read-only: log, status, diff, show, branch (--list), fetch (non-mutating read).
_STATE_CHANGING_GIT_RE = re.compile(
    r"\bgit(?:\s+(?:-\w[^\s]*|--\w[^\s]*)|\s+-C\s+\S+)*\s+"
    r"(?:checkout|switch|pull|merge|commit|rebase|reset|cherry-pick)\b"
)


def _is_foreign_beads_worktree(cwd: Path) -> bool:
    """True iff `cwd` is a LINKED git worktree (`.git` is a file, not a dir)
    whose MAIN repo contains a `.beads/` directory but the worktree itself has
    NO `.beads/redirect` — i.e., it was created without `bd worktree create`.

    A bd-created worktree has `.beads/redirect`, so it passes the test at
    `.beads/redirect` and this returns False. A plain-git worktree (main has no
    `.beads/`) also returns False.
    """
    try:
        cwd = cwd.resolve()
    except OSError:
        return False
    git_file = cwd / ".git"
    if not git_file.is_file():
        return False  # not a linked worktree
    # Already bd-created — has the redirect wiring.
    if (cwd / ".beads" / "redirect").is_file():
        return False
    # Parse `gitdir: <path>` from the .git file.
    try:
        content = git_file.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return False
    if not content.startswith("gitdir:"):
        return False
    gitdir_str = content[len("gitdir:"):].strip()
    # The gitdir path points at something like <main>/.git/worktrees/<name>.
    # Walk up to find the main repo's .git/ dir and then check for .beads/.
    gitdir = Path(gitdir_str)
    if not gitdir.is_absolute():
        gitdir = (cwd / gitdir).resolve()
    # Navigate: <main>/.git/worktrees/<name> -> <main>/.git -> <main>
    main_git = gitdir.parent.parent  # .git dir
    main_repo = main_git.parent      # main repo root
    return (main_repo / ".beads").is_dir()


def _resolve_target_cwd(command: str, cwd: Path) -> Path:
    """If the command uses `-C <path>`, resolve that path relative to cwd.
    Returns cwd unchanged if -C is absent or unparseable."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        return cwd
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "-C" and i + 1 < len(tokens):
            p = Path(tokens[i + 1])
            if not p.is_absolute():
                p = cwd / p
            try:
                return p.resolve()
            except OSError:
                return p
        if tok.startswith("-C") and len(tok) > 2:
            p = Path(tok[2:])
            if not p.is_absolute():
                p = cwd / p
            try:
                return p.resolve()
            except OSError:
                return p
        i += 1
    return cwd


def deny_foreign_worktree(cwd: Path) -> NoReturn:
    """Emit the A2 denial for state-changing git in a foreign beads worktree."""
    reason = (
        "This git command targets a linked worktree that was created without "
        "`bd worktree create` — it has a `.beads/` gap (the main repo has `.beads/` "
        "but this worktree has no `.beads/redirect`). Running state-changing git "
        "here will corrupt the beads DB view for this worktree. "
        "Recovery: re-create the worktree with `bd worktree create <path> -b <branch>` "
        "— that sets up `.beads/redirect` so it shares the main repo's database. "
        "(Do NOT run `bd init` inside a worktree — that shadows the real DB.) "
        "# beads-worktree-waiver: <reason> — to proceed despite this warning."
    )
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    sys.exit(0)


def evaluate_worktree_operation(command: str, cwd: Path) -> Optional[str]:
    """A2: check whether `command` is a state-changing git op targeting a foreign
    beads worktree. Returns "deny" if it should be blocked (and emits the denial
    document + exits), or None to allow.

    Exposed at module level so the A2 tripwire test (`hasattr(hook,
    'evaluate_worktree_operation')`) can detect it.
    """
    # Quick pre-check: only bother if the command contains a git subcommand at all.
    if "git" not in command:
        return None
    if not _STATE_CHANGING_GIT_RE.search(command):
        return None  # read-only git or not git at all — allow

    # Determine the effective working directory (may differ if -C is used).
    target_cwd = _resolve_target_cwd(command, cwd)

    if not _is_foreign_beads_worktree(target_cwd):
        return None  # plain-git worktree, bd-created worktree, or non-worktree

    _record_signal(
        gate_name="beads_worktree_guard",
        decision="deny",
        reason="state-changing git in foreign beads worktree",
        tool="Bash",
    )
    deny_foreign_worktree(target_cwd)
    return "deny"  # unreachable but satisfies the return type


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
    if not command:
        return 0

    cwd_raw = data.get("cwd") or data.get("workingDirectory") or os.getcwd()
    cwd = Path(cwd_raw)

    # A1: use re.search so git -C / --git-dir / compound forms are found.
    if _WORKTREE_ADD_RE.search(command):
        if not _in_beads_project(cwd):
            return 0  # plain git repo — worktree add is fine
        _record_signal(
            gate_name="beads_worktree_guard",
            decision="deny",
            reason="git worktree add redirected to bd worktree create",
            tool="Bash",
        )
        deny(command, cwd)
        return 0  # unreachable (deny exits)

    # A2: state-changing git in a foreign beads worktree — deny and redirect.
    evaluate_worktree_operation(command, cwd)  # exits if denying
    return 0


if __name__ == "__main__":
    sys.exit(main())
