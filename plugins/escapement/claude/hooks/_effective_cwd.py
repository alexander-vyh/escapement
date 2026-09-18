#!/usr/bin/env python3
"""One owner for "which directory is this command actually about".

Hooks receive a `cwd` in their payload and treat it as the repository the
command touches. For a session that stays in one checkout that is true. It is
not true for the two shapes agents use constantly:

* a host that lets a call name its own working directory (Pi's Bash tool takes
  `cwd`), where the payload still carried the *session's* directory;
* `cd /other/repo && git push`, where the payload directory is whatever the
  session started in.

Both were observed on 2026-09-18: pushing a branch in one repository was
interrogated about uncommitted test edits in a different repository, by a gate
whose finding was correct about a tree the command never touched. A gate that
reasons about the wrong repository is not a stricter gate, it is a wrong one,
and every false finding it produces teaches the reader to dismiss the true ones.

Resolution is deliberately narrow. Only a `cd` in *leading* position is read,
because that is the form whose effect on the rest of the command is
unambiguous. `make && cd build && ./x` is left alone rather than guessed at.
A target that does not resolve to an existing directory is ignored, so a typo
or a variable this module cannot expand leaves the payload as it was.
"""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path

# `;` `&` `|` `&&` `||` and newlines separate one invocation from the next.
_SHELL_SEP_RE = re.compile(r"\|\||&&|[;|&\n]")


def _existing_directory(candidate: str, base: str | None) -> str | None:
    if not candidate:
        return None
    expanded = os.path.expanduser(candidate)
    path = Path(expanded)
    if not path.is_absolute() and base:
        path = Path(base) / path
    try:
        resolved = path.resolve()
    except OSError:
        return None
    return str(resolved) if resolved.is_dir() else None


def leading_cd_target(command: str, base: str | None) -> str | None:
    """The directory a leading `cd <dir>` moves the rest of the command into."""
    segments = _SHELL_SEP_RE.split(command)
    if not segments:
        return None
    try:
        tokens = shlex.split(segments[0], comments=True)
    except ValueError:
        return None
    if len(tokens) != 2 or tokens[0] != "cd":
        # Bare `cd` (home) and `cd dir extra` are not the unambiguous form.
        return None
    return _existing_directory(tokens[1], base)


def resolve(payload: dict) -> str | None:
    """Return the directory this payload's command runs in, or None to keep.

    Precedence: the call's own declared directory, then a leading `cd`, then
    nothing — the payload's existing `cwd` stands.
    """
    if not isinstance(payload, dict):
        return None
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    base = payload.get("cwd") if isinstance(payload.get("cwd"), str) else None

    declared = tool_input.get("cwd")
    if isinstance(declared, str):
        resolved = _existing_directory(declared, base)
        if resolved:
            return resolved

    command = tool_input.get("command")
    if isinstance(command, str) and command:
        return leading_cd_target(command, base)
    return None


def normalized(payload: dict) -> dict:
    """The payload with `cwd` set to the command's effective directory."""
    target = resolve(payload)
    if not target or target == payload.get("cwd"):
        return payload
    updated = dict(payload)
    updated["cwd"] = target
    return updated
