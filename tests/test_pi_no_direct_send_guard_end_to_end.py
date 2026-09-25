"""no_direct_send_guard on Pi, driven through the rendered extension.

pi-mcp-adapter reaches a Slack server's send tool four ways: its `mcp` proxy
tool by `server` + tool, or by the server-prefixed tool name alone (read with
`-` as `_`); a direct tool registered under that prefixed name (`directTools`);
and an `mcpScript` whose JavaScript calls it. Each reaches the same send, so
each must be blocked toward the draft.
"""

from __future__ import annotations

import pytest

from pi_extension_harness import Session, git_repo, pi_env, rendered_plugin, run

ARGS = {"channel_id": "C123", "message": "shipping now"}


@pytest.fixture(scope="module")
def plugin(tmp_path_factory):
    return rendered_plugin(tmp_path_factory)


def test_pi_slack_send_is_blocked_toward_the_draft(plugin, tmp_path):
    session = Session(git_repo(tmp_path / "repo", {"README.md": "x\n"}))
    outcomes = run(plugin, [
        session.tool_call("mcp", {"server": "slack", "tool": "slack_send_message", "args": ARGS}),
        session.tool_call("mcp", {"tool": "slack_slack_schedule_message", "args": ARGS}),
        session.tool_call("mcp", {"tool": "slack-slack-send-message", "args": ARGS}),
    ], pi_env(tmp_path))

    by_server, prefixed, hyphenated = (outcome["result"] for outcome in outcomes)
    for result in (by_server, prefixed, hyphenated):
        assert result and result["block"] is True, outcomes
        assert "Direct send is blocked" in result["reason"]
    assert 'mcp({ server: "slack", tool: "slack_send_message_draft" })' in by_server["reason"]
    assert 'mcp({ tool: "slack_slack_send_message_draft" })' in prefixed["reason"]
    assert 'mcp({ tool: "slack_slack_send_message_draft" })' in hyphenated["reason"]


def test_pi_slack_draft_runs(plugin, tmp_path):
    session = Session(git_repo(tmp_path / "repo", {"README.md": "x\n"}))
    [outcome] = run(plugin, [
        session.tool_call("mcp", {"server": "slack", "tool": "slack_send_message_draft", "args": ARGS}),
    ], pi_env(tmp_path))

    assert outcome["result"] is None, outcome


def test_pi_direct_and_scripted_slack_sends_are_blocked(plugin, tmp_path):
    session = Session(git_repo(tmp_path / "repo", {"README.md": "x\n"}))
    outcomes = run(plugin, [
        session.tool_call("slack_slack_send_message", ARGS),
        session.tool_call("mcpScript", {"code": (
            'const history = await tools.slack_slack_read_channel({ channel_id: "C123" });\n'
            'return tools.call("slack_slack_send_message", { channel_id: "C123", message: "hi" });'
        )}),
        session.tool_call("mcpScript", {"code": 'await tools["slack_slack_schedule_message"]({ post_at: 1 });'}),
    ], pi_env(tmp_path))

    for outcome in outcomes:
        result = outcome["result"]
        assert result and result["block"] is True, outcomes
        assert 'mcp({ tool: "slack_slack_send_message_draft" })' in result["reason"]


def test_pi_unrelated_extension_tools_run(plugin, tmp_path):
    session = Session(git_repo(tmp_path / "repo", {"README.md": "x\n"}))
    outcomes = run(plugin, [
        session.tool_call("websearch", {"query": "slack_send_message api"}),
        session.tool_call("slack_slack_send_message_draft", ARGS),
        session.tool_call("mcpScript", {"code": 'return tools.slack_slack_read_channel({ channel_id: "C123" });'}),
    ], pi_env(tmp_path))

    assert [outcome["result"] for outcome in outcomes] == [None, None, None], outcomes
