"""Drive the rendered Pi extension through a session start in a fresh
repository and see project_bootstrap act on Pi: the project is wired for Pi
(OpenSpec asked for its `pi` tools, the conservative outcome policy written),
and the bootstrap report with Pi's agent-dispatch wording is in the system
prompt of the turn that follows.

`bd` and `openspec` are failing shims on PATH, so nothing initialises a real
tool in the temp repository; they record how they were called.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from pi_extension_harness import Session, git_repo, pi_env, rendered_plugin, run

REPORT = "# Project Bootstrap Report"
DISPATCH = "## Agent Dispatch Rules"


@pytest.fixture(scope="module")
def plugin(tmp_path_factory) -> Path:
    return rendered_plugin(tmp_path_factory)


def _env_with_failing_tools(tmp_path: Path) -> tuple[dict[str, str], Path]:
    shims = tmp_path / "shims"
    shims.mkdir()
    log = tmp_path / "tool-calls.log"
    for tool in ("bd", "openspec"):
        shim = shims / tool
        shim.write_text(f'#!/bin/sh\necho "{tool} $*" >> "{log}"\nexit 1\n', encoding="utf-8")
        shim.chmod(0o755)
    env = pi_env(tmp_path)
    env["PATH"] = f"{shims}{os.pathsep}{env['PATH']}"
    return env, log


def _prompt_after_start(plugin: Path, cwd: Path, env: dict[str, str]) -> str:
    session = Session(cwd)
    _start, turn = run(plugin, [session.start(), session.prompt("hello")], env)
    return turn["result"]["systemPrompt"]


def test_pi_session_start_bootstraps_the_project_for_pi(plugin, tmp_path):
    repo = git_repo(tmp_path / "project", {"README.md": "demo\n"})
    env, log = _env_with_failing_tools(tmp_path)

    prompt = _prompt_after_start(plugin, repo, env)

    assert REPORT in prompt and "Project: project" in prompt
    calls = log.read_text(encoding="utf-8").splitlines()
    assert "openspec init --tools pi ." in calls
    assert not any(call.startswith("bd init") for call in calls), "bd is unreachable, so it is never initialised"
    assert "openspec init --tools pi" in prompt, "a failed init names the Pi repair"
    assert "bd/dolt not reachable" in prompt
    assert json.loads((repo / ".escapement" / "repo.json").read_text(encoding="utf-8")) == {
        "intended_outcome": "pr-opened",
        "auto_merge_on_green": False,
    }
    assert "No AGENTS.md found" in prompt
    # The report, through its dispatch paragraph, is worded for Pi: no Claude
    # team tools, no pointer to the Claude-only continuation-harness rule.
    start = prompt.index(REPORT)
    report = prompt[start:prompt.index("\n\n", prompt.index(DISPATCH, start))]
    assert "subagent tool" in report
    assert "TeamCreate" not in report and "continuation-harness.md" not in report


def test_pi_session_start_outside_a_repository_adds_no_bootstrap(plugin, tmp_path):
    """Negative control: a directory that is not a git repository is left alone."""
    plain = tmp_path / "plain"
    plain.mkdir()
    env, log = _env_with_failing_tools(tmp_path)

    prompt = _prompt_after_start(plugin, plain, env)

    assert REPORT not in prompt and DISPATCH not in prompt
    assert not log.exists(), "no tool is touched outside a repository"
    assert not (plain / ".escapement").exists()
