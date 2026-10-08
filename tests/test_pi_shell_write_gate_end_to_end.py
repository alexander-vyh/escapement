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


def _ran(plugin: Path, env: dict, session: Session, repo: Path, command: str,
         call_id: str | None = None) -> dict:
    """Pi's tool_call, then bash runs `command`, then its tool_result.

    The tool_call runs the PreToolUse snapshot, so it is delivered before the
    change is on disk; the outcome returned is the tool_result's. `call_id`
    replaces the harness's `call-N` with a provider's own id shape.
    """
    arguments = {"command": command}
    call_event = session.tool_call("bash", arguments)
    result_event = session.tool_result("bash", arguments, "done")
    if call_id is not None:
        call_event["payload"]["toolCallId"] = result_event["payload"]["toolCallId"] = call_id
    (call,) = run(plugin, [call_event], env)
    assert not (call["result"] or {}).get("block"), call
    subprocess.run(["bash", "-c", command], cwd=repo, check=True)
    (outcome,) = run(plugin, [result_event], env)
    return outcome


def test_pi_openai_responses_call_ids_still_pair_the_halves(plugin, tmp_path):
    """Pi's openai-codex provider names calls `call_…|fc_…`; the gate must not go quiet."""
    repo = _project(tmp_path)
    outcome = _ran(plugin, pi_env(tmp_path), Session(repo), repo,
                   "python3 -c \"open('src/app.py','w').write('VALUE = 4\\n')\"",
                   call_id="call_Xy12AbC|fc_0123456789abcdef")
    assert "src/app.py" in appended_text(outcome["result"])


def test_pi_shell_write_without_tests_is_reported_in_the_result_once(plugin, tmp_path):
    repo = _project(tmp_path)
    (repo / "src" / "legacy.py").write_text("OLD = 1\n")  # another session's dirt
    session, env = Session(repo), pi_env(tmp_path)

    first = _ran(plugin, env, session, repo,
                 "python3 -c \"open('src/app.py','w').write('VALUE = 2\\n')\"")
    second = _ran(plugin, env, session, repo, "ls")

    assert first["result"]["content"][0]["text"] == "done"
    report = appended_text(first["result"])
    assert "TDD" in report and "src/app.py" in report
    assert "legacy.py" not in report, "dirt this session did not write is not its debt"
    assert "test-oracle-brief.md" in report
    assert second["result"] is None, "an unchanged debt is not repeated on every bash call"


def test_pi_shell_docs_write_is_silent(plugin, tmp_path):
    """Positive control: a docs change owes neither a test nor a brief."""
    repo = _project(tmp_path)
    outcome = _ran(plugin, pi_env(tmp_path), Session(repo), repo, "echo more >> docs/README.md")

    assert outcome["result"] is None
