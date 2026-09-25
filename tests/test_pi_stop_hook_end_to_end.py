"""Drive the rendered Pi extension to the end of a run and see stop_hook act
on Pi: a run that changed code without declaring what the change is for is
continued with a follow-up user message, and that message's way forward is
made of commands the Pi package ships -- following it releases the stop.

The continued run may stop (stop_hook_active), and the user saying 'stop'
releases the session. The only inputs are Pi-shaped events.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from pi_extension_harness import Session, follow_ups, git_repo, pi_env, rendered_plugin, run

GATE = "Escapement stop gate"


@pytest.fixture(scope="module")
def plugin(tmp_path_factory) -> Path:
    return rendered_plugin(tmp_path_factory)


def _changed_code(tmp_path: Path) -> tuple[Path, Session]:
    """A session that wrote a source file in a repository and then paused.
    The repository tracks beads, so gate signal lands in its .beads/."""
    repo = git_repo(tmp_path / "project", {"src/app.py": "VALUE = 1\n", ".beads/.gitkeep": ""})
    session = Session(repo)
    session.user("make VALUE configurable")
    write = {"path": str(repo / "src" / "app.py"), "content": "VALUE = 2\n"}
    session.tool_call("write", write)
    (repo / "src" / "app.py").write_text(write["content"], encoding="utf-8")
    session.tool_result("write", write, "Wrote src/app.py")
    session.say("I changed VALUE; next I will wire the setting in.")
    return repo, session


def _gate_follow_ups(outcome: dict) -> list[dict]:
    return [item for item in follow_ups(outcome) if GATE in item["text"]]


def test_pi_undeclared_code_change_continues_the_run_once(plugin, tmp_path):
    repo, session = _changed_code(tmp_path)

    first, continued = run(plugin, [session.agent_end(), session.agent_end()], pi_env(tmp_path))

    (message,) = _gate_follow_ups(first)
    assert message["options"] == {"deliverAs": "followUp"}, "only a follow-up continues a finished Pi run"
    text = message["text"]
    assert "no_declaration" in text and "You are not done" in text
    assert "ScheduleWakeup" not in text and "~/.claude" not in text and "/.claude/" not in text
    # Every file the way forward names is one the installed Pi package carries.
    named = re.findall(r"(/\S+?(?:\.py|/verify))\b", text)
    assert {Path(path).name for path in named} == {"init_contract.py", "derive_contract.py", "verify"}
    for path in named:
        assert Path(path).is_file() and Path(path).is_relative_to(plugin), path
    assert "saying 'stop'" in text, "the block must name the user's release"

    assert _gate_follow_ups(continued) == [], "the continued run may stop: no loop"

    signal = [json.loads(line) for line in (repo / ".beads" / ".gate-signal.jsonl").read_text().splitlines()]
    assert {"gate": "continuation-harness", "decision": "block", "reason": "no_declaration"}.items() <= next(
        row for row in signal if row.get("gate") == "continuation-harness"
    ).items(), "the Pi stop decision must reach the half-life corpus"


def test_pi_following_the_block_releases_the_stop(plugin, tmp_path):
    repo, session = _changed_code(tmp_path)
    env = pi_env(tmp_path)
    (blocked,) = run(plugin, [session.agent_end()], env)
    (message,) = _gate_follow_ups(blocked)
    commands = re.findall(r"`([^`]+)`", message["text"])
    declare = next(command for command in commands if "init_contract.py" in command)
    verify = next(command for command in commands if command.endswith("verify"))
    declare = declare.replace("<what a user can observe>", "VALUE reads 2").replace(
        "<command whose exit 0 proves it>", "grep -q 'VALUE = 2' src/app.py"
    )

    for command in (declare, verify):
        done = subprocess.run(["bash", "-c", command], cwd=repo, env=env, capture_output=True, text=True)
        assert done.returncode == 0, (command, done.stdout, done.stderr)

    (released,) = run(plugin, [session.agent_end()], env)
    assert _gate_follow_ups(released) == []


def test_pi_user_stop_releases_the_session(plugin, tmp_path):
    """Negative control: the same undeclared change, but the user said stop."""
    _repo, session = _changed_code(tmp_path)
    session.user("stop")
    session.say("Stopping here.")

    (outcome,) = run(plugin, [session.agent_end()], pi_env(tmp_path))

    assert _gate_follow_ups(outcome) == []
