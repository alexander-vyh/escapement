"""enforce_named_agents on Pi, driven through the rendered extension.

Business outcome: a Pi agent that starts a pi-subagents child with a task but
no `agent` is stopped, and told the one change that fixes it -- set `agent` on
the subagent call. A child that names its agent runs untouched, and a
management action (`{action: "list"}`) dispatches nothing, so it is not judged.

Source of truth: pi-subagents' `subagent` schema -- `{agent, task}` runs one
child and "task requires agent"; `action` is management only. The only inputs
here are Pi tool_call events; nothing imports the hook.
"""

from __future__ import annotations

import pytest

from pi_extension_harness import Session, notices, pi_env, rendered_plugin, run


@pytest.fixture(scope="module")
def plugin(tmp_path_factory):
    return rendered_plugin(tmp_path_factory)


def _dispatch(plugin, tmp_path, arguments: dict) -> dict:
    session = Session(tmp_path)
    (outcome,) = run(plugin, [session.tool_call("subagent", arguments)], pi_env(tmp_path))
    return outcome


def test_pi_subagent_without_agent_is_blocked_with_the_repair(plugin, tmp_path):
    outcome = _dispatch(plugin, tmp_path, {"task": "Find where the config loader reads env vars"})

    result = outcome["result"]
    assert result and result["block"] is True
    reason = result["reason"]
    assert "SUBAGENT BLOCKED" in reason
    # The repair is Pi's: set `agent` on the subagent call, not Claude's Agent(name=...).
    assert '{agent: "scout", task: "..."}' in reason
    assert "Agent(name=" not in reason
    assert "spawn_agent" not in reason


def test_pi_subagent_with_agent_is_allowed(plugin, tmp_path):
    outcome = _dispatch(
        plugin, tmp_path, {"agent": "scout", "task": "Find where the config loader reads env vars"}
    )

    assert outcome["result"] is None
    assert "BLOCKED" not in notices(outcome)


def test_pi_management_action_is_not_judged_as_a_dispatch(plugin, tmp_path):
    outcome = _dispatch(plugin, tmp_path, {"action": "list"})

    assert outcome["result"] is None
    assert outcome["sent"] == []
