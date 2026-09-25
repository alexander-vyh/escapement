"""bypass_guard on Pi, driven through the rendered extension with Pi's bash call."""

from __future__ import annotations

import pytest

from pi_extension_harness import Session, git_repo, pi_env, rendered_plugin, run


@pytest.fixture(scope="module")
def plugin(tmp_path_factory):
    return rendered_plugin(tmp_path_factory)


def _commit(plugin, tmp_path, command: str) -> dict:
    repo = git_repo(tmp_path / "repo", {"README.md": "x\n"})
    [outcome] = run(plugin, [Session(repo).tool_call("bash", {"command": command})], pi_env(tmp_path))
    return outcome


def test_pi_no_verify_commit_is_blocked_with_the_waiver_escape(plugin, tmp_path):
    outcome = _commit(plugin, tmp_path, 'git commit --no-verify -m "wip"')

    result = outcome["result"]
    assert result and result["block"] is True, outcome
    assert "--no-verify" in result["reason"]
    assert 'BYPASS_WAIVER="' in result["reason"], "the block must carry its waiver escape"


def test_pi_no_verify_quoted_in_a_commit_message_runs(plugin, tmp_path):
    outcome = _commit(plugin, tmp_path, 'git commit -m "explain why --no-verify is banned"')

    assert outcome["result"] is None, outcome
