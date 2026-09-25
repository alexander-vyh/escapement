"""Drive the rendered Pi extension through Pi writes and edits of
implementation code, and see tdd-gate ask its question the only way Pi can.

Pi runs a PreToolUse `ask` as a block, so "say 'proceed'" would be a dead
end. The gate blocks once per file per session instead, and the block tells
the model that making the same write or edit again is the way forward.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pi_extension_harness import Session, git_repo, pi_env, rendered_plugin, run


@pytest.fixture(scope="module")
def plugin(tmp_path_factory) -> Path:
    return rendered_plugin(tmp_path_factory)


def _project(tmp_path: Path) -> Path:
    """A code project with no test changes in its working tree."""
    return git_repo(tmp_path / "project", {
        "pyproject.toml": "[project]\nname = 'demo'\n",
        "src/app.py": "VALUE = 1\n",
    })


def test_pi_impl_write_without_tests_is_blocked_once_then_the_retry_passes(plugin, tmp_path):
    repo = _project(tmp_path)
    session = Session(repo)
    write = {"path": str(repo / "src" / "app.py"), "content": "VALUE = 2\n"}

    first, retry = run(plugin, [session.tool_call("write", write), session.tool_call("write", write)], pi_env(tmp_path))

    assert first["result"]["block"] is True
    reason = first["result"]["reason"]
    assert "TDD" in reason and "src/app.py" in reason
    assert "make the same write or edit again" in reason, "the block must name its escape"
    assert "proceed" not in reason, "nobody on Pi can answer a prompt"
    assert retry["result"] is None, "the same write again is the override"


def test_pi_impl_edit_without_tests_is_blocked(plugin, tmp_path):
    repo = _project(tmp_path)
    session = Session(repo)
    edit = {"path": "src/app.py", "edits": [{"oldText": "VALUE = 1", "newText": "VALUE = 3"}]}

    (outcome,) = run(plugin, [session.tool_call("edit", edit)], pi_env(tmp_path))

    assert outcome["result"]["block"] is True
    assert "make the same write or edit again" in outcome["result"]["reason"]


def test_pi_test_write_is_not_blocked(plugin, tmp_path):
    """Negative control: writing the test first is exactly what TDD asks."""
    repo = _project(tmp_path)
    session = Session(repo)
    write = {"path": str(repo / "tests" / "test_app.py"), "content": "def test_value():\n    pass\n"}

    (outcome,) = run(plugin, [session.tool_call("write", write)], pi_env(tmp_path))

    assert outcome["result"] is None
