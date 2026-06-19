#!/usr/bin/env python3
"""Claude Code hook: inject Serena-preference guidance at turn start.

Fires on UserPromptSubmit. In projects where Serena has been onboarded
(.serena/memories directory is populated), injects a short planning prompt
that steers the model toward Serena's symbol tools for code navigation before
it commits to an inline Read/Grep-heavy approach.

Fires at most once per session — the injection becomes part of the conversation
context, so repeated firing would just accumulate tokens without adding signal.

Silent in projects without Serena onboarding.

Exit codes:
  0 — allow silently, OR emit additionalContext JSON to inject guidance
"""

import json
import os
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Project / session discovery
# ---------------------------------------------------------------------------

def _session_flag_path() -> Path:
    session_id = os.environ.get("CLAUDE_SESSION_ID") or str(os.getppid())
    return Path(f"/tmp/serena_injection_{session_id}.flag")


def _has_serena_memories(start: Path) -> bool:
    """Walk up from ``start`` looking for .serena/memories inside a project.

    Uses the same project-root signals as serena_onboarding_check.sh. Returns
    True if the directory exists and contains at least one file.
    """
    project_signals = (".git", "pyproject.toml", "package.json", "Gemfile",
                       "Cargo.toml", "go.mod")
    current = start.resolve() if start.exists() else start
    for directory in (current, *current.parents):
        if any((directory / sig).exists() for sig in project_signals):
            memories = directory / ".serena" / "memories"
            if memories.is_dir():
                try:
                    return any(memories.iterdir())
                except OSError:
                    return False
            return False
        if directory == directory.parent:
            break
    return False


# ---------------------------------------------------------------------------
# Injection content
# ---------------------------------------------------------------------------

_GUIDANCE = (
    "Serena (LSP-backed semantic code tooling) is active for this project.\n\n"
    "For **source code** navigation, prefer Serena's symbol tools over Read:\n"
    "  - mcp__serena__get_symbols_overview(relative_path) — structure of a file\n"
    "  - mcp__serena__find_symbol(name_path, relative_path) — fetch a class/method body\n"
    "  - mcp__serena__find_referencing_symbols(name_path) — find callers of a symbol\n"
    "  - mcp__serena__search_for_pattern(substring_pattern) — project-scoped pattern search\n\n"
    "Use **Read** for: non-code files (markdown, YAML, JSON, logs, config), small "
    "files, or targeted byte ranges (pass explicit offset+limit).\n\n"
    "Use **Grep** for: literal strings, error messages, config keys — Serena is "
    "semantic, Grep is textual.\n\n"
    "Use **Glob** for: filename/path patterns.\n\n"
    "Full-file Read on source code in this project is blocked by the "
    "serena_preference_gate hook. If an investigation is large, dispatch an "
    "explorer agent with a batch objective rather than reading inline."
)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    hook_event = data.get("hook_event_name", "") or data.get("hookEventName", "")
    if hook_event != "UserPromptSubmit":
        return 0

    cwd_raw = data.get("cwd") or data.get("workingDirectory") or os.getcwd()
    cwd = Path(cwd_raw)

    if not _has_serena_memories(cwd):
        return 0

    flag = _session_flag_path()
    if flag.exists():
        # Already injected in this session — guidance is in context, no need to re-emit.
        return 0

    try:
        flag.touch()
    except OSError:
        pass

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": _GUIDANCE,
        }
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
