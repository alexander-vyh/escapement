#!/usr/bin/env python3
"""Claude Code hook: enforce named agents, block multi-agent dispatch without teams.

Three levels of enforcement:
  - HARD BLOCK: Agent calls without `name` — anonymous agents are never OK
  - HARD BLOCK: Second+ agent call without `team_name` in a 30-second window
    (detects multi-agent dispatch without TeamCreate)
  - SOFT NUDGE: First agent call with `name` but no `team_name` — might be a
    legitimate one-off, so warn but allow

Input (via stdin):
  JSON with hook_event_name, tool_name, tool_input
Exit codes:
  0 — allow (with optional system message)
  2 — block (missing name, or multi-agent without team)
"""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Shared signal capture per claude/rules/gate-design.md Rule 2.
sys.path.insert(0, str(Path(__file__).parent))
try:
    from _gate_signal import record as _record_signal
except ImportError:  # pragma: no cover
    def _record_signal(*_args, **_kwargs) -> None:
        return None

_LOG_FILE = Path.home() / ".claude" / "hooks" / "agent-dispatch.log"
_TRACKER_PREFIX = "agent-team-tracker-"
_TRACKER_DIR = Path.home() / ".claude" / "hooks" / "state"
_WINDOW_SECONDS = 30
_STALE_SECONDS = 86400  # 24 hours


def _is_safe_session_id(value: str) -> bool:
    """A session id is safe to use as a filename component.

    Reject empty values and anything that could escape the tracker
    directory (path separators, traversal). Tracker files are keyed by
    session id, so an unsafe id is a path-traversal vector.
    """
    if not value:
        return False
    if "/" in value or "\\" in value or value in (".", ".."):
        return False
    if os.sep in value or (os.altsep and os.altsep in value):
        return False
    return True


def _get_session_id(data: dict | None = None) -> str:
    """Resolve a unique, filesystem-safe session identifier.

    Preference order: the payload's ``session_id``, then the
    ``CLAUDE_SESSION_ID`` env var, then the parent PID. Unsafe values
    (empty, path-traversal) at any tier are skipped in favour of the
    next tier so the tracker file always lands inside _TRACKER_DIR.
    """
    candidates = []
    if isinstance(data, dict):
        candidates.append((data.get("session_id") or "").strip())
    candidates.append((os.environ.get("CLAUDE_SESSION_ID") or "").strip())
    for candidate in candidates:
        if _is_safe_session_id(candidate):
            return candidate
    return str(os.getppid())


def _is_ci_without_session(data: dict) -> bool:
    """True when running in CI with no usable session id.

    In CI the parent-PID fallback is meaningless (every step is a fresh
    process), so teamless-multi-agent tracking would produce false
    positives. When CI is set and neither the payload nor the env
    carries a session id, the hook should stand down. If a real
    session id is present, normal enforcement still applies.
    """
    if not (os.environ.get("CI") or "").strip():
        return False
    payload_sid = (data.get("session_id") or "").strip() if isinstance(data, dict) else ""
    env_sid = (os.environ.get("CLAUDE_SESSION_ID") or "").strip()
    return not (_is_safe_session_id(payload_sid) or _is_safe_session_id(env_sid))


def _get_track_file(data: dict | None = None) -> Path:
    """Return the session-keyed tracker file path."""
    try:
        _TRACKER_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return _TRACKER_DIR / f"{_TRACKER_PREFIX}{_get_session_id(data)}"


def _cleanup_stale_trackers() -> None:
    """Remove tracker files older than 24 hours."""
    try:
        now = time.time()
        for entry in _TRACKER_DIR.iterdir():
            if entry.name.startswith(_TRACKER_PREFIX):
                try:
                    mtime = entry.stat().st_mtime
                    if (now - mtime) > _STALE_SECONDS:
                        entry.unlink()
                except OSError:
                    pass
    except OSError:
        pass


def _log(msg: str) -> None:
    try:
        with open(_LOG_FILE, "a") as f:
            f.write(f"{datetime.now().isoformat()} {msg}\n")
    except OSError:
        pass


def _get_recent_teamless_count(data: dict | None = None) -> int:
    """Count teamless agent dispatches within the tracking window."""
    track_file = _get_track_file(data)
    try:
        if not track_file.exists():
            return 0
        lines = track_file.read_text().strip().split("\n")
        now = time.time()
        return sum(
            1 for line in lines
            if line.strip() and (now - float(line.strip())) < _WINDOW_SECONDS
        )
    except (OSError, ValueError):
        return 0


def _record_teamless_dispatch(data: dict | None = None) -> None:
    """Record a teamless agent dispatch timestamp and prune old entries."""
    track_file = _get_track_file(data)
    now = time.time()
    try:
        # Read existing, prune old entries, append new
        entries: list[str] = []
        if track_file.exists():
            for line in track_file.read_text().strip().split("\n"):
                if line.strip():
                    try:
                        ts = float(line.strip())
                        if (now - ts) < _WINDOW_SECONDS:
                            entries.append(line.strip())
                    except ValueError:
                        pass
        entries.append(str(now))
        track_file.write_text("\n".join(entries) + "\n")
    except OSError:
        pass


_BLOCK_NO_NAME = """\
🚫 AGENT BLOCKED — missing `name` parameter.

Anonymous agents cannot be addressed via SendMessage.
Every agent MUST have a `name`.

Quick one-off agent:
  Agent(name="fetcher", description="...", prompt="...")

Multi-agent team (agents that talk to each other):
  TeamCreate(team_name="research")
  Agent(name="explorer-1", team_name="research", description="...", prompt="...")
  Agent(name="explorer-2", team_name="research", description="...", prompt="...")

There is almost never a reason to dispatch an anonymous agent. The
two legitimate cases — a one-off lookup, or an explicit user-requested
anonymous probe — are still served by giving the agent a name (even
something throwaway like name="oneoff" or name="probe"). The cost of
naming is one keyword arg; the cost of leaving it off is that the
agent cannot be addressed, paired, or coordinated with.\
"""

_BLOCK_MULTI_NO_TEAM = """\
🚫 AGENT BLOCKED — multiple agents dispatched without `team_name`.

You already dispatched an agent without a team in the last {window}s.
This means you are doing multi-agent work and MUST use TeamCreate.

REQUIRED pattern for multi-agent work:

  TeamCreate(team_name="research")
  Agent(name="agent-1", team_name="research", description="...", prompt="...")
  Agent(name="agent-2", team_name="research", description="...", prompt="...")

Go back and:
1. Call TeamCreate(team_name="...") FIRST
2. Add team_name="..." to ALL Agent calls
3. Re-dispatch all agents together\
"""

_NUDGE_NO_TEAM = (
    "⚠️ WARNING: Agent \"{name}\" was dispatched without team_name. "
    "If you dispatch another agent without team_name in the next 30 seconds, "
    "it WILL BE BLOCKED. If this is multi-agent work, STOP NOW — do not "
    "dispatch more agents. Instead: (1) call TeamCreate(team_name=\"...\") "
    "(2) re-dispatch ALL agents with team_name. Without team_name, agents "
    "cannot SendMessage to each other or appear as selectable teammates."
)


def main() -> int:
    _cleanup_stale_trackers()

    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    tool_name = data.get("tool_name", "")
    _log(f"CALLED tool_name={tool_name!r}")

    if tool_name != "Agent":
        return 0

    # In CI with no usable session id, the PPID fallback is meaningless
    # (each step is a fresh process), so teamless tracking would produce
    # false positives. Stand down rather than block legitimate dispatch.
    if _is_ci_without_session(data):
        _log("SKIPPED — CI without session id")
        return 0

    tool_input = data.get("tool_input", {})
    if not isinstance(tool_input, dict):
        return 0

    agent_name = (tool_input.get("name") or "").strip()
    team_name = (tool_input.get("team_name") or "").strip()
    _log(f"AGENT name={agent_name!r} team={team_name!r} desc={tool_input.get('description', '')!r}")

    # HARD BLOCK: no name
    if not agent_name:
        _log("BLOCKED — no name")
        _record_signal(
            gate_name="enforce_named_agents",
            decision="deny",
            reason="agent dispatched without name parameter",
        )
        result = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": _BLOCK_NO_NAME,
            }
        }
        json.dump(result, sys.stdout)
        return 2

    # Team check: only applies when team_name is missing
    if not team_name:
        recent_count = _get_recent_teamless_count(data)
        _record_teamless_dispatch(data)

        if recent_count > 0:
            # Second+ teamless agent in window — HARD BLOCK
            _log(f"BLOCKED — multi-agent without team ({recent_count + 1} in {_WINDOW_SECONDS}s)")
            _record_signal(
                gate_name="enforce_named_agents",
                decision="deny",
                reason=f"second teamless agent within {_WINDOW_SECONDS}s window",
                name=agent_name,
                recent_count=recent_count,
            )
            result = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": _BLOCK_MULTI_NO_TEAM.format(
                        window=_WINDOW_SECONDS
                    ),
                }
            }
            json.dump(result, sys.stdout)
            return 2

        # First teamless agent in window — SOFT NUDGE
        _log("NUDGED — no team_name (first in window)")
        _record_signal(
            gate_name="enforce_named_agents",
            decision="nudge",
            reason="first teamless agent in window — second within 30s will block",
            name=agent_name,
        )
        result = {
            "systemMessage": _NUDGE_NO_TEAM.format(name=agent_name),
        }
        json.dump(result, sys.stdout)
        return 0

    _log("ALLOWED — named agent on team")
    _record_signal(
        gate_name="enforce_named_agents",
        decision="allow",
        reason="named agent on team",
        name=agent_name,
        team=team_name,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
