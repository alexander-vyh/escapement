#!/usr/bin/env python3
"""UserPromptSubmit hook (Claude, Codex, Pi): inject Serena guidance once per
session.

Escapement bundles the Serena MCP server on every host, started with
``--project-from-cwd``, so Serena is live in any code project. This steers the
model toward Serena's symbol tools before it commits to a read-heavy approach,
and nudges onboarding when the project has no Serena memories yet.

Fires at most once per session (keyed on the payload's ``session_id``) — the
injection becomes part of the conversation context, so repeated firing would
just accumulate tokens without adding signal. Silent outside code projects.

Exit codes:
  0 — allow silently, OR emit additionalContext JSON to inject guidance
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _serena_tools import serena_guidance  # noqa: E402


# Same project-root signals serena_preference_gate.py uses.
_PROJECT_SIGNALS = (".git", "pyproject.toml", "package.json", "Gemfile",
                    "Cargo.toml", "go.mod", ".serena/project.yml")
_SAFE_SESSION_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")


# ---------------------------------------------------------------------------
# Project / session discovery
# ---------------------------------------------------------------------------

def _session_flag_path(session_id: str) -> Path:
    if not _SAFE_SESSION_ID.fullmatch(session_id):
        session_id = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return Path(tempfile.gettempdir()) / f"serena_injection_{session_id}.flag"


def _project_root(start: Path) -> Path | None:
    """The nearest ancestor of ``start`` that looks like a code project."""
    current = start.resolve() if start.exists() else start
    for directory in (current, *current.parents):
        if any((directory / sig).exists() for sig in _PROJECT_SIGNALS):
            return directory
    return None


def _has_serena_memories(root: Path) -> bool:
    memories = root / ".serena" / "memories"
    try:
        return memories.is_dir() and any(memories.iterdir())
    except OSError:
        return False


# ---------------------------------------------------------------------------
# Injection content
# ---------------------------------------------------------------------------

def _guidance(onboarded: bool) -> str:
    parts = [
        "Serena (LSP-backed semantic code tooling) is available in this project.",
        serena_guidance(),
        "Serena memories are project knowledge: list_memories / read_memory for "
        "what is relevant; write_memory for non-obvious facts you discover.\n"
        "Read non-code files, small files, or explicit line ranges directly; use "
        "text search for literal strings, error messages and config keys. When "
        "dispatching subagents that will touch code, tell them to use Serena too.",
    ]
    if onboarded:
        parts.append(
            "Full-file reads of large source files are blocked here by the "
            "serena_preference_gate hook."
        )
    else:
        parts.append(
            "Serena is not onboarded for this project yet (no .serena/memories): "
            "run Serena's onboarding tool early."
        )
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    if not isinstance(data, dict):
        return 0

    hook_event = data.get("hook_event_name", "") or data.get("hookEventName", "")
    if hook_event != "UserPromptSubmit":
        return 0

    cwd_raw = data.get("cwd") or data.get("workingDirectory") or os.getcwd()
    root = _project_root(Path(cwd_raw))
    if root is None:
        return 0

    session_id = data.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        session_id = os.environ.get("CLAUDE_SESSION_ID") or str(os.getppid())
    flag = _session_flag_path(session_id)
    if flag.exists():
        # Already injected in this session — guidance is in context.
        return 0
    try:
        flag.touch()
    except OSError:
        pass

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": _guidance(_has_serena_memories(root)),
        }
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
