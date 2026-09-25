#!/usr/bin/env python3
"""Agent-dispatch hook: soft gate on bd close — warns if no review agent was dispatched.

Dual-purpose PreToolUse hook:
  - On agent dispatch (Claude `Agent`, Codex spawn_agent, Pi's translated
    `Agent`): records it in a per-session state file under /tmp/ when it is a
    review (see _is_review_agent)
  - On Bash calls: checks if the command is `bd close` or `bd update --status closed`
    and warns if no review agent was recorded for this session

This is advisory — it never denies. On Claude it asks the user to confirm the
close. Codex has no working ask (a PreToolUse "ask" fails the hook run and its
context is dropped) and Pi enforces ask as a block, so on those hosts the
same finding reaches the model as non-blocking context.

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

from _agent_dispatch import agent_dispatch, host as _host  # noqa: E402
from _host_output import advisory  # noqa: E402

_STATE_DIR = Path("/tmp/claude-review-gate")

# Agent types that structurally count as review agents. A dispatch with one
# of these subagent_types satisfies the gate even when the prompt is blinded
# (contains no "review" words) — which is the common case for disciplined
# blinded-review workflows.
_REVIEWER_SUBAGENT_TYPES = {
    "adversarial-reviewer",
    "code-reviewer",
    "test-quality-reviewer",
}

# Word-boundary pattern matching the review-word family (review, reviews,
# reviewed, reviewer, reviewers, reviewing) but NOT false-positive substrings
# like "reviewable", "preview", or "previewer".
_REVIEW_WORD_RE = re.compile(r"\breview(?:s|ed|er|ers|ing)?\b", re.IGNORECASE)

# Word-boundary anchored detection of `bd close`. The leading \b prevents
# matching when "bd" is the tail of a longer token (e.g. "mybd close",
# "subd close") — those are not the beads CLI. The boundary still matches
# "bd close" at the start of a string or after a shell separator like ";".
_BD_CLOSE_RE = re.compile(r"\bbd\s+close\b")
_BD_UPDATE_CLOSED_RE = re.compile(r"\bbd\s+update\s+.*--status[=\s]+closed\b")


def _state_file(session_id: str) -> Path:
    """Return the state file path for a given session."""
    return _STATE_DIR / f"{session_id}.json"


def _read_state(session_id: str) -> list:
    """Read the list of review-agent names recorded for a session.

    Returns a list of reviewer names (possibly empty). Defends against state
    files that are valid JSON but not the expected shape: a dict missing the
    "reviews" key, a null literal, or a top-level array all return []
    rather than raising KeyError/TypeError.
    """
    sf = _state_file(session_id)
    if not sf.exists():
        return []
    try:
        parsed = json.loads(sf.read_text())
    except (json.JSONDecodeError, OSError):
        return []
    if isinstance(parsed, dict):
        reviews = parsed.get("reviews", [])
        return reviews if isinstance(reviews, list) else []
    return []


def _write_state(session_id: str, reviews: list) -> None:
    """Persist the list of review-agent names for a session."""
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        _state_file(session_id).write_text(json.dumps({"reviews": reviews}))
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
    if _BD_CLOSE_RE.search(command):
        return True
    if _BD_UPDATE_CLOSED_RE.search(command):
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

# Concise remedy surfaced as the ask-decision reason. Names the concrete
# escape path (dispatch a reviewer subagent, or say 'proceed') so the gate
# is actionable rather than a bare prohibition (gate-design.md Rule 1).
_ASK_REASON = (
    "No review agent was dispatched before this close. Dispatch a "
    "code-reviewer or adversarial-reviewer subagent first, or say "
    "'proceed' to close without review."
)

# How to dispatch a reviewer, in the words of the host that will read it.
_REVIEW_DISPATCH = {
    "codex": 'spawn_agent with a task_name that names the review, e.g. task_name="code_reviewer"',
    "pi": (
        'the subagent tool and one of the reviewers Escapement ships for Pi, e.g. '
        '{agent: "adversarial-reviewer", task: "..."} or '
        '{agent: "test-quality-reviewer", task: "..."}'
    ),
}

_NUDGE_NO_REVIEW = (
    "No review agent was dispatched in this session before this close. Review "
    "catches drift between spec and implementation, oracle downgrades and "
    "missed regressions that the implementer's own context hides. Dispatch one "
    "first with {dispatch}; it counts when its name, task or type says review "
    "(reviewer, review, code-reviewer, adversarial-reviewer, "
    "test-quality-reviewer). This notice does not block the close: if the work "
    "was already reviewed or needs none, go ahead."
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
    dispatch = agent_dispatch(data)
    if dispatch is not None:
        if _is_review_agent(dispatch):
            reviews = _read_state(session_id)
            agent_name = dispatch.get("name") or "unknown"
            reviews.append(agent_name)
            _write_state(session_id, reviews)
        return 0

    # --- Bash gating path ---
    if tool_name == "Bash":
        command = tool_input.get("command", "")
        if not _is_close_command(command):
            return 0

        reviews = _read_state(session_id)
        if reviews:
            # Review agent was dispatched — allow silently
            _record_signal(
                gate_name="review_gate",
                decision="allow",
                reason=f"{len(reviews)} review agent(s) dispatched this session",
                reviewers=reviews[:5],
            )
            return 0

        # No review agent — surface it before closing. This is a soft gate: it
        # never denies. Claude asks the user to confirm; other hosts get the
        # same finding as model context (see the module docstring).
        #
        # CANONICAL DECISION CONTRACT: the decision is signaled with a single
        # mechanism — one permissionDecision JSON document on stdout, exit 0.
        # Exit 2 is the mutually-exclusive legacy stderr-feedback path; emitting
        # both the JSON decision *and* a non-zero exit is a contradictory
        # double-signal. This advisory gate uses the same single-mechanism
        # JSON-on-stdout-plus-exit-0 contract as the hard-deny gates.
        host = _host(data)
        _record_signal(
            gate_name="review_gate",
            decision="nudge",
            reason="no review agent dispatched this session before bd close",
            host=host,
        )
        if host != "claude":
            json.dump(
                advisory(_NUDGE_NO_REVIEW.format(dispatch=_REVIEW_DISPATCH[host])),
                sys.stdout,
            )
            return 0
        result = {
            "systemMessage": _WARN_NO_REVIEW,
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": _ASK_REASON,
                "additionalContext": _WARN_NO_REVIEW,
            },
        }
        json.dump(result, sys.stdout)
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
