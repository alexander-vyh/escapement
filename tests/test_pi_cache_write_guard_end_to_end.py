"""cache_write_guard on Pi, driven through the rendered extension.

The session's weight comes from Pi's own per-turn usage on the branch, which
the extension writes out as the transcript the guard measures. The usage is
the shape Pi's OpenAI providers report: no cache writes, the new context as
uncached `input`. A guard that read only Claude's cache-write count would see
zero here and never fire on the provider Pi runs by default.
"""

from __future__ import annotations

import time

import pytest

from pi_extension_harness import Session, git_repo, pi_env, rendered_plugin, run

COMMAND = "bd show escapement-l4fv"


@pytest.fixture(scope="module")
def plugin(tmp_path_factory):
    return rendered_plugin(tmp_path_factory)


def _session_with_new_context(repo, tokens: int) -> Session:
    session = Session(repo)
    session.user("look into the flaky test")
    session.branch.append({
        "role": "assistant",
        "content": [{"type": "text", "text": "Reading the suite."}],
        "usage": {"input": tokens, "output": 900, "cacheRead": 0, "cacheWrite": 0, "totalTokens": tokens + 900},
        "stopReason": "stop",
        "timestamp": int(time.time() * 1000),
    })
    return session


def test_pi_status_op_in_a_heavy_session_is_blocked_toward_pi_print(plugin, tmp_path):
    repo = git_repo(tmp_path / "repo", {"README.md": "x\n"})
    session = _session_with_new_context(repo, 400_000)

    [outcome] = run(plugin, [session.tool_call("bash", {"command": COMMAND})], pi_env(tmp_path))

    result = outcome["result"]
    assert result and result["block"] is True, outcome
    assert "400k new tokens" in result["reason"]
    assert f"pi -p '{COMMAND}'" in result["reason"], "must name Pi's own lightweight runner"
    assert "cache-guard-waiver:" in result["reason"], "must name the inline waiver escape"


def test_pi_status_op_in_a_light_session_runs(plugin, tmp_path):
    repo = git_repo(tmp_path / "repo", {"README.md": "x\n"})
    session = _session_with_new_context(repo, 20_000)

    [outcome] = run(plugin, [session.tool_call("bash", {"command": COMMAND})], pi_env(tmp_path))

    assert outcome["result"] is None, outcome
