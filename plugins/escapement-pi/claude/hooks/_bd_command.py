#!/usr/bin/env python3
"""One owner for reading a `bd` invocation out of a shell command string.

A gate that decides with `"bd close" in command` fires on prose, not on work.
Observed false positives, all from one session: a `bd note` whose note text
explained the close gate, a `grep` whose pattern contained the phrase, and
`bd close --help`. None of them closed a bead. Each cost a real interruption,
and a gate that interrupts for nothing is one the reader learns to dismiss --
the habituation failure `claude/rules/delicate-art-of-bureaucracy.md` names.

So matching is token-position aware: the phrase has to appear as `bd` followed
by the subcommand in argv position, in some segment of the command, outside
quotes. `shlex` supplies the quoting rules rather than a second regex guess.

The bead-id reader is deliberately conservative about flag values. Missing an
id means a caller resolves no design and stays silent; inventing one means a
caller looks up something that does not exist, which also resolves nothing.
Both directions fail safe, so a value-taking flag is skipped by name rather
than by guessing whether its value looks like an id.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

# `;` `&` `|` `&&` `||` and newlines separate one invocation from the next.
_SHELL_SEP_RE = re.compile(r"\|\||&&|[;|&\n]")

# Wrappers that may precede the real argv0 without changing what is being run.
_TRANSPARENT_WRAPPERS = ("env", "command", "nohup", "time", "timeout", "stdbuf")

# A bead id: prefix, dash, slug, with optional dotted child suffixes. The slug
# is one-or-more characters because a tracker is free to issue `x-1`; requiring
# two silently dropped short ids, and a dropped id means the caller resolves no
# design and says nothing.
BEAD_ID_RE = re.compile(r"\A[a-z][a-z0-9]*-[a-z0-9]+(?:\.[0-9]+)*\Z")

# Flags whose next token is a value, not a bead id. Any `--flag=value` form is
# handled generically, so only the space-separated spellings need naming.
_VALUE_FLAGS = frozenset({
    "--reason",
    "--close-reason",
    "--note",
    "--notes",
    "--comment",
    "--message",
    "-m",
    "--assignee",
    "--owner",
    "--repo",
    "--db",
    "--spec-id",
    "--format",
})


def _segments(command: str) -> list[str]:
    return _SHELL_SEP_RE.split(command)


def invocations(command: str, subcommand: str) -> list[list[str]]:
    """Return the argv tail after `bd <subcommand>` for every real invocation.

    A segment counts only when `bd` (or a path ending in `bd`) sits in argv0
    position, after any leading `VAR=value` assignments and transparent
    wrappers, and `subcommand` is the token right after it.
    """
    found: list[list[str]] = []
    for segment in _segments(command):
        try:
            # comments=True so a trailing `# ...waiver: ...` note contributes no
            # argv tokens: its words would otherwise read as positional ids.
            tokens = shlex.split(segment, comments=True)
        except ValueError:
            # Unbalanced quotes: this segment is not a command we can read.
            continue
        index = 0
        while index < len(tokens) and "=" in tokens[index] and not tokens[index].startswith("-"):
            index += 1
        while index < len(tokens) and tokens[index] in _TRANSPARENT_WRAPPERS:
            index += 1
        if index + 1 >= len(tokens):
            continue
        if Path(tokens[index]).name != "bd":
            continue
        if tokens[index + 1] != subcommand:
            continue
        found.append(tokens[index + 2:])
    return found


def invokes(command: str, subcommand: str) -> bool:
    """Whether the command actually runs `bd <subcommand>` somewhere."""
    return bool(invocations(command, subcommand))


def bead_ids(argv: list[str]) -> list[str]:
    """Return the positional bead ids in one argv tail, in order, deduplicated."""
    ids: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--":
            index += 1
            continue
        if token.startswith("-"):
            if "=" not in token and token in _VALUE_FLAGS:
                index += 2
            else:
                index += 1
            continue
        if BEAD_ID_RE.match(token) and token not in ids:
            ids.append(token)
        index += 1
    return ids


def subcommand_bead_ids(command: str, subcommand: str) -> list[str]:
    """Bead ids passed to `bd <subcommand>` across every invocation in `command`."""
    ids: list[str] = []
    for argv in invocations(command, subcommand):
        for bead in bead_ids(argv):
            if bead not in ids:
                ids.append(bead)
    return ids
