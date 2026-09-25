"""review_gate on Pi, driven through the rendered extension.

Business outcome: a Pi agent that closes a bead (`bd close`) without having
dispatched a reviewer is told so before its next step, with the reviewers
Escapement ships for Pi named as the way forward. A reviewer dispatched through
pi-subagents (`subagent {agent: "adversarial-reviewer" | "test-quality-reviewer"}`)
satisfies the close, and an ordinary helper (`scout`) does not.

The gate is a soft gate on every host: Claude asks the user; Pi has no ask
(the extension enforces one as a block), so the finding reaches the model as a
steer message and the close itself runs. The only inputs are Pi events.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pi_extension_harness import Session, notices, pi_env, rendered_plugin, run

CLOSE = {"command": "bd close escapement-abcd --reason 'done'"}
NUDGE = "No review agent was dispatched"


@pytest.fixture(scope="module")
def plugin(tmp_path_factory):
    return rendered_plugin(tmp_path_factory)


@pytest.fixture
def env(tmp_path):
    """A `bd` that answers nothing: the close must not reach a real tracker,
    and the other Bash gates see an empty one."""
    shims = tmp_path / "bin"
    shims.mkdir()
    bd = shims / "bd"
    bd.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    bd.chmod(0o755)
    env = pi_env(tmp_path)
    env["PATH"] = f"{shims}:{env['PATH']}"
    return env


@pytest.fixture
def session(tmp_path):
    session = Session(tmp_path)
    yield session
    Path(f"/tmp/claude-review-gate/{session.id}.json").unlink(missing_ok=True)
    Path(f"/tmp/context_burn_{session.id}.json").unlink(missing_ok=True)


def test_pi_close_without_reviewer_reaches_the_model_without_blocking(plugin, env, session):
    (close,) = run(plugin, [session.tool_call("bash", CLOSE)], env)

    assert close["result"] is None, "the review nudge never blocks the close"
    steer = [item for item in close["sent"] if NUDGE in item["text"]]
    assert steer and steer[0]["options"] == {"deliverAs": "steer"}
    assert '{agent: "adversarial-reviewer"' in steer[0]["text"]
    assert "proceed" not in steer[0]["text"], "Pi has no ask for the user to answer"


@pytest.mark.parametrize("reviewer", ["adversarial-reviewer", "test-quality-reviewer"])
def test_pi_reviewer_subagent_satisfies_the_close(plugin, env, session, reviewer):
    # A blinded brief: no review words, so only the agent identifies the review.
    dispatch = session.tool_call("subagent", {"agent": reviewer, "task": "Check the diff in HEAD~1 against the spec."})
    close = session.tool_call("bash", CLOSE)
    dispatched, closed = run(plugin, [dispatch, close], env)

    assert dispatched["result"] is None
    assert closed["result"] is None
    assert NUDGE not in notices(closed)


def test_pi_non_reviewer_subagent_does_not_satisfy_the_close(plugin, env, session):
    dispatch = session.tool_call("subagent", {"agent": "scout", "task": "Map the config loader."})
    close = session.tool_call("bash", CLOSE)
    _, closed = run(plugin, [dispatch, close], env)

    assert NUDGE in notices(closed)


@pytest.mark.parametrize(
    "dispatch_input",
    [
        # pi-subagents' `task` is optional; the agent alone is the dispatch.
        {"agent": "adversarial-reviewer"},
        # The pattern pi-subagents recommends for reviews: children inside a
        # workflowScript, which the mapping reads from its `agent:` literals.
        {"async": True, "workflowScript": (
            "const r = await runs.all([{key: 'a', agent: 'scout', task: 'map'},"
            " {key: 'b', agent: \"test-quality-reviewer\", task: 'check HEAD~1'}]);\n"
            "return r;"
        )},
    ],
    ids=["taskless", "workflow-script"],
)
def test_pi_reviewer_dispatch_shapes_satisfy_the_close(plugin, env, session, dispatch_input):
    dispatch = session.tool_call("subagent", dispatch_input)
    close = session.tool_call("bash", CLOSE)
    _, closed = run(plugin, [dispatch, close], env)

    assert NUDGE not in notices(closed)


def test_pi_workflow_script_without_a_reviewer_does_not_satisfy_the_close(plugin, env, session):
    script = "return await runs.run('m', {agent: 'scout', task: 'map'});"
    dispatch = session.tool_call("subagent", {"workflowScript": script})
    close = session.tool_call("bash", CLOSE)
    _, closed = run(plugin, [dispatch, close], env)

    assert NUDGE in notices(closed)
