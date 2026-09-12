#!/usr/bin/env python3
"""Did this session change code? Derived from its own transcript (escapement-pip5).

The continuation harness requires a declared outcome from a session that changed
code, and requires nothing from one that did not. That requirement must be
DERIVED, never asserted: `would_block_stop.py` states the law for its own gate —
"A DERIVED signal (gate-design Rule 3 / derive-not-assert) — never
agent-asserted." A self-declared exemption was tried and measured: verified stops
fell from 20.5% of real decisions in May 2026 to 0% in August.

Why the transcript and not git
------------------------------
`git status` sees the whole working tree, and many concurrent sessions share one
checkout, so a peer's in-flight edits would implicate this session. The transcript
IS the session, so a scan over it is session-local by construction. The Stop hook
already reads this file, so this adds no new hook, no new state file, and no
write-path race.

What counts as changing code
----------------------------
A write is only interesting if it can reach someone outside this repository:
inside a git work tree, not gitignored, not under a scratchpad. A throwaway script
in /tmp ships nothing, so there is no outcome to check it against, and demanding
an oracle for one would just train agents to declare a fake contract to clear a
gate a temp file tripped.

Coverage is deliberately two-layer, and the second layer is PARTIAL — see
`bash_write_targets`.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import shlex
import subprocess
from typing import Iterable

# Tools whose input names a file they write. Exact and complete — these carry an
# explicit path, so there is no guessing.
_EDIT_TOOLS = frozenset({"Write", "Edit", "MultiEdit", "NotebookEdit"})
_PATH_KEYS = ("file_path", "notebook_path", "path")

# Bash constructs that write a file. Necessary because the host's auto mode
# instructs agents to "make file changes with sed, heredocs, or short scripts,
# rather than using the dedicated Read, Edit, or Write tools" — a detector that
# watched only the edit tools would be blind exactly in unattended sessions.
_REDIRECT_RE = re.compile(r"(?<!\d)>>?\s*([^\s;|&<>()]+)")
_SED_INPLACE_RE = re.compile(r"\bsed\b[^;|&]*?\s-i\b(?:\s+(?:''|\"\"|\S+))?\s+([^\s;|&]+)")
_TEE_RE = re.compile(r"\btee\b(?:\s+-\w+)*\s+([^\s;|&<>]+)")
# Whole-command write verbs whose target is the LAST bare argument.
_COPY_MOVE_RE = re.compile(r"\b(?:cp|mv|install|rsync)\b\s+(.+)")
# Commands that rewrite tracked files wholesale. Their targets are hard to parse,
# so presence alone is treated as a repo write when run inside a work tree.
_WHOLESALE_RE = re.compile(
    r"\b(?:patch|git\s+apply|git\s+restore|git\s+checkout\s+--|git\s+revert|git\s+stash\s+pop)\b"
)

# Heredoc openers: `<<EOF`, `<<'EOF'`, `<<"EOF"`, `<<-EOF`.
_HEREDOC_OPEN_RE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
# A heredoc fed to a shell IS shell, so that body must still be scanned. Written
# to require a command position so `ssh` and `pushd` do not read as shells.
_SHELL_CMD_RE = re.compile(
    r"(?:^|[\s|;&(])(?:[\w./-]*/)?(?:sh|bash|zsh|ksh|dash|ash)(?=\s|$)"
)

_SCRATCH_PARTS = frozenset({"scratchpad", ".worktrees-scratch"})


def _rows(transcript_path: "str | os.PathLike | None") -> Iterable[dict]:
    if not transcript_path:
        return []
    path = pathlib.Path(transcript_path)
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        # Fail OPEN on missing evidence: no transcript must never manufacture a
        # block. The gate may only block on positive proof that code changed.
        return []
    out = []
    for line in raw.splitlines():
        # Cheap prefilter — most transcript rows are not tool calls, and this runs
        # on every Stop.
        if '"tool_use"' not in line:
            continue
        try:
            row = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(row, dict):
            out.append(row)
    return out


def _tool_uses(rows: Iterable[dict]) -> Iterable[tuple[str, dict]]:
    for row in rows:
        message = row.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            name = block.get("name")
            payload = block.get("input")
            if isinstance(name, str) and isinstance(payload, dict):
                yield name, payload


def _strip_heredoc_bodies(command: str) -> str:
    """Drop heredoc body lines, keeping the opening line that carries the redirect.

    A heredoc writes a file only through a redirect on its OPENING line
    (`cat > f <<EOF`), which sits outside the body. The body is data for some
    other interpreter -- routinely Python, jq or awk, which host auto mode
    actively steers agents toward -- where `>` is a comparison operator. Scanning
    it as shell invents write targets for files that never exist: `len(v) > 2000:`
    reads as a redirect to a file named `2000:`.

    That phantom is not a harmless over-count. It blocks a session that changed
    nothing, and the pressure it creates is the one this module's docstring
    already refuses elsewhere -- it "would just train agents to declare a fake
    contract to clear a gate".

    Exception, kept deliberately: a body piped to a shell IS shell, so it stays.
    """
    lines = command.split("\n")
    kept: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        kept.append(line)
        index += 1
        opener = _HEREDOC_OPEN_RE.search(line)
        if not opener:
            continue
        delimiter = opener.group(2)
        shell_body = bool(_SHELL_CMD_RE.search(line))
        while index < len(lines) and lines[index].strip() != delimiter:
            if shell_body:
                kept.append(lines[index])
            index += 1
        if index < len(lines):  # the delimiter line itself
            kept.append(lines[index])
            index += 1
    return "\n".join(kept)


def bash_write_targets(command: str) -> list[str]:
    """Paths a Bash command appears to write, plus a sentinel for wholesale rewrites.

    KNOWN LIMIT, named rather than hidden (the repo's capability-honesty rule):
    this is pattern recognition over shell text, not a shell. It catches the
    constructs agents actually use — redirects, heredocs, `sed -i`, `tee`,
    copy/move, patch/git-apply — and will miss a sufficiently indirect write (a
    path built at runtime, a script that writes on the agent's behalf). It is a
    high-recall heuristic layered under the exact edit-tool detection, NOT an
    airtight oracle, and must not be described as one.

    Second named limit: heredoc BODIES are not scanned unless the heredoc is fed
    to a shell (see `_strip_heredoc_bodies`). A redirect written inside a body
    that some non-shell interpreter then executes on the agent's behalf is missed.
    That is the deliberate price of not misreading every `>` in heredoc'd Python,
    jq and awk as a write, which is the far commoner case.

    Returns "." for a wholesale rewrite, meaning "something in the tree changed".
    """
    if not isinstance(command, str) or not command.strip():
        return []
    command = _strip_heredoc_bodies(command)
    targets: list[str] = []

    for match in _SED_INPLACE_RE.finditer(command):
        targets.append(match.group(1))
    for match in _TEE_RE.finditer(command):
        targets.append(match.group(1))
    for match in _REDIRECT_RE.finditer(command):
        candidate = match.group(1)
        # `2>&1` and friends are not files.
        if candidate.startswith("&"):
            continue
        targets.append(candidate)
    for match in _COPY_MOVE_RE.finditer(command):
        try:
            words = shlex.split(match.group(1))
        except ValueError:
            continue
        bare = [w for w in words if not w.startswith("-")]
        if len(bare) >= 2:
            targets.append(bare[-1])
    if _WHOLESALE_RE.search(command):
        targets.append(".")

    cleaned = []
    for target in targets:
        target = target.strip().strip("'\"")
        if target and not target.startswith("$"):
            cleaned.append(target)
    return cleaned


def written_paths(transcript_path: "str | os.PathLike | None") -> list[str]:
    """Every path this session appears to have written, in transcript order."""
    paths: list[str] = []
    for name, payload in _tool_uses(_rows(transcript_path)):
        if name in _EDIT_TOOLS:
            for key in _PATH_KEYS:
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    paths.append(value.strip())
                    break
        elif name == "Bash":
            command = payload.get("command")
            if isinstance(command, str):
                paths.extend(bash_write_targets(command))
    return paths


def _run_git(args: list[str], cwd: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=10,
    )


def is_code_path(path: str, *, cwd: str) -> bool:
    """Whether writing `path` is a change that could reach someone outside the repo.

    True iff it resolves inside a git work tree, is not gitignored, and is not
    under a scratchpad directory.
    """
    if not path:
        return False
    candidate = pathlib.Path(path)
    if not candidate.is_absolute():
        candidate = pathlib.Path(cwd) / candidate
    try:
        resolved = candidate.resolve()
    except (OSError, RuntimeError):
        return False

    if _SCRATCH_PARTS & set(resolved.parts):
        return False

    # The directory is what we ask git about — the file itself may not exist yet.
    probe_dir = resolved.parent
    while not probe_dir.exists() and probe_dir != probe_dir.parent:
        probe_dir = probe_dir.parent
    if not probe_dir.exists():
        return False

    try:
        inside = _run_git(["rev-parse", "--is-inside-work-tree"], str(probe_dir))
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            return False
        ignored = _run_git(["check-ignore", "-q", str(resolved)], str(probe_dir))
        # exit 0 = the path IS ignored.
        if ignored.returncode == 0:
            return False
    except (OSError, subprocess.SubprocessError):
        # Fail OPEN: an unavailable git must not manufacture a block.
        return False
    return True


def touched_code(transcript_path: "str | os.PathLike | None", cwd: str) -> bool:
    """Whether this session changed code that can reach someone outside the repo."""
    if not cwd:
        return False
    for path in written_paths(transcript_path):
        if is_code_path(path, cwd=cwd):
            return True
    return False
