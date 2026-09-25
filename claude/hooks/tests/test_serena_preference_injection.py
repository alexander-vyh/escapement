"""Behavioral tests for claude/hooks/serena_preference_injection.py.

Business outcome: Escapement ships Serena on every host, so in any code project
the model is told — once per session, not every turn — to reach for Serena's
symbol tools, and is nudged to onboard Serena when the project has no Serena
memories yet. Outside a code project it stays silent.

The hook runs as a subprocess with each host's UserPromptSubmit payload shape,
and its per-session flag lives under an isolated TMPDIR. Assertions read the
additionalContext the host would inject.

Run from anywhere:
  python3 -m pytest claude/hooks/tests/test_serena_preference_injection.py -q
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_HOOK = Path(__file__).resolve().parent.parent / "serena_preference_injection.py"


@pytest.fixture
def tmpdir_env(tmp_path):
    flags = tmp_path / "tmp"
    flags.mkdir()
    return flags


@pytest.fixture
def onboarded_project(tmp_path):
    project = tmp_path / "project"
    (project / ".git").mkdir(parents=True)
    memories = project / ".serena" / "memories"
    memories.mkdir(parents=True)
    (memories / "architecture.md").write_text("notes", encoding="utf-8")
    return project


@pytest.fixture
def fresh_project(tmp_path):
    """A code project Serena has not been onboarded to."""
    project = tmp_path / "fresh"
    project.mkdir()
    (project / "pyproject.toml").write_text("[project]\nname='x'\n", encoding="utf-8")
    return project


def _claude_prompt(session_id: str, cwd: Path) -> dict:
    return {
        "session_id": session_id,
        "transcript_path": "/dev/null",
        "cwd": str(cwd),
        "permission_mode": "default",
        "hook_event_name": "UserPromptSubmit",
        "prompt": "refactor the parser",
    }


def _codex_prompt(session_id: str, cwd: Path) -> dict:
    return {
        "session_id": session_id,
        "cwd": str(cwd),
        "hook_event_name": "UserPromptSubmit",
        "prompt": "refactor the parser",
    }


def _pi_prompt(session_id: str, cwd: Path) -> dict:
    """What Pi's extension forwards on a user prompt."""
    return {
        "session_id": session_id,
        "cwd": str(cwd),
        "hook_event_name": "UserPromptSubmit",
        "prompt": "refactor the parser",
    }


def _inject(payload: dict, tmpdir: Path) -> str | None:
    """Run the hook as the host does; return injected context or None."""
    env = {**os.environ, "TMPDIR": str(tmpdir)}
    result = subprocess.run(
        [sys.executable, str(_HOOK)],
        input=json.dumps(payload),
        capture_output=True, text=True, env=env, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout.strip()
    if not out:
        return None
    output = json.loads(out)["hookSpecificOutput"]
    assert output["hookEventName"] == "UserPromptSubmit"
    return output["additionalContext"]


def _assert_once_per_session(make_payload, project: Path, tmpdir: Path) -> None:
    first = _inject(make_payload("s-1", project), tmpdir)
    assert first is not None and "find_symbol" in first, first
    assert _inject(make_payload("s-1", project), tmpdir) is None, "second prompt must be silent"
    assert _inject(make_payload("s-2", project), tmpdir) is not None, "new session fires again"


def test_claude_prompt_submit_injects_guidance_once_per_session(onboarded_project, tmpdir_env):
    _assert_once_per_session(_claude_prompt, onboarded_project, tmpdir_env)


def test_codex_prompt_submit_injects_guidance_once_per_session(onboarded_project, tmpdir_env):
    _assert_once_per_session(_codex_prompt, onboarded_project, tmpdir_env)


def test_pi_prompt_submit_injects_guidance_once_per_session(onboarded_project, tmpdir_env):
    _assert_once_per_session(_pi_prompt, onboarded_project, tmpdir_env)


def test_sessions_on_different_hosts_do_not_suppress_each_other(onboarded_project, tmpdir_env):
    assert _inject(_codex_prompt("codex-a", onboarded_project), tmpdir_env) is not None
    assert _inject(_pi_prompt("pi-b", onboarded_project), tmpdir_env) is not None


def test_non_code_directory_is_silent(tmp_path, tmpdir_env):
    plain = tmp_path / "notes"
    plain.mkdir()
    assert _inject(_codex_prompt("s-plain", plain), tmpdir_env) is None


def test_onboarding_nudge_only_when_memories_absent(onboarded_project, fresh_project, tmpdir_env):
    """A project without Serena memories still gets the guidance — Serena ships
    with Escapement — plus a nudge to onboard; an onboarded one gets no nudge
    and is told the full-read gate applies."""
    fresh = _inject(_codex_prompt("s-fresh", fresh_project), tmpdir_env)
    onboarded = _inject(_codex_prompt("s-onboarded", onboarded_project), tmpdir_env)

    assert fresh is not None and "find_symbol" in fresh
    assert "onboarding" in fresh
    assert "serena_preference_gate" not in fresh, "gate is inert until onboarded"

    assert onboarded is not None
    assert "onboarding" not in onboarded
    assert "serena_preference_gate" in onboarded


def test_nested_directory_of_a_project_fires(onboarded_project, tmpdir_env):
    nested = onboarded_project / "src" / "pkg"
    nested.mkdir(parents=True)
    assert _inject(_pi_prompt("s-nested", nested), tmpdir_env) is not None
