#!/usr/bin/env python3
"""PreToolUse hook (Claude, Codex, Pi): block full-file reads of large source
files when Serena is onboarded for the project.

Fires on Read (Claude; Pi's adapter sends the same shape) and on Bash (every
host; Codex reads files only through the shell).

Rationale: reading an entire source file top-to-bottom burns main-context tokens
when Serena's LSP-backed tools (get_symbols_overview, find_symbol,
find_referencing_symbols) can answer the same questions with a fraction of the
tokens. Only fires when .serena/memories is present in the project tree — silent
in projects where Serena is not onboarded.

Shell reads: an unpiped, unredirected ``cat``/``bat``/``less``/``more``/``nl``
of a file is a full read. Ranged reads (``head``, ``tail``, ``sed -n 'a,bp'``)
and anything piped onward or redirected are allowed — the same parity Read gets
for offset/limit.

Exemptions (all allow silently):
  - Subagents (detected via env vars) — they do their own exploration
  - Read with offset/limit, or a ranged shell read — targeted read is fine
  - Non-source files (markdown, YAML, JSON, config, logs, shell) — not Serena's
    domain
  - Files under the size threshold — small enough that full Read is cheap
  - Projects without .serena/memories — Serena not onboarded here

Exit codes:
  0 — allow silently, OR emit JSON with permissionDecision=deny to block
"""

from __future__ import annotations

import json
import os
import shlex
import sys
from pathlib import Path

# Shared signal capture per claude/rules/gate-design.md Rule 2.
sys.path.insert(0, str(Path(__file__).parent))
try:
    from _gate_signal import record as _record_signal
except ImportError:  # pragma: no cover
    def _record_signal(*_args, **_kwargs) -> None:
        return None

from _host_output import deny as _deny_envelope  # noqa: E402
from _serena_tools import serena_guidance  # noqa: E402


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

# Shell commands that print a whole file. head/tail/sed read a range and are
# deliberately absent: they are the shell's offset/limit.
_FULL_READ_COMMANDS = frozenset({"cat", "bat", "less", "more", "nl"})

# Shell operators (as shlex groups them) that end a simple command, and the
# characters every operator token is made of.
_SEQUENCE_OPERATORS = frozenset({"&&", "||", ";", ";;", ";&", "&"})
_PIPES = frozenset({"|", "|&"})
_OPERATOR_CHARS = frozenset("();<>|&")


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

    Uses the same project-root signals as serena_preference_injection.py.
    Returns True if .serena/memories exists and is non-empty.
    """
    project_signals = (".git", "pyproject.toml", "package.json", "Gemfile",
                       "Cargo.toml", "go.mod", ".serena/project.yml")
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
        # File doesn't exist / unreadable — let the read handle the error naturally
        return True


def _gated_target(path: Path, cwd: Path) -> str | None:
    """The cwd-relative path to name in a denial, or None when the read is fine."""
    if not _is_source_file(path) or _is_small_file(path):
        return None
    project_anchor = path.parent if path.parent.exists() else cwd
    if not _find_serena_memories(project_anchor):
        return None
    try:
        return str(path.resolve().relative_to(cwd.resolve()))
    except ValueError:
        return str(path)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _deny(rel_path: str, what: str) -> int:
    """Emit the PreToolUse deny envelope (exit 0; see _host_output)."""
    reason = (
        f"Blocked: {what} of the large source file {rel_path} while Serena is "
        "onboarded for this project.\n\n"
        f"{serena_guidance(rel_path)}\n\n"
        "If Serena cannot parse this file (try get_symbols_overview first), read "
        "only the range you need: Read with offset and limit, or "
        f"`sed -n 'START,ENDp' {rel_path}`."
    )
    print(json.dumps(_deny_envelope(reason)))
    return 0


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

def _handle_read(tool_input: dict, cwd: Path) -> int:
    file_path_str = tool_input.get("file_path", "")
    if not file_path_str:
        return 0

    # Targeted read — allow
    if tool_input.get("offset") is not None or tool_input.get("limit") is not None:
        return 0

    file_path = Path(file_path_str)
    if not file_path.is_absolute():
        file_path = cwd / file_path
    rel_path = _gated_target(file_path, cwd)
    if rel_path is None:
        return 0

    _record_signal(
        gate_name="serena_preference_gate",
        decision="deny",
        reason="full-file Read on source while Serena active",
        path=rel_path,
        surface="Read",
    )
    return _deny(rel_path, "full-file read")


def _simple_commands(command: str) -> list[tuple[list[str], bool]]:
    """Split a shell line into (words, output_is_shaped) per simple command.

    ``output_is_shaped`` is True when the command's stdout is piped onward or
    redirected, so it never lands in context whole. Input redirection
    (``cat < file``) is not shaping: the redirect target stays a word. Quote-
    aware via shlex; heredoc bodies are not modelled.
    """
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    lexer.commenters = ""
    commands: list[tuple[list[str], bool]] = []
    words: list[str] = []
    shaped = False
    for token in lexer:
        if token in _SEQUENCE_OPERATORS or token in _PIPES:
            if words:
                commands.append((words, shaped or token in _PIPES))
            words, shaped = [], False
        elif set(token) <= _OPERATOR_CHARS:
            # Redirection or grouping; only stdout redirection shapes output.
            if ">" in token:
                if words and words[-1].isdigit() and words[-1] != "1":
                    words.pop()  # `2>`: an fd prefix, and stdout still flows
                else:
                    shaped = True
        else:
            words.append(token)
    if words:
        commands.append((words, shaped))
    return commands


def _handle_bash(tool_input: dict, cwd: Path) -> int:
    command = tool_input.get("command", "")
    if not isinstance(command, str) or not command.strip():
        return 0

    try:
        commands = _simple_commands(command)
    except ValueError:  # unbalanced quotes — not ours to judge
        return 0

    for words, shaped in commands:
        cmd_name = Path(words[0]).name  # strips /usr/bin/ etc.
        if cmd_name == "cd" and len(words) == 2:
            cwd = cwd / words[1]
            continue
        if shaped or cmd_name not in _FULL_READ_COMMANDS:
            continue
        for arg in words[1:]:
            if arg.startswith("-"):
                continue
            target = Path(arg)
            if not target.is_absolute():
                target = cwd / target
            rel_path = _gated_target(target, cwd)
            if rel_path is None:
                continue
            _record_signal(
                gate_name="serena_preference_gate",
                decision="deny",
                reason=f"full-file Bash {cmd_name} on source while Serena active",
                path=rel_path,
                surface="Bash",
                cmd=cmd_name,
            )
            return _deny(rel_path, f"full-file `{cmd_name}`")
    return 0


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
    if not isinstance(data, dict):
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
