#!/usr/bin/env python3
"""PreToolUse hook: block direct Slack/email send tools; drafts are allowed.

A tool is a direct send when its name ends in `slack_send_message` or
`slack_schedule_message` after a `_` boundary (case-insensitive). Every host
names the same Slack MCP tool differently, and all of them match:

  Claude   mcp__plugin_slack_slack__slack_send_message
           mcp__claude_ai_Slack__slack_schedule_message
  Codex    mcp__slack__slack_send_message              (plugin/config server)
           mcp__codex_apps__slack_slack_send_message   (ChatGPT app)
  Pi       mcp__slack__slack_send_message              (mcp proxy, server + tool)
           mcp____slack_slack_send_message             (mcp proxy, prefixed tool only)
           slack_slack_send_message                    (direct tool, or an mcpScript
                                                        call naming it)

pi-mcp-adapter resolves a proxy call's tool name with `-` read as `_`, so
`slack-send-message` reaches the same tool; the name is judged the same way.

The drafts (`..._send_message_draft`) never match. The hook checks the name
itself instead of trusting its registration, so a broad host matcher can never
turn it into a draft blocker.

Gmail: the current Claude AI Gmail MCP has no send tool (create_draft is the
only write action). If a send tool is added, extend _DIRECT_SEND and the
registered matchers.

Exit codes:
  0 — allow (no output) or deny (permissionDecision JSON)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import NoReturn

# Shared signal capture per claude/rules/gate-design.md Rule 2.
sys.path.insert(0, str(Path(__file__).parent))
try:
    from _gate_signal import record as _record_signal
except ImportError:  # pragma: no cover
    def _record_signal(*_args, **_kwargs) -> None:
        return None
from _agent_dispatch import host as _host  # noqa: E402

_DIRECT_SEND = re.compile(r"(?:^|_)slack_(?:send|schedule)_message$", re.IGNORECASE)


def _draft_tool(tool_name: str) -> str:
    """The same server's draft tool: `..._send_message` -> `..._send_message_draft`."""
    return re.sub(r"(?i)(send|schedule)_message$", "send_message_draft", tool_name)


def _pi_draft_call(tool_name: str) -> str:
    """The Pi `mcp` proxy call for the draft. The extension names a proxy call
    `mcp__<server>__<tool>` (empty server when the call named none), and a
    direct or mcpScript call by its prefixed tool name, which the proxy also
    resolves."""
    server, tool = "", tool_name
    if tool_name.startswith("mcp__"):
        server, _, tool = tool_name[len("mcp__"):].partition("__")
    target = f'tool: "{_draft_tool(tool)}"'
    return f"mcp({{ server: \"{server}\", {target} }})" if server else f"mcp({{ {target} }})"


def deny(tool_name: str, on_pi: bool) -> NoReturn:
    # CANONICAL DENY CONTRACT: signal the block with a single mechanism — the
    # permissionDecision="deny" JSON document on stdout, exit 0. Exit 2 is the
    # mutually-exclusive legacy stderr-feedback path; emitting both is a
    # contradictory double-block. We use the JSON path, so this exits 0.
    draft_tool = _pi_draft_call(tool_name) if on_pi else _draft_tool(tool_name)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"Direct send is blocked: {tool_name}. "
                f"Use {draft_tool} instead so the message can be reviewed before sending."
            ),
        }
    }))
    sys.exit(0)


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # fail-open
    if not isinstance(data, dict):
        return 0

    tool_name = data.get("tool_name", "")
    if not isinstance(tool_name, str):
        return 0
    tool_name = tool_name.replace("-", "_")
    if not _DIRECT_SEND.search(tool_name):
        return 0
    _record_signal(
        gate_name="no_direct_send_guard",
        decision="deny",
        reason="direct Slack send redirected to draft",
        tool=tool_name,
    )
    deny(tool_name, _host(data) == "pi")
    return 0  # unreachable


if __name__ == "__main__":
    sys.exit(main())
