"""Reading Codex's `apply_patch` PreToolUse payload.

Codex writes files through `apply_patch`, not Write/Edit, so any gate that
matches on Write/Edit is silently inert there. Every such gate needs the same
two answers — which file, and how much longer does it get — and the format is
Codex's, not ours, so it gets one owner here rather than a copy per gate.

The payload shape is CAPTURED, not assumed. See
`tests/fixtures/codex_apply_patch_pretooluse.json` for provenance: the patch
text arrives as ``tool_input["command"]`` and paths inside it are relative to
``cwd``. An earlier gate in this repo guessed ``tool_input["input"]`` and would
have been dead on arrival with its own tests passing.

Everything here fails open — an unreadable payload returns None, never an
exception into a live session.
"""

from __future__ import annotations

import os
import re

PATCH_TARGET = re.compile(r"^\*\*\* (Add|Update|Delete) File: (.+?)\s*$")
MOVE_TARGET = re.compile(r"^\*\*\* Move to: (.+?)\s*$")
# A patch that names an environment is applied in THAT environment's working
# directory (codex-rs apply-patch parser: `*** Environment ID: <id>`), which the
# hook payload does not carry -- its `cwd` is the primary environment's.
ENVIRONMENT_DIRECTIVE = re.compile(r"^\*\*\* Environment ID:")


def targets(command: str, cwd: str) -> list[tuple[str, str]] | None:
    """Every file a patch changes, in patch order: ``[(kind, abs_path), ...]``.

    ``kind`` is ``Add``, ``Update`` or ``Delete`` for a file header, and ``Move``
    for the destination of an ``Update`` that renames. A gate that asks "may
    this file be written" must see all of them: a patch touching a harmless
    file first and a gated one second is the same write as two Claude edits.

    Relative paths resolve against ``cwd``, which Codex sets to the turn's
    working directory -- the same directory its apply_patch handler resolves
    them against (captured: tests/fixtures/codex_apply_patch_pretooluse.json).

    Returns None -- fail open -- when there is no parseable target, when a
    relative target has no ``cwd`` to resolve against, or when the patch names
    another environment whose directory the payload does not carry.
    """
    if not command or "*** " not in command:
        return None
    found: list[tuple[str, str]] = []
    for line in command.splitlines():
        if ENVIRONMENT_DIRECTIVE.match(line):
            return None
        header = PATCH_TARGET.match(line)
        move = None if header else MOVE_TARGET.match(line)
        if header:
            kind, raw = header.group(1), header.group(2).strip()
        elif move:
            kind, raw = "Move", move.group(1).strip()
        else:
            continue
        if not raw:
            continue
        if not os.path.isabs(raw):
            if not cwd:
                return None
            raw = os.path.join(cwd, raw)
        found.append((kind, os.path.normpath(raw)))
    return found or None


def payload_targets(tool_input: object, cwd: str) -> list[tuple[str, str]] | None:
    """``targets`` of an apply_patch ``tool_input``, which carries the patch
    text as ``command`` (captured, not ``input``). None when it does not."""
    if not isinstance(tool_input, dict):
        return None
    patch = tool_input.get("command")
    return targets(patch, cwd) if isinstance(patch, str) else None


def first_target(command: str, cwd: str) -> tuple[str, str, int, int] | None:
    """The first file a patch touches: ``(kind, abs_path, added, removed)``.

    Only the first, because a gate reports on one file, and a patch touching
    several is better judged per-file on the next edit than by a summed number
    that matches nothing on disk.

    Returns None when there is no parseable target, so callers fail open.
    """
    if not command or "*** " not in command:
        return None
    added = removed = 0
    target: str | None = None
    kind = ""
    for line in command.splitlines():
        match = PATCH_TARGET.match(line)
        if match:
            if target is not None:
                break  # second target — report only the first
            kind, target = match.group(1), match.group(2).strip()
            continue
        if target is None:
            continue
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    if not target:
        return None
    path = target if os.path.isabs(target) else os.path.join(cwd or "", target)
    return kind, path, added, removed
