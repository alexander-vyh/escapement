"""Behavioral tests for claude/hooks/serena_preference_gate.py.

Business outcome the gate protects: when Serena (LSP-backed symbol tools) is
onboarded for a project, the main thread should not burn context by reading an
entire large source file top-to-bottom — it should use symbol tools instead.
The gate enforces this by DENYING full-file Reads (and cat/head/tail bypasses)
of large source files, redirecting to Serena's symbol tools.

The gate is a tightrope: it must block the wasteful case while leaving every
legitimate case alone. So the controls come in pairs.

  Negative control — a full-file Read of a LARGE source file, in a project
  that HAS .serena/memories, must be DENIED with a decision that redirects to
  Serena's symbol tools (and the redirect must carry the file's path so it is
  actionable). This is the one case the gate exists to catch.

  Positive controls — each of the gate's documented exemptions must pass
  through (return 0, no deny):
    * targeted Read (offset/limit set) — already cheap
    * non-source file (e.g. .md) — not Serena's domain
    * small source file — full Read is cheap
    * project WITHOUT .serena/memories — Serena not onboarded
    * subagent context — subagents do their own exploration
  Plus a Bash cat-bypass mirror of the negative control, so the shell path is
  not silently un-guarded.

All inputs are real on-disk fixtures (a genuine large .py file, a real
.serena/memories dir) and the assertions read the externally-observable
permission decision + redirect text, not the gate's private classifier
helpers — so they are behavioral, not implementation echoes.

Run from anywhere:
  python3 -m pytest claude/hooks/tests/test_serena_preference_gate.py -v
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_hooks_dir = Path(__file__).resolve().parent.parent
if str(_hooks_dir) not in sys.path:
    sys.path.insert(0, str(_hooks_dir))

import serena_preference_gate as hook  # noqa: E402


# Size that comfortably exceeds the gate's "small file" threshold (8 KiB).
_LARGE_SOURCE = "def f():\n    return 1  # padding line to grow the file\n" * 600


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def serena_project(tmp_path, monkeypatch):
    """A tmp project that is a git repo AND has a non-empty .serena/memories.

    This is the "Serena is onboarded here" state in which the gate is allowed
    to fire. Also clears subagent env vars so the gate doesn't silently exempt
    every test as a subagent run.
    """
    for var in (
        "CLAUDE_AGENT_NAME", "CLAUDE_AGENT_TYPE", "CLAUDE_SUBAGENT",
        "CLAUDE_TEAM_NAME", "CLAUDE_AGENT_ID",
    ):
        monkeypatch.delenv(var, raising=False)

    (tmp_path / ".git").mkdir()  # project-root signal
    memories = tmp_path / ".serena" / "memories"
    memories.mkdir(parents=True)
    (memories / "architecture.md").write_text("notes", encoding="utf-8")
    return tmp_path


@pytest.fixture
def bare_project(tmp_path, monkeypatch):
    """A tmp project that is a git repo but has NO .serena/memories."""
    for var in (
        "CLAUDE_AGENT_NAME", "CLAUDE_AGENT_TYPE", "CLAUDE_SUBAGENT",
        "CLAUDE_TEAM_NAME", "CLAUDE_AGENT_ID",
    ):
        monkeypatch.delenv(var, raising=False)
    (tmp_path / ".git").mkdir()
    return tmp_path


def _run_read(file_path, cwd, *, offset=None, limit=None) -> tuple[int, dict]:
    return _run("Read", {"file_path": str(file_path),
                         **({"offset": offset} if offset is not None else {}),
                         **({"limit": limit} if limit is not None else {})}, cwd)


def _run_bash(command, cwd) -> tuple[int, dict]:
    return _run("Bash", {"command": command}, cwd)


def _run(tool_name, tool_input, cwd) -> tuple[int, dict]:
    """Drive the gate's main() and return (exit_code, parsed_stdout_json).

    The gate returns 0 in all paths and only *emits JSON* when it denies, so
    the deny vs allow distinction is whether stdout carries a deny decision.
    """
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": tool_input,
        "cwd": str(cwd),
    }
    stdout_capture = io.StringIO()
    with (
        patch("sys.stdin", io.StringIO(json.dumps(payload))),
        patch("sys.stdout", stdout_capture),
        patch.object(hook, "_record_signal", lambda *a, **k: None),
    ):
        ret = hook.main()
    exit_code = ret if ret is not None else 0
    out = stdout_capture.getvalue().strip()
    parsed = json.loads(out) if out else {}
    return exit_code, parsed


def _is_deny(parsed: dict) -> bool:
    return parsed.get("hookSpecificOutput", {}).get(
        "permissionDecision"
    ) == "deny"


# ---------------------------------------------------------------------------
# Negative control: the case the gate exists to catch.
# ---------------------------------------------------------------------------

def test_full_read_of_large_source_with_serena_is_denied(serena_project):
    """Full-file Read of a large .py file in a Serena-onboarded project must
    be DENIED and the denial must redirect to Serena symbol tools, naming the
    file path so the redirect is actionable."""
    big = serena_project / "campaign.py"
    big.write_text(_LARGE_SOURCE, encoding="utf-8")

    exit_code, parsed = _run_read(big, serena_project)

    assert exit_code == 0  # gate signals via JSON, not exit code
    assert _is_deny(parsed), "large source full-read must be denied"

    reason = parsed["hookSpecificOutput"]["permissionDecisionReason"]
    # Redirect must point at Serena's symbol tools (the actionable escape).
    assert "mcp__serena__" in reason, reason
    # And carry the file's name so the user can paste it into the call.
    assert "campaign.py" in reason, reason


def test_full_cat_of_large_source_with_serena_is_denied(serena_project):
    """The shell bypass (cat/head/tail) must be guarded the same way — a
    full `cat` of a large source file is denied and redirected."""
    big = serena_project / "service.py"
    big.write_text(_LARGE_SOURCE, encoding="utf-8")

    exit_code, parsed = _run_bash(f"cat {big}", serena_project)

    assert exit_code == 0
    assert _is_deny(parsed), "full-file `cat` of large source must be denied"
    reason = parsed["hookSpecificOutput"]["permissionDecisionReason"]
    assert "service.py" in reason, reason


# ---------------------------------------------------------------------------
# Positive controls: every documented exemption must pass through.
# ---------------------------------------------------------------------------

def test_targeted_read_passes(serena_project):
    """A Read with offset/limit is already cheap — must NOT be denied even on
    a large source file in a Serena project."""
    big = serena_project / "campaign.py"
    big.write_text(_LARGE_SOURCE, encoding="utf-8")

    _, parsed = _run_read(big, serena_project, offset=100, limit=50)
    assert not _is_deny(parsed)


def test_non_source_file_passes(serena_project):
    """A large markdown file is not Serena's domain — must pass through."""
    doc = serena_project / "README.md"
    doc.write_text(_LARGE_SOURCE, encoding="utf-8")  # large, but .md

    _, parsed = _run_read(doc, serena_project)
    assert not _is_deny(parsed)


def test_small_source_file_passes(serena_project):
    """A small .py file is cheap to read fully — must pass through."""
    small = serena_project / "tiny.py"
    small.write_text("def f():\n    return 1\n", encoding="utf-8")

    _, parsed = _run_read(small, serena_project)
    assert not _is_deny(parsed)


def test_large_source_without_serena_passes(bare_project):
    """Same large source file, but the project has NO .serena/memories — the
    gate must stay silent because Serena is not onboarded here."""
    big = bare_project / "campaign.py"
    big.write_text(_LARGE_SOURCE, encoding="utf-8")

    _, parsed = _run_read(big, bare_project)
    assert not _is_deny(parsed)


def test_subagent_is_exempt(serena_project, monkeypatch):
    """Subagents absorb research work — a full-file Read from a subagent must
    pass through even on a large source file in a Serena project."""
    monkeypatch.setenv("CLAUDE_AGENT_NAME", "explorer-1")
    big = serena_project / "campaign.py"
    big.write_text(_LARGE_SOURCE, encoding="utf-8")

    _, parsed = _run_read(big, serena_project)
    assert not _is_deny(parsed)
