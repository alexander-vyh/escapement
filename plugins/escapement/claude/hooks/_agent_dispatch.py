"""Which host a hook runs under, and what an agent dispatch looks like there.

One owner, because every agent-dispatch gate (enforce_named_agents, review_gate,
context_burn_detector) has to recognise the same dispatch on every host, and a
wrong guess is silent: the gate fires on nothing.

Captured on codex-cli 0.156.1, not read from docs
(claude/hooks/tests/fixtures/codex_agent_mcp_stop_payloads.json):

  dispatch   Codex names the tool `collaborationspawn_agent` (older builds:
             `spawn_agent`). Its input is `{task_name, message}`, or
             `{message, agent_type, ...}` on the older tool. `message` is an
             opaque encrypted blob on the current tool, so the prompt cannot be
             read. PreToolUse matchers are anchored, and neither `Agent` nor
             `spawn_agent` matched the captured name; CODEX_SPAWN_MATCHER does.

  subagent   A tool call made inside a Codex subagent carries `agent_id` and
             `agent_type`. The session_id is the parent's.

  ask        A PreToolUse `permissionDecision: "ask"` does not prompt anyone on
             Codex. Codex marks the hook run failed, the tool runs, and the
             hook's additionalContext is dropped. So a gate that asks on Claude
             must speak differently on other hosts.

Claude's `Agent` input already has this shape, and the Pi extension translates
pi-subagents calls into it, so only Codex needs a mapping.
"""

from __future__ import annotations

import os
import re

# Registered as the Codex PreToolUse matcher for every agent-dispatch gate.
CODEX_SPAWN_MATCHER = "(collaboration)?spawn_agent"
_CODEX_SPAWN_TOOL = re.compile(CODEX_SPAWN_MATCHER)
HOSTS = ("claude", "codex", "pi")


def host(payload: object) -> str:
    """The host this hook is running under.

    `ESCAPEMENT_HOST` wins when set (the Pi extension sets it for every gate).
    Otherwise a `turn_id` marks Codex: Codex documents it as a Codex-only
    extension on every turn-scoped event, and Claude does not send it.
    """
    declared = os.environ.get("ESCAPEMENT_HOST", "").strip().lower()
    if declared in HOSTS:
        return declared
    if isinstance(payload, dict) and payload.get("turn_id"):
        return "codex"
    return "claude"


def _readable(message: object) -> str:
    """The prompt text, or "" for Codex's encrypted message blob.

    The blob is one unbroken token; a prompt a gate could learn from has spaces.
    """
    if not isinstance(message, str) or not any(ch.isspace() for ch in message.strip()):
        return ""
    return message


def agent_dispatch(payload: object) -> dict | None:
    """Claude-shaped `Agent` input for an agent dispatch on any host, else None.

    Keys: name, subagent_type, description, prompt, plus any waiver field the
    caller supplied. On Codex, `name` is the task_name, or the agent_type when
    there is no task name: either one identifies the spawned agent.
    """
    if not isinstance(payload, dict):
        return None
    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_name, str) or not isinstance(tool_input, dict):
        return None
    if tool_name == "Agent":
        return tool_input
    if not _CODEX_SPAWN_TOOL.fullmatch(tool_name):
        return None
    task_name = str(tool_input.get("task_name") or "").strip()
    agent_type = str(tool_input.get("agent_type") or "").strip()
    mapped = {
        key: value
        for key, value in tool_input.items()
        if key not in {"task_name", "agent_type", "message", "items"}
    }
    mapped.update(
        name=task_name or agent_type,
        subagent_type=agent_type,
        # Codex task names are snake_case; spaced, they read as words to
        # word-boundary checks ("test_quality_reviewer" names a reviewer).
        description=re.sub(r"[_\-/]+", " ", task_name).strip(),
        prompt=_readable(tool_input.get("message")),
    )
    return mapped


def is_subagent_call(payload: object) -> bool:
    """True for a tool call made inside a subagent (Codex sends its agent_id)."""
    return isinstance(payload, dict) and bool(payload.get("agent_id"))
