#!/usr/bin/env python3
"""Agent-dispatch hook: detect excessive inline research without agent dispatch.

Tracks research operations in the main thread and emits a single nudge once
the weighted cost crosses a threshold. The counter resets when an agent is
dispatched (Claude `Agent`, Codex spawn_agent, Pi's translated `Agent`). The
nudge is emitted at most once per (session, threshold crossing) to avoid
noise — if the model continues inline work after the nudge, further tool calls
stay silent until the counter resets via agent dispatch.

Weights (empirically chosen):
  Grep, Glob, rg/grep/find/ls → 0  (cheap, almost always the right tool)
  Read with offset/limit      → 1  (targeted; sed -n/head/tail, piped cat)
  Read full-file non-code     → 1  (config, markdown, logs — usually fine)
  Read full-file code         → 5  (pathological pattern — where the budget lives)

Codex has no Read tool: research there is Bash (`cat`, `sed -n`, `rg`), so a
Bash command is weighted by the file reads it performs. Tool calls made inside
a subagent never count (Codex marks them with agent_id; Claude with env).

State is persisted to /tmp/ using a session-derived filename so counting
survives across individual tool calls within a session.

Input (via stdin):
  JSON with hook_event_name, tool_name, tool_input
Exit codes:
  0 — allow, with an optional advisory nudge on the threshold-crossing call
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

from _agent_dispatch import agent_dispatch, host as _host, is_subagent_call  # noqa: E402
from _host_output import advisory  # noqa: E402

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_DEFAULT_THRESHOLD = 10  # weighted units

# Extensions treated as source code for weight purposes.
_SOURCE_EXTENSIONS = frozenset({
    ".py", ".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".rb", ".go", ".rs",
    ".java", ".kt", ".swift", ".c", ".cc", ".cpp", ".cxx", ".h", ".hpp",
    ".cs", ".php", ".scala", ".ex", ".exs", ".elm", ".dart",
})

_WEIGHT_READ_TARGETED = 1
_WEIGHT_READ_NON_SOURCE = 1
_WEIGHT_READ_SOURCE_FULL = 5


# ---------------------------------------------------------------------------
# Threshold + state path
# ---------------------------------------------------------------------------

def _get_threshold() -> int:
    try:
        return int(os.environ.get("CONTEXT_BURN_THRESHOLD", _DEFAULT_THRESHOLD))
    except (ValueError, TypeError):
        return _DEFAULT_THRESHOLD


def _state_file(data: dict) -> Path:
    # The payload's session id before the parent pid: a Codex hook's parent is
    # a fresh shell per call, so a pid key would never accumulate a count.
    session_id = (
        os.environ.get("CLAUDE_SESSION_ID")
        or str(data.get("session_id") or "")
        or str(os.getppid())
    )
    return Path(f"/tmp/context_burn_{session_id}.json")


# ---------------------------------------------------------------------------
# Subagent detection
# ---------------------------------------------------------------------------

def _is_subagent() -> bool:
    agent_env_vars = (
        "CLAUDE_AGENT_NAME",
        "CLAUDE_AGENT_TYPE",
        "CLAUDE_SUBAGENT",
        "CLAUDE_TEAM_NAME",
        "CLAUDE_AGENT_ID",
    )
    return any(os.environ.get(var) for var in agent_env_vars)


# ---------------------------------------------------------------------------
# State persistence
# ---------------------------------------------------------------------------

def _read_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {"count": 0, "nudged": False}


def _write_state(path: Path, state: dict) -> None:
    try:
        path.write_text(json.dumps(state))
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Weighting
# ---------------------------------------------------------------------------

def _file_weight(file_path: str) -> int:
    if Path(file_path).suffix.lower() in _SOURCE_EXTENSIONS:
        return _WEIGHT_READ_SOURCE_FULL
    return _WEIGHT_READ_NON_SOURCE


def _weight_for(tool_name: str, tool_input: dict) -> int:
    if tool_name == "Bash":
        return _bash_weight(str(tool_input.get("command") or ""))
    if tool_name != "Read":
        return 0  # Grep, Glob and everything else cost nothing here

    if tool_input.get("offset") is not None or tool_input.get("limit") is not None:
        return _WEIGHT_READ_TARGETED

    file_path = tool_input.get("file_path", "")
    if not file_path:
        return _WEIGHT_READ_NON_SOURCE
    return _file_weight(file_path)


_FULL_READERS = frozenset({"cat", "nl", "bat", "less", "more"})
_RANGED_READERS = frozenset({"head", "tail"})
_SHELL_OPERATORS = frozenset("|&;()<>")
_REDIRECTIONS = frozenset({">", ">>", ">|", "&>", "&>>", ">&", "<", "<<", "<<<", "<&"})
_STDOUT_TO_FILE = frozenset({">", ">>", ">|", "&>", "&>>"})


def _simple_read_weight(words: list[str], piped: bool) -> int:
    """What one simple command costs as a Read: 0 unless it reads a file."""
    while words and "=" in words[0] and not words[0].startswith("-"):
        words = words[1:]  # leading VAR=value assignments
    if not words:
        return 0
    program = Path(words[0]).name
    operands = [word for word in words[1:] if not word.startswith("-")]
    if program in _FULL_READERS:
        if piped:
            return _WEIGHT_READ_TARGETED * len(operands)
        return sum(_file_weight(operand) for operand in operands)
    if program in _RANGED_READERS and operands:
        return _WEIGHT_READ_TARGETED
    if program == "sed" and "-n" in words and "-i" not in words and len(operands) >= 2:
        return _WEIGHT_READ_TARGETED
    return 0


def _bash_weight(command: str) -> int:
    """Weight of the file reads a shell line performs, as if each were a Read.

    Output that is redirected to a file never reaches the context, so it costs
    nothing; output piped onward is shaped, so it costs like a targeted read.
    """
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return 0
    weight = 0
    words: list[str] = []
    to_file = False
    stream = iter([*tokens, ";"])
    for token in stream:
        if token in _REDIRECTIONS:
            fd = words.pop() if words and words[-1] in ("0", "1", "2") else "1"
            next(stream, None)  # the redirection target is not an operand
            if token in _STDOUT_TO_FILE and (fd == "1" or token.startswith("&")):
                to_file = True
            continue
        if token and set(token) <= _SHELL_OPERATORS:
            if words and not to_file:
                weight += _simple_read_weight(words, piped=token in ("|", "|&"))
            words = []
            to_file = False
        else:
            words.append(token)
    return weight


# ---------------------------------------------------------------------------
# Nudge text — descriptive, no "proceed" escape hatch
# ---------------------------------------------------------------------------

_NUDGE_MESSAGE = (
    "Context-burn threshold crossed: {count} weighted units of inline research "
    "on the main thread without dispatching an agent.\n\n"
    "Continuing investigation should happen in an explorer agent so main-thread "
    "context stays focused on the task. Dispatch pattern:\n"
    "{dispatch}\n\n"
    "This notice fires once per session; it will not repeat until an agent is "
    "dispatched (which resets the counter)."
)

# The dispatch pattern, in the words of the host that will read it.
_DISPATCH_PATTERN = {
    "claude": (
        "  TeamCreate(team_name=\"research\")\n"
        "  Agent(name=\"explorer\", team_name=\"research\",\n"
        "        description=\"...\", prompt=\"<batch of questions to answer>\")"
    ),
    "codex": (
        "  spawn_agent(task_name=\"explorer\", "
        "message=\"<batch of questions to answer>\")"
    ),
    "pi": "  the subagent tool with a scout agent and the batch of questions as its task",
}


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
    if not isinstance(data, dict) or is_subagent_call(data):
        return 0

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {}) if isinstance(data.get("tool_input"), dict) else {}

    state_path = _state_file(data)
    state = _read_state(state_path)

    # Agent dispatch → reset counter and nudged flag
    if agent_dispatch(data) is not None:
        _write_state(state_path, {"count": 0, "nudged": False})
        return 0

    weight = _weight_for(tool_name, tool_input)
    if weight == 0:
        return 0

    state["count"] = int(state.get("count", 0)) + weight
    threshold = _get_threshold()

    # Fire once per crossing. The nudged flag is only cleared on Agent dispatch.
    should_nudge = state["count"] >= threshold and not state.get("nudged", False)
    if should_nudge:
        state["nudged"] = True

    _write_state(state_path, state)

    if should_nudge:
        _record_signal(
            gate_name="context_burn_detector",
            decision="nudge",
            reason=f"context burn cost {state['count']} crossed threshold {threshold}",
            count=state["count"],
            threshold=threshold,
            tool_name=tool_name,
        )
        message = _NUDGE_MESSAGE.format(
            count=state["count"], dispatch=_DISPATCH_PATTERN[_host(data)]
        )
        json.dump(advisory(message), sys.stdout)

    return 0


if __name__ == "__main__":
    sys.exit(main())
