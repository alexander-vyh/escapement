"""Behavioral tests for claude/hooks/dsy_reminder.py.

Business outcome: agents overbuild, and the user used to retype a short
design-principles reminder by hand. On EVERY prompt, on Claude, Codex and Pi,
the model receives that reminder through additionalContext (the one channel all
three hosts pass to the model), cheaply: one short line, no user-visible noise.

The hook runs as a subprocess with each host's UserPromptSubmit payload shape.

Run from anywhere:
  python3 -m pytest claude/hooks/tests/test_dsy_reminder.py -q
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_HOOK = Path(__file__).resolve().parent.parent / "dsy_reminder.py"
_MAX_CHARS = 40


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


_HOSTS = pytest.mark.parametrize(
    "make_payload", [_claude_prompt, _codex_prompt, _pi_prompt],
    ids=["claude", "codex", "pi"],
)


def _run(stdin: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_HOOK)],
        input=stdin, capture_output=True, text=True, cwd=cwd, timeout=30,
    )


def _reminder(stdin: str, cwd: Path) -> str:
    """Run the hook as a host does; return the context the model receives."""
    result = _run(stdin, cwd)
    assert result.returncode == 0, result.stderr
    document = json.loads(result.stdout)
    assert "systemMessage" not in document, "a systemMessage would nag the user every prompt"
    output = document["hookSpecificOutput"]
    assert output["hookEventName"] == "UserPromptSubmit"
    return output["additionalContext"]


@_HOSTS
def test_every_prompt_in_one_session_gets_the_reminder(make_payload, tmp_path):
    project = tmp_path / "project"
    (project / ".git").mkdir(parents=True)
    payload = json.dumps(make_payload("same-session", project))

    first = _reminder(payload, project)
    second = _reminder(payload, project)
    third = _reminder(payload, project)

    assert first and first == second == third


@_HOSTS
def test_reminder_names_the_three_principles_in_one_short_line(make_payload, tmp_path):
    text = _reminder(json.dumps(make_payload("s-1", tmp_path)), tmp_path)

    for principle in ("DRY", "SOLID", "YAGNI"):
        assert principle in text
    assert "\n" not in text.strip()
    assert len(text) <= _MAX_CHARS


def test_reminder_fires_outside_a_code_project(tmp_path):
    """Overbuilding is not limited to code projects; a notes dir still gets it."""
    plain = tmp_path / "notes"
    plain.mkdir()

    assert _reminder(json.dumps(_codex_prompt("s-plain", plain)), plain)


@pytest.mark.parametrize("stdin", ["", "   \n", "not json at all", "[1, 2]", "null"])
def test_unusable_stdin_still_emits_the_reminder(stdin, tmp_path):
    assert _reminder(stdin, tmp_path)
