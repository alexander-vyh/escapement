"""Drive the rendered Pi extension through Pi's tool_result for a code write,
and see the reminder to run the project's tests reach the model in the tool
result it reads -- once per cooldown, not after every write.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pi_extension_harness import Session, appended_text, git_repo, pi_env, rendered_plugin, run


@pytest.fixture(scope="module")
def plugin(tmp_path_factory) -> Path:
    return rendered_plugin(tmp_path_factory)


def _project(tmp_path: Path) -> Path:
    """A Python project with pytest infrastructure."""
    return git_repo(tmp_path / "project", {
        "pyproject.toml": "[project]\nname = 'demo'\n",
        "src/app.py": "VALUE = 1\n",
        "tests/test_app.py": "def test_value():\n    pass\n",
        "README.md": "demo\n",
    })


def _written(session: Session, tool: str, arguments: dict) -> dict:
    session.tool_call(tool, arguments)
    return session.tool_result(tool, arguments, "Wrote the file.")


def test_pi_code_write_gets_test_reminder_in_result_once_per_cooldown(plugin, tmp_path):
    repo = _project(tmp_path)
    session = Session(repo)
    write = {"path": str(repo / "src" / "app.py"), "content": "VALUE = 2\n"}
    edit = {"path": "src/app.py", "edits": [{"oldText": "VALUE = 2", "newText": "VALUE = 3"}]}

    first, second = run(plugin, [_written(session, "write", write), _written(session, "edit", edit)], pi_env(tmp_path))

    assert first["result"]["content"][0]["text"] == "Wrote the file."
    reminder = appended_text(first["result"])
    assert "run tests" in reminder and "`pytest`" in reminder
    assert second["result"] is None, "the reminder repeats only after its cooldown"


def test_pi_docs_write_gets_no_test_reminder(plugin, tmp_path):
    """Negative control: a docs change gives nothing to test."""
    repo = _project(tmp_path)
    session = Session(repo)

    (outcome,) = run(plugin, [_written(session, "write", {"path": str(repo / "README.md"), "content": "more\n"})], pi_env(tmp_path))

    assert outcome["result"] is None
