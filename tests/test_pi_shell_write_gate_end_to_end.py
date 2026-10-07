"""Drive the rendered Pi extension through a Pi bash call that writes
implementation code, and see shell_write_gate's report reach the model in the
tool result it reads -- once, not after every later bash call.

Nothing here names the written file in a way a command parser would catch:
the bash command runs a python one-liner, and the gate reads the working tree.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from pi_extension_harness import Session, appended_text, git_repo, pi_env, rendered_plugin, run


@pytest.fixture(scope="module")
def plugin(tmp_path_factory) -> Path:
    return rendered_plugin(tmp_path_factory)


def _project(tmp_path: Path) -> Path:
    return git_repo(tmp_path / "project", {
        "pyproject.toml": "[project]\nname = 'demo'\n",
        "src/app.py": "VALUE = 1\n",
        "docs/README.md": "demo\n",
    })


def _ran(session: Session, repo: Path, command: str) -> dict:
    """Pi's bash ran `command`: the change is on disk before tool_result."""
    subprocess.run(["bash", "-c", command], cwd=repo, check=True)
    arguments = {"command": command}
    session.tool_call("bash", arguments)
    return session.tool_result("bash", arguments, "done")


def test_pi_shell_write_without_tests_is_reported_in_the_result_once(plugin, tmp_path):
    repo = _project(tmp_path)
    session = Session(repo)
    write = _ran(session, repo, "python3 -c \"open('src/app.py','w').write('VALUE = 2\\n')\"")
    later = _ran(session, repo, "ls")

    first, second = run(plugin, [write, later], pi_env(tmp_path))

    assert first["result"]["content"][0]["text"] == "done"
    report = appended_text(first["result"])
    assert "TDD" in report and "src/app.py" in report
    assert "test-oracle-brief.md" in report
    assert second["result"] is None, "an unchanged debt is not repeated on every bash call"


def test_pi_shell_docs_write_is_silent(plugin, tmp_path):
    """Positive control: a docs change owes neither a test nor a brief."""
    repo = _project(tmp_path)
    session = Session(repo)

    (outcome,) = run(plugin, [_ran(session, repo, "echo more >> docs/README.md")], pi_env(tmp_path))

    assert outcome["result"] is None
