#!/usr/bin/env python3
"""Claude Code hook: block full-file Read on source-code files when Serena is
available for the project.

Fires as PreToolUse on Read and on Bash (to catch cat/head/tail/less bypasses).

Rationale: reading an entire source file top-to-bottom burns main-context tokens
when Serena's LSP-backed tools (get_symbols_overview, find_symbol,
find_referencing_symbols) can answer the same questions with a fraction of the
tokens. Only fires when .serena/memories is present in the project tree — silent
in projects where Serena is not onboarded.

Exemptions (all allow silently):
  - Subagents (detected via env vars) — they do their own exploration
  - Read with offset/limit — targeted read is fine
  - Non-source files (markdown, YAML, JSON, config, logs, shell) — not Serena's
    domain
  - Files under the size threshold — small enough that full Read is cheap
  - Projects without .serena/memories — Serena not onboarded here

Exit codes:
  0 — allow silently, OR emit JSON with permissionDecision=deny to block
"""

import json
import os
import re
import sys
from pathlib import Path

# Shared signal capture per claude/rules/gate-design.md Rule 2.
sys.path.insert(0, str(Path(__file__).parent))
try:
    from _gate_signal import record as _record_signal
except ImportError:  # pragma: no cover
    def _record_signal(*_args, **_kwargs) -> None:
        return None


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Extensions treated as "source code" that Serena should handle.
# Conservative list — focuses on languages with mature LSP coverage.
_SOURCE_EXTENSIONS = frozenset({
    ".py",
    ".js", ".jsx", ".mjs", ".cjs",
    ".ts", ".tsx",
    ".rb",
    ".go",
    ".rs",
    ".java", ".kt",
    ".swift",
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp",
    ".cs",
    ".php",
    ".scala",
    ".ex", ".exs",
    ".elm",
    ".dart",
})

# Files under this size (in bytes) are small enough that a full Read is cheap.
# ~200 lines at an average of 40 chars/line = ~8KB.
_SMALL_FILE_BYTES = 8 * 1024

# Bash commands that read a full file's contents and would bypass the Read gate.
# Matches the first token of the command against this set.
_FILE_READING_COMMANDS = frozenset({"cat", "bat", "head", "tail", "less", "more"})


# ---------------------------------------------------------------------------
# Subagent detection (mirrors context_burn_detector.py)
# ---------------------------------------------------------------------------

def _is_subagent() -> bool:
    """Return True if this hook is running inside a subagent context.

    Subagents exist specifically to absorb research work off the main thread.
    Blocking their Reads would defeat the purpose of the system.
    """
    agent_env_vars = (
        "CLAUDE_AGENT_NAME",
        "CLAUDE_AGENT_TYPE",
        "CLAUDE_SUBAGENT",
        "CLAUDE_TEAM_NAME",
        "CLAUDE_AGENT_ID",
    )
    return any(os.environ.get(var) for var in agent_env_vars)


# ---------------------------------------------------------------------------
# Serena onboarding check
# ---------------------------------------------------------------------------

def _find_serena_memories(start: Path) -> bool:
    """Walk up from ``start`` looking for a project containing .serena/memories.

    Uses the same "project root" signals as serena_onboarding_check.sh.
    Returns True if .serena/memories exists and is non-empty.
    """
    project_signals = (".git", "pyproject.toml", "package.json", "Gemfile",
                       "Cargo.toml", "go.mod")
    current = start.resolve() if start.exists() else start
    for directory in (current, *current.parents):
        # Did we hit a project boundary?
        if any((directory / sig).exists() for sig in project_signals):
            memories = directory / ".serena" / "memories"
            if memories.is_dir():
                try:
                    return any(memories.iterdir())
                except OSError:
                    return False
            return False
        if directory == directory.parent:  # filesystem root
            break
    return False


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------

def _is_source_file(path: Path) -> bool:
    """Return True if ``path`` has a source-code extension Serena handles."""
    return path.suffix.lower() in _SOURCE_EXTENSIONS


def _is_small_file(path: Path) -> bool:
    """Return True if ``path`` is below the size threshold."""
    try:
        return path.stat().st_size < _SMALL_FILE_BYTES
    except OSError:
        # File doesn't exist / unreadable — let Read handle the error naturally
        return True


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

_BLOCK_MESSAGE = (
    "Blocked: full-file Read on a source-code file while Serena is active for this "
    "project.\n\n"
    "Use Serena's symbol tools instead — they answer the same questions with a "
    "fraction of the context:\n"
    "  mcp__serena__get_symbols_overview(relative_path=\"{rel_path}\")\n"
    "    — top-level structure of this file (classes, functions, methods)\n"
    "  mcp__serena__find_symbol(name_path=\"<Symbol>\", relative_path=\"{rel_path}\")\n"
    "    — fetch a specific class/method body\n"
    "  mcp__serena__find_referencing_symbols(name_path=\"<Symbol>\", relative_path=\"{rel_path}\")\n"
    "    — who uses this symbol\n"
    "  mcp__serena__search_for_pattern(substring_pattern=\"...\")\n"
    "    — regex/text search within project scope\n\n"
    "If Serena's LSP does not handle this file well (rare — try get_symbols_overview "
    "first to confirm), retry Read with an explicit offset and limit to fetch only "
    "the range you need."
)


def _deny(reason: str) -> int:
    """Emit a PreToolUse deny decision and return exit code 0."""
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    return 0


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

def _handle_read(tool_input: dict, cwd: Path) -> int:
    file_path_str = tool_input.get("file_path", "")
    if not file_path_str:
        return 0

    file_path = Path(file_path_str)

    # Targeted read — allow
    if tool_input.get("offset") is not None or tool_input.get("limit") is not None:
        return 0

    # Not source code — allow
    if not _is_source_file(file_path):
        return 0

    # Small file — allow
    if _is_small_file(file_path):
        return 0

    # Serena not onboarded for this project — allow
    project_anchor = file_path.parent if file_path.parent.exists() else cwd
    if not _find_serena_memories(project_anchor):
        return 0

    # Build a path string the model can paste directly into Serena calls.
    try:
        rel = file_path.resolve().relative_to(cwd.resolve())
        rel_path = str(rel)
    except ValueError:
        rel_path = str(file_path)

    _record_signal(
        gate_name="serena_preference_gate",
        decision="deny",
        reason="full-file Read on source while Serena active",
        path=rel_path,
        surface="Read",
    )
    return _deny(_BLOCK_MESSAGE.format(rel_path=rel_path))


_BASH_FILE_TOKEN = re.compile(r"[^\s|&;<>()]+")


def _handle_bash(tool_input: dict, cwd: Path) -> int:
    command = tool_input.get("command", "")
    if not command:
        return 0

    # Match patterns like: cat path, head -n 50 path, tail path/to/file, etc.
    # Only catch a simple leading invocation — complex pipelines are out of
    # scope (too easy to false-positive).
    stripped = command.lstrip()
    tokens = stripped.split(None, 1)
    if len(tokens) < 2:
        return 0

    cmd_name = Path(tokens[0]).name  # strips /usr/bin/ etc.
    if cmd_name not in _FILE_READING_COMMANDS:
        return 0

    # Pull the last bare token on the line as a candidate file path. Skips
    # flag-style tokens (starting with -). Good enough for the common case
    # "head -n 50 path/to/file.py".
    rest = tokens[1]
    candidates = [
        t for t in _BASH_FILE_TOKEN.findall(rest)
        if not t.startswith("-")
    ]
    if not candidates:
        return 0
    target = candidates[-1]

    # Resolve relative to cwd
    target_path = Path(target)
    if not target_path.is_absolute():
        target_path = (cwd / target_path)

    if not _is_source_file(target_path):
        return 0
    if _is_small_file(target_path):
        return 0

    project_anchor = target_path.parent if target_path.parent.exists() else cwd
    if not _find_serena_memories(project_anchor):
        return 0

    try:
        rel = target_path.resolve().relative_to(cwd.resolve())
        rel_path = str(rel)
    except ValueError:
        rel_path = str(target_path)

    _record_signal(
        gate_name="serena_preference_gate",
        decision="deny",
        reason=f"full-file Bash {cmd_name} on source while Serena active",
        path=rel_path,
        surface="Bash",
        cmd=cmd_name,
    )
    return _deny(
        "Blocked: full-file shell read ({cmd}) on source code while Serena is "
        "active. Use Serena's symbol tools instead — see Read block message for "
        "details. Target: {path}\n\n"
        "If you need a byte range, use Read with offset/limit rather than {cmd}."
        .format(cmd=cmd_name, path=rel_path)
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    if _is_subagent():
        return 0

    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    if not isinstance(tool_input, dict):
        return 0

    cwd_raw = data.get("cwd") or data.get("workingDirectory") or os.getcwd()
    cwd = Path(cwd_raw)

    if tool_name == "Read":
        return _handle_read(tool_input, cwd)
    if tool_name == "Bash":
        return _handle_bash(tool_input, cwd)
    return 0


if __name__ == "__main__":
    sys.exit(main())
