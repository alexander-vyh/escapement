#!/usr/bin/env python3
"""Claude Code hook: detect excessive inline research without agent dispatch.

Tracks research operations in the main thread and emits a single nudge once
the weighted cost crosses a threshold. The counter resets when an Agent tool
is used. The nudge is emitted at most once per (session, threshold crossing)
to avoid noise — if the model continues inline work after the nudge, further
tool calls stay silent until the counter resets via Agent dispatch.

Weights (empirically chosen):
  Grep, Glob             → 0  (cheap, almost always the right tool)
  Read with offset/limit → 1  (targeted, low cost)
  Read full-file non-code→ 1  (config, markdown, logs — usually fine)
  Read full-file code    → 5  (pathological pattern — where the budget lives)

State is persisted to /tmp/ using a session-derived filename so counting
survives across individual tool calls within a session.

Input (via stdin):
  JSON with hook_event_name, tool_name, tool_input
Exit codes:
  0 — allow, with optional systemMessage nudge on the threshold-crossing call
"""

import json
import os
import sys
from pathlib import Path


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


def _state_file() -> Path:
    session_id = os.environ.get("CLAUDE_SESSION_ID") or str(os.getppid())
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

def _weight_for(tool_name: str, tool_input: dict) -> int:
    if tool_name in ("Grep", "Glob"):
        return 0
    if tool_name != "Read":
        return 0

    if tool_input.get("offset") is not None or tool_input.get("limit") is not None:
        return _WEIGHT_READ_TARGETED

    file_path = tool_input.get("file_path", "")
    if not file_path:
        return _WEIGHT_READ_NON_SOURCE

    ext = Path(file_path).suffix.lower()
    if ext in _SOURCE_EXTENSIONS:
        return _WEIGHT_READ_SOURCE_FULL
    return _WEIGHT_READ_NON_SOURCE


# ---------------------------------------------------------------------------
# Nudge text — descriptive, no "proceed" escape hatch
# ---------------------------------------------------------------------------

_NUDGE_MESSAGE = (
    "Context-burn threshold crossed: {count} weighted units of inline research "
    "on the main thread without dispatching an agent.\n\n"
    "Continuing investigation should happen in an explorer agent so main-thread "
    "context stays focused on the task. Dispatch pattern:\n"
    "  TeamCreate(team_name=\"research\")\n"
    "  Agent(name=\"explorer\", team_name=\"research\",\n"
    "        description=\"...\", prompt=\"<batch of questions to answer>\")\n\n"
    "This notice fires once per session; it will not repeat until an Agent tool "
    "is dispatched (which resets the counter)."
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
    tool_input = data.get("tool_input", {}) if isinstance(data.get("tool_input"), dict) else {}

    state_path = _state_file()
    state = _read_state(state_path)

    # Agent dispatch → reset counter and nudged flag
    if tool_name == "Agent":
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
        json.dump({"systemMessage": _NUDGE_MESSAGE.format(count=state["count"])}, sys.stdout)

    return 0


if __name__ == "__main__":
    sys.exit(main())
