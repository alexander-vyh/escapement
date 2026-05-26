#!/usr/bin/env python3
"""Claude Code hook: block direct Slack/email send tools; drafts are allowed.

Registered as PreToolUse matchers for each blocked tool name. By the time
this hook runs, the tool is already on the block list — so the hook always
denies and suggests the draft alternative.

Blocked tools (plugin MCP):
  mcp__plugin_slack_slack__slack_send_message       — use slack_send_message_draft
  mcp__plugin_slack_slack__slack_schedule_message   — use slack_send_message_draft

Blocked tools (legacy claude.ai MCP):
  mcp__claude_ai_Slack__slack_send_message          — use slack_send_message_draft
  mcp__claude_ai_Slack__slack_schedule_message      — use slack_send_message_draft

Allowed (no hook registered):
  mcp__plugin_slack_slack__slack_send_message_draft
  mcp__claude_ai_Slack__slack_send_message_draft

Gmail: the current Claude AI Gmail MCP has no send tool (create_draft is the
only write action). If a send tool is added, add its name here and a matcher
in settings.template.json.

Exit codes:
  0 — never reached (always denies)
  2 — deny with JSON explanation
"""

import json
import sys
from typing import NoReturn

_DRAFT_HINT: dict[str, str] = {
    "mcp__plugin_slack_slack__slack_send_message": (
        "mcp__plugin_slack_slack__slack_send_message_draft"
    ),
    "mcp__plugin_slack_slack__slack_schedule_message": (
        "mcp__plugin_slack_slack__slack_send_message_draft"
    ),
    "mcp__claude_ai_Slack__slack_send_message": (
        "mcp__claude_ai_Slack__slack_send_message_draft"
    ),
    "mcp__claude_ai_Slack__slack_schedule_message": (
        "mcp__claude_ai_Slack__slack_send_message_draft"
    ),
}


def deny(tool_name: str) -> NoReturn:
    draft_tool = _DRAFT_HINT.get(tool_name, "the draft equivalent")
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
    sys.exit(2)


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # fail-open

    tool_name = data.get("tool_name", "")
    deny(tool_name)
    return 0  # unreachable


if __name__ == "__main__":
    sys.exit(main())
