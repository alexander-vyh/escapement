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

# Characters that make up shell control operators (`;` `&` `|` `&&` `||`,
# newlines, subshell parens) and redirections (`<` `>`). The lexer groups a run
# of them into one token, so `&&\n` or `;(` arrive as a single separator.
_PUNCTUATION = ";&|()<>\n"
_SEPARATOR_CHARS = frozenset(";&|()\n")

# A heredoc opener: `<<WORD`, `<<-WORD`, `<<'WORD'`, `<<"WORD"`, but not the
# here-string `<<<`. Its body is data, never commands.
_HEREDOC_RE = re.compile(r"(?<!<)<<(?!<)(-?)[ \t]*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\2")

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
    "-r",
    "--reason-file",
    "--session",
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


def _strip_heredoc_bodies(command: str) -> str:
    """Drop every heredoc body (and its terminator line), keeping the opener."""
    kept: list[str] = []
    pending: list[tuple[bool, str]] = []
    for line in command.split("\n"):
        if pending:
            strip_tabs, word = pending[0]
            if (line.lstrip("\t") if strip_tabs else line) == word:
                pending.pop(0)
            continue
        kept.append(line)
        pending.extend((m.group(1) == "-", m.group(3)) for m in _HEREDOC_RE.finditer(line))
    return "\n".join(kept)


def _strip_comments(command: str) -> str:
    """Drop shell comments, deciding with the quotes still present.

    A `#` starts a comment only outside quotes and at the start of a word, as in
    the shell. Deciding after shlex has removed the quotes would read
    `git commit -m "#1 fix"; bd close a1` as a comment that hides the close.
    """
    kept: list[str] = []
    quote = ""
    index = 0
    while index < len(command):
        char = command[index]
        if quote:
            if char == "\\" and quote == '"' and index + 1 < len(command):
                kept.append(command[index:index + 2])
                index += 2
                continue
            if char == quote:
                quote = ""
        elif char == "\\" and index + 1 < len(command):
            kept.append(command[index:index + 2])
            index += 2
            continue
        elif char in "'\"":
            quote = char
        elif char == "#" and (index == 0 or command[index - 1] in " \t\n;&|()"):
            end = command.find("\n", index)
            index = len(command) if end < 0 else end
            continue
        kept.append(char)
        index += 1
    return "".join(kept)


def _segments(command: str) -> list[list[str]]:
    """Argv of every simple command, quote- and heredoc-aware.

    The WHOLE command is tokenized first, so a control operator inside quotes
    (`git commit -m "fix && bd close x"`) is part of a word, never a separator,
    and a heredoc body is never read as commands. Redirections and their
    targets are dropped, and comments are removed before tokenizing. Unbalanced
    quotes mean the command cannot be read: no segments.
    """
    source = _strip_comments(_strip_heredoc_bodies(command))
    lexer = shlex.shlex(source, posix=True, punctuation_chars=_PUNCTUATION)
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        tokens = list(lexer)
    except ValueError:
        return []
    segments: list[list[str]] = [[]]
    skip_target = False
    for token in tokens:
        is_punctuation = bool(token) and all(ch in _PUNCTUATION for ch in token)
        if is_punctuation and set(token) <= _SEPARATOR_CHARS:
            segments.append([])
            skip_target = False
            continue
        if is_punctuation:  # a redirection: drop it and its target
            skip_target = True
            continue
        if skip_target:
            skip_target = False
            continue
        segments[-1].append(token)
    return [segment for segment in segments if segment]


def program_invocations(command: str, program: str, *path: str) -> list[list[str]]:
    """Return the argv tail after `<program> <path...>` for every real invocation.

    A segment counts only when `program` (or a path ending in it) sits in argv0
    position, after any leading `VAR=value` assignments and transparent
    wrappers, and `path` are the tokens right after it.
    """
    found: list[list[str]] = []
    for tokens in _segments(command):
        index = 0
        while index < len(tokens) and "=" in tokens[index] and not tokens[index].startswith("-"):
            index += 1
        while index < len(tokens) and tokens[index] in _TRANSPARENT_WRAPPERS:
            index += 1
        end = index + 1 + len(path)
        if end > len(tokens) or Path(tokens[index]).name != program:
            continue
        if tuple(tokens[index + 1:end]) != path:
            continue
        found.append(tokens[end:])
    return found


def invocations(command: str, subcommand: str) -> list[list[str]]:
    """Return the argv tail after `bd <subcommand>` for every real invocation."""
    return program_invocations(command, "bd", subcommand)


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


# PR-merge flags whose next token is a value, not the PR selector.
_GH_MERGE_VALUE_FLAGS = frozenset({
    "-R", "--repo", "-b", "--body", "-F", "--body-file", "-t", "--subject",
    "-A", "--author-email", "--match-head-commit",
})


def pr_merges(command: str) -> list[tuple[str | None, str | None]]:
    """(selector, repo) for every real `gh pr merge`, read by the same parser.

    The selector is the first positional argument (number, URL or branch), or
    None for gh's "the current branch's PR"; repo is `-R`/`--repo`'s value.
    """
    merges: list[tuple[str | None, str | None]] = []
    for argv in program_invocations(command, "gh", "pr", "merge"):
        selector = repo = None
        index = 0
        while index < len(argv):
            token = argv[index]
            flag, _, inline = token.partition("=")
            if flag in ("-R", "--repo"):
                repo = inline if inline else (argv[index + 1] if index + 1 < len(argv) else None)
            if token.startswith("-"):
                index += 2 if not inline and flag in _GH_MERGE_VALUE_FLAGS else 1
                continue
            selector = selector or token
            index += 1
        merges.append((selector, repo))
    return merges
