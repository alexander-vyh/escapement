"""validate_no_shirking on Pi, driven through the rendered extension.

Pi's agent_end is the Stop: a block continues the run with the gate's reason as
a follow-up user message. At a commit, the gate reads what the session said
from the Claude-shaped transcript the extension writes from Pi's branch.
"""

from __future__ import annotations

import pytest

from pi_extension_harness import Session, follow_ups, git_repo, pi_env, rendered_plugin, run

SHIRKING = "The remaining failure in test_parser is a pre-existing failure, not related to my changes."
OWNED = "test_parser failed on the empty-line case; I fixed the tokenizer and the whole suite now passes."
SIGNATURE = "OUTCOME OWNERSHIP VIOLATION"


@pytest.fixture(scope="module")
def plugin(tmp_path_factory):
    return rendered_plugin(tmp_path_factory)


def _session(tmp_path, final: str) -> Session:
    session = Session(git_repo(tmp_path / "repo", {"README.md": "x\n"}))
    session.user("fix the parser tests")
    session.say(final)
    return session


def test_pi_stop_after_shirking_continues_the_run(plugin, tmp_path):
    session = _session(tmp_path, SHIRKING)

    first, second = run(plugin, [session.agent_end(), session.agent_end()], pi_env(tmp_path))

    [continued] = [item for item in follow_ups(first) if SIGNATURE in item["text"]]
    assert continued["options"] == {"deliverAs": "followUp"}
    assert "pre-existing failure" in continued["text"]
    assert '"proceed"' in continued["text"], "the block must name its release"
    assert not any(SIGNATURE in item["text"] for item in follow_ups(second)), (
        "the re-entered stop carries stop_hook_active and must let the session go"
    )


def test_pi_commit_after_shirking_is_blocked(plugin, tmp_path):
    session = _session(tmp_path, SHIRKING)

    [outcome] = run(plugin, [session.tool_call("bash", {"command": 'git commit -am "done"'})], pi_env(tmp_path))

    result = outcome["result"]
    assert result and result["block"] is True, outcome
    assert SIGNATURE in result["reason"]
    assert "FIX THE FAILURES NOW" in result["reason"]


def test_pi_owned_final_message_stops_cleanly(plugin, tmp_path):
    session = _session(tmp_path, OWNED)

    [outcome] = run(plugin, [session.agent_end()], pi_env(tmp_path))

    assert not any(SIGNATURE in item["text"] for item in outcome["sent"]), outcome
