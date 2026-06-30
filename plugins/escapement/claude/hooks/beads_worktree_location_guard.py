#!/usr/bin/env python3
"""Location guard for `bd worktree create` targets.

`bd worktree create` fixes the beads database wiring, but an in-repo worktree
at a visible path is still a problem: source indexers treat it as more project
source. This helper denies non-ignored in-repo targets and allows ignored or
outside-repo targets.
"""

from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Callable, NoReturn, Optional


SignalRecorder = Callable[..., None]

_SHELL_SEP_RE = re.compile(r"&&|\|\||[;|\n]")
_ENVVAR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_WAIVER_RE = re.compile(r"#\s*beads-worktree-waiver:\s*(\S.*?)\s*$", re.MULTILINE)
_WAIVER_PLACEHOLDERS = frozenset({"<reason>", "tbd", "n/a", "na", "none", "todo", "fixme"})


def _has_substantive_waiver(command: str) -> bool:
    match = _WAIVER_RE.search(command)
    if not match:
        return False
    reason = match.group(1).strip()
    return len(reason) >= 8 and reason.lower() not in _WAIVER_PLACEHOLDERS


def _bd_worktree_create_args(tokens: list[str]) -> Optional[list[str]]:
    """Return tokens after `bd worktree create`, or None for other commands."""
    i = 0
    n = len(tokens)
    while i < n and _ENVVAR_RE.match(tokens[i]):
        i += 1
    while i < n and tokens[i] in ("env", "command"):
        i += 1
        while i < n and (_ENVVAR_RE.match(tokens[i]) or tokens[i].startswith("-")):
            i += 2 if tokens[i] in ("-u", "-S") and i + 1 < n else 1
    if i >= n or tokens[i].split("/")[-1] != "bd":
        return None
    i += 1
    while i < n and tokens[i].startswith("-"):
        i += 2 if tokens[i] == "--db" and i + 1 < n else 1
    if i + 1 < n and tokens[i] == "worktree" and tokens[i + 1] == "create":
        return tokens[i + 2:]
    return None


def _bd_path_and_branch(args: list[str]) -> tuple[Optional[str], Optional[str]]:
    path: Optional[str] = None
    branch: Optional[str] = None
    i = 0
    while i < len(args):
        tok = args[i]
        if tok in ("-b", "-B", "--branch"):
            if i + 1 < len(args):
                branch = args[i + 1]
            i += 2
            continue
        if tok.startswith("-"):
            i += 1
            continue
        if path is None:
            path = tok
        i += 1
    return path, branch


def _git(args: list[str], cwd: Path) -> tuple[int, str]:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode, result.stdout.strip()
    except Exception:
        return 255, ""


def _worktree_target_is_safe(path_str: Optional[str], cwd: Path) -> bool:
    """Allow only outside-repo targets or in-repo targets ignored by git."""
    if not path_str:
        return True
    rc, root_str = _git(["rev-parse", "--show-toplevel"], cwd)
    if rc != 0 or not root_str:
        return True
    target = Path(path_str)
    if not target.is_absolute():
        target = cwd / target
    try:
        root = Path(root_str).resolve()
        rel = target.resolve().relative_to(root)
    except (OSError, ValueError):
        return True
    rc, _ = _git(["check-ignore", "-q", str(rel)], root)
    if rc == 0:
        return True
    if rc == 1:
        return False
    return True


def _location_suggestion(path_str: Optional[str], branch: Optional[str]) -> str:
    name = Path(path_str).name if path_str else "<name>"
    cmd = f"bd worktree create .worktrees/{name}"
    cmd += f" -b {branch}" if branch else " -b <branch>"
    return cmd


def deny_worktree_location(path_str: Optional[str], branch: Optional[str]) -> NoReturn:
    attempted = f"bd worktree create {path_str or '<path>'}"
    suggestion = _location_suggestion(path_str, branch)
    reason = (
        f"`{attempted}` would place the worktree inside the repo at a path that "
        "is not ignored by git. Non-ignored in-repo worktrees get indexed by "
        "tools like Serena and can bloat their cache. Put beads worktrees under "
        "a gitignored in-repo directory or outside the repo. "
        f"For the same slug, an ignored in-repo target would be `{suggestion}`; "
        "choosing another ignored or outside-repo path is also fine. "
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


def evaluate_bd_worktree_location(
    command: str,
    cwd: Path,
    record_signal: SignalRecorder,
) -> Optional[str]:
    """Deny `bd worktree create` into a non-ignored in-repo path."""
    if "worktree" not in command or "create" not in command:
        return None
    for segment in _SHELL_SEP_RE.split(command):
        segment = segment.strip()
        if not segment:
            continue
        try:
            tokens = shlex.split(segment)
        except ValueError:
            continue
        args = _bd_worktree_create_args(tokens)
        if args is None:
            continue
        path_str, branch = _bd_path_and_branch(args)
        if _worktree_target_is_safe(path_str, cwd):
            continue
        if _has_substantive_waiver(command):
            record_signal(
                gate_name="beads_worktree_guard",
                decision="waiver",
                reason="bd worktree create location waiver",
                tool="Bash",
            )
            continue
        record_signal(
            gate_name="beads_worktree_guard",
            decision="deny",
            reason="bd worktree create into non-ignored in-repo path",
            tool="Bash",
        )
        deny_worktree_location(path_str, branch)
    return None
