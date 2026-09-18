#!/usr/bin/env python3
"""PreToolUse guard for explicit-path edits in a managed primary checkout.

The independent oracle is filesystem shape. A primary checkout has a .git
directory and a sibling .beads directory. A linked worktree has .git as a file,
so explicit edits there remain allowed.

Arbitrary process effects are outside this hook's hard-enforcement boundary.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import NoReturn

sys.path.insert(0, str(Path(__file__).parent))
from _worktree_cli import bundled_cli_prefix

try:
    from _gate_signal import record as _record_signal
except ImportError:  # pragma: no cover
    def _record_signal(*_args, **_kwargs) -> None:
        return None


# Gate-design Rule 1: every gate needs a first-class escape path, documented in
# the denial itself and invokable by the agent without escalating to the user.
# Without one the predicted failure is mock compliance, and that is exactly what
# happened on 2026-09-17: an agent denied Write here judged a worktree
# impossible (it needed a file that was untracked, so a worktree from HEAD would
# not contain it), found no way forward, and wrote the file with a Bash heredoc.
# Arbitrary process effects stay outside this hook's enforcement boundary, so
# the fix is an escape with a recorded reason rather than wider enforcement.
WAIVER_RELATIVE_PATH = Path(".beads") / ".root-checkout-waiver"
WAIVER_MIN_REASON_LENGTH = 20
WAIVER_PLACEHOLDER_REASONS = frozenset(
    {"tbd", "n/a", "na", "todo", "wip", "fixme", "none", "x", "?", "??", "???"}
)

PATH_KEY_BY_TOOL = {
    "Write": "file_path",
    "Edit": "file_path",
    "NotebookEdit": "notebook_path",
    "MultiEdit": "file_path",
}
GATED_EDIT_TOOLS = frozenset(PATH_KEY_BY_TOOL)


def _emit_deny(reason: str) -> NoReturn:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            }
        )
    )
    sys.exit(0)


def _safe_resolve(path: Path) -> Path:
    try:
        return path.resolve(strict=False)
    except OSError:
        return path


def _primary_checkout_root_for(path: Path) -> Path | None:
    """Return the primary beads checkout containing path, if one exists."""
    resolved = _safe_resolve(path)
    start = resolved if resolved.is_dir() else resolved.parent
    for directory in (start, *start.parents):
        git_marker = directory / ".git"
        if git_marker.is_dir():
            return directory if (directory / ".beads").is_dir() else None
        if git_marker.exists():
            return None
    return None


def _path_from_tool_input(tool_name: str, tool_input: dict, cwd: Path) -> Path | None:
    raw = tool_input.get(PATH_KEY_BY_TOOL[tool_name])
    if not isinstance(raw, str) or not raw:
        return None
    path = Path(raw)
    return _safe_resolve(path if path.is_absolute() else cwd / path)


def _quote(value: object) -> str:
    text = str(value)
    if text and all(char.isalnum() or char in "/._-" for char in text):
        return text
    return "'" + text.replace("'", "'\"'\"'") + "'"


def _waiver_reason(root: Path) -> str | None:
    """A substantive, agent-supplied reason for editing the primary checkout.

    Presence is not enough. A gate that accepts any string teaches the shortest
    passing one, which is how a waiver becomes a checkbox and the corpus stops
    being worth reading.
    """
    try:
        raw = (root / WAIVER_RELATIVE_PATH).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    reason = raw.strip()
    if len(reason) < WAIVER_MIN_REASON_LENGTH:
        return None
    if reason.lower() in WAIVER_PLACEHOLDER_REASONS:
        return None
    return reason


def _deny_reason(operation: str, root: Path) -> str:
    prefix = bundled_cli_prefix(Path(__file__))
    if prefix is None:
        repair = (
            "Worktree creation is unavailable: broken Escapement installation; "
            "the bundled escapement-worktree CLI is missing. Repair or reinstall "
            "Escapement before creating a worktree."
        )
    else:
        invocation = (
            " ".join(_quote(token) for token in prefix)
            + f" create --repo {_quote(root)} --name <task> --branch <branch>"
        )
        repair = (
            "Create a linked worktree with the Escapement-owned "
            f"escapement-worktree transaction: `{invocation}`, then make the "
            "change there."
        )
    waiver = (
        "If the change genuinely cannot be made in a worktree -- for example it "
        "depends on a file that is untracked here, so a worktree created from "
        f"HEAD would not contain it -- write `{WAIVER_RELATIVE_PATH}` under "
        f"`{root}` containing a reason of at least {WAIVER_MIN_REASON_LENGTH} "
        "characters saying why, then retry. Writing that file is never blocked, "
        "the reason is recorded as gate signal, and committing the dependency "
        "first is usually the better answer. Do not route around this by "
        "switching to a different tool."
    )
    return (
        f"`{operation}` targets the primary checkout of a beads-managed repo "
        f"at `{root}`. Routine agent implementation work should not dirty the "
        f"root checkout. {repair} {waiver}"
    )


def _deny(operation: str, root: Path, tool_name: str) -> NoReturn:
    _record_signal(
        gate_name="root_checkout_guard",
        decision="deny",
        reason=f"primary checkout explicit edit blocked: {operation}",
        tool=tool_name,
        target=str(root),
    )
    _emit_deny(_deny_reason(operation, root))


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if data.get("hook_event_name") != "PreToolUse":
        return 0
    tool_name = data.get("tool_name", "")
    if tool_name not in GATED_EDIT_TOOLS:
        return 0
    tool_input = data.get("tool_input", {})
    if not isinstance(tool_input, dict):
        return 0
    cwd = _safe_resolve(
        Path(data.get("cwd") or data.get("workingDirectory") or os.getcwd())
    )
    target = _path_from_tool_input(tool_name, tool_input, cwd)
    if target is None:
        return 0
    root = _primary_checkout_root_for(target)
    if root is None:
        return 0
    if _safe_resolve(target) == _safe_resolve(root / WAIVER_RELATIVE_PATH):
        # An escape the gate blocks you from reaching is not an escape.
        return 0
    reason = _waiver_reason(root)
    if reason is not None:
        _record_signal(
            gate_name="root_checkout_guard",
            decision="waiver-accepted",
            reason=reason,
            tool=tool_name,
            target=str(target),
        )
        return 0
    _deny(f"{tool_name} {target}", root, tool_name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
