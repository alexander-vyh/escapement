#!/usr/bin/env python3
"""Claude Code hook: soft gate on bd close — warns if no review agent was dispatched.

Dual-purpose PreToolUse hook:
  - On Agent calls: checks if name/description contains "review" and records it
    in a per-session state file under /tmp/
  - On Bash calls: checks if the command is `bd close` or `bd update --status closed`
    and warns if no review agent was recorded for this session

This is advisory (soft warning) — it never blocks, only nudges.

Input (via stdin):
  JSON with hook_event_name, tool_name, tool_input, session_id
Exit codes:
  0 — allow (with optional system message warning)
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

_STATE_DIR = Path("/tmp/claude-review-gate")

# Agent types that structurally count as review agents. A dispatch with one
# of these subagent_types satisfies the gate even when the prompt is blinded
# (contains no "review" words) — which is the common case for disciplined
# blinded-review workflows.
_REVIEWER_SUBAGENT_TYPES = {
    "adversarial-reviewer",
    "code-reviewer",
    "superpowers:code-reviewer",
    "test-quality-reviewer",
}

# Word-boundary pattern matching the review-word family (review, reviews,
# reviewed, reviewer, reviewers, reviewing) but NOT false-positive substrings
# like "reviewable", "preview", or "previewer".
_REVIEW_WORD_RE = re.compile(r"\breview(?:s|ed|er|ers|ing)?\b", re.IGNORECASE)


def _state_file(session_id: str) -> Path:
    """Return the state file path for a given session."""
    return _STATE_DIR / f"{session_id}.json"


def _read_state(session_id: str) -> dict:
    """Read the review dispatch state for a session."""
    sf = _state_file(session_id)
    if not sf.exists():
        return {"reviews": []}
    try:
        return json.loads(sf.read_text())
    except (json.JSONDecodeError, OSError):
        return {"reviews": []}


def _write_state(session_id: str, state: dict) -> None:
    """Write the review dispatch state for a session."""
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        _state_file(session_id).write_text(json.dumps(state))
    except OSError:
        pass


def _is_review_agent(tool_input: dict) -> bool:
    """Return True if the agent dispatch counts as a code/design review.

    Two signals, either is sufficient:
      1. subagent_type is in the explicit reviewer allowlist (primary —
         catches blinded dispatches whose prompts contain no review words)
      2. name/description/prompt contains a whole-word match for the
         review-word family (backward compat for untyped dispatches)
    """
    subagent_type = (tool_input.get("subagent_type") or "").strip()
    if subagent_type in _REVIEWER_SUBAGENT_TYPES:
        return True

    for field in ("name", "description", "prompt"):
        value = tool_input.get(field) or ""
        if _REVIEW_WORD_RE.search(value):
            return True
    return False


def _is_close_command(command: str) -> bool:
    """Return True if the bash command is a bd close or bd update --status closed."""
    if re.search(r"bd\s+close", command):
        return True
    if re.search(r"bd\s+update\s+.*--status[=\s]+closed", command):
        return True
    return False


_WARN_NO_REVIEW = (
    "No review agent was dispatched before closing this task. "
    "Review catches drift between spec and implementation, oracle "
    "downgrades, and missed regressions — the kind of failures that "
    "the implementer's own context makes invisible.\n\n"
    "Consider dispatching a code-reviewer or adversarial-reviewer "
    "agent first. The gate is satisfied by either:\n"
    "  (1) subagent_type contains 'reviewer' (e.g. code-reviewer, "
    "adversarial-reviewer, test-quality-reviewer), OR\n"
    "  (2) the agent's name/description/prompt contains a review-word "
    "(review, audit, critique, etc.).\n\n"
    "If you've already reviewed manually or this work doesn't need "
    "review, say 'proceed' to close anyway."
)


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    session_id = data.get("session_id", "") or os.environ.get("CLAUDE_SESSION_ID", "default")

    if not isinstance(tool_input, dict):
        return 0

    # --- Agent tracking path ---
    if tool_name == "Agent":
        if _is_review_agent(tool_input):
            state = _read_state(session_id)
            agent_name = tool_input.get("name", "unknown")
            state["reviews"].append(agent_name)
            _write_state(session_id, state)
        return 0

    # --- Bash gating path ---
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        if not _is_close_command(command):
            return 0

        state = _read_state(session_id)
        if state["reviews"]:
            # Review agent was dispatched — allow silently
            _record_signal(
                gate_name="review_gate",
                decision="allow",
                reason=f"{len(state['reviews'])} review agent(s) dispatched this session",
                reviewers=state["reviews"][:5],
            )
            return 0

        # No review agent — soft warning
        _record_signal(
            gate_name="review_gate",
            decision="nudge",
            reason="no review agent dispatched this session before bd close",
        )
        result = {
            "systemMessage": _WARN_NO_REVIEW,
        }
        json.dump(result, sys.stdout)
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
