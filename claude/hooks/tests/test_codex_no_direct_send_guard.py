"""Codex: no_direct_send_guard stops a direct Slack send and points at the draft.

Business outcome
----------------
A Codex agent cannot post to Slack without a human reviewing the message; it
can still write the draft.

Independent source of truth
---------------------------
Captured on codex-cli 0.156.1 (fixtures/codex_agent_mcp_stop_payloads.json): an
MCP server named `slack` surfaces its tool to PreToolUse as
`mcp__slack__slack_send_message`; the registered matcher fired on it, a deny
blocked the call before the server saw it (the control run without the deny
reached the server). Live Codex rollouts name the ChatGPT-app Slack tools
`mcp__codex_apps__slack_slack_send_message` and `..._send_message_draft`.

Rejects
-------
- a matcher that misses either Codex naming, or catches the draft;
- a hook that denies whatever it is registered on (a broad matcher would then
  block drafts).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HOOK = ROOT / "claude" / "hooks" / "no_direct_send_guard.py"
SEND = json.loads(
    (Path(__file__).parent / "fixtures" / "codex_agent_mcp_stop_payloads.json").read_text()
)["payloads"]["slack_send_pretooluse"]
MANIFEST = json.loads((ROOT / "agent-surfaces" / "manifest.json").read_text())


def _codex_matcher() -> str:
    hook = next(h for h in MANIFEST["hooks"] if h["id"] == "no_direct_send_guard")
    [event] = hook["hosts"]["codex"]["events"]
    return event["matcher"]


def _run(tool_name: str, tmp_path: Path) -> dict | None:
    result = subprocess.run(
        [sys.executable, "-B", str(HOOK)],
        input=json.dumps({**SEND, "tool_name": tool_name, "cwd": str(tmp_path)}),
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "GATE_SIGNAL_FALLBACK_DIR": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout.strip()
    return json.loads(out) if out else None


def test_codex_matcher_selects_send_tools_and_skips_drafts():
    matcher = _codex_matcher()
    for send in (
        SEND["tool_name"],
        "mcp__codex_apps__slack_slack_send_message",
        "mcp__codex_apps__slack_slack_schedule_message",
    ):
        assert re.fullmatch(matcher, send), send
    for other in (
        "mcp__slack__slack_send_message_draft",
        "mcp__codex_apps__slack_slack_send_message_draft",
        "mcp__codex_apps__slack_slack_read_channel",
    ):
        assert not re.fullmatch(matcher, other), other


def test_codex_captured_send_is_denied_toward_the_draft(tmp_path):
    out = _run(SEND["tool_name"], tmp_path)
    decision = out["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    assert "mcp__slack__slack_send_message_draft" in decision["permissionDecisionReason"]


def test_codex_schedule_is_redirected_to_the_same_servers_draft(tmp_path):
    out = _run("mcp__codex_apps__slack_slack_schedule_message", tmp_path)
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert "mcp__codex_apps__slack_slack_send_message_draft" in reason


def test_codex_draft_is_allowed(tmp_path):
    assert _run("mcp__slack__slack_send_message_draft", tmp_path) is None
