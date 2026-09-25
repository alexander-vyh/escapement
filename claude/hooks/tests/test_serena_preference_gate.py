"""Behavioral tests for claude/hooks/serena_preference_gate.py.

Business outcome the gate protects: when Serena (LSP-backed symbol tools) is
onboarded for a project, the main thread should not burn context by reading an
entire large source file top-to-bottom — on any host. Claude and Pi read files
with a Read tool (Pi's adapter forwards the Claude Read shape); Codex reads them
through the shell (`cat FILE`, `nl -ba FILE`). Each host's full read of a large
source file is DENIED with a redirect that names the file; every cheaper read
(ranged, small, non-source, not onboarded, subagent) passes.

The hook runs as a subprocess — the way every host invokes it — against real
on-disk projects, and the assertions read the permission decision it prints.

Run from anywhere:
  python3 -m pytest claude/hooks/tests/test_serena_preference_gate.py -q
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_HOOK = Path(__file__).resolve().parent.parent / "serena_preference_gate.py"
_CODEX_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "codex_apply_patch_pretooluse.json"

# Size that comfortably exceeds the gate's "small file" threshold (8 KiB).
_LARGE_SOURCE = "def f():\n    return 1  # padding line to grow the file\n" * 600

_SUBAGENT_VARS = (
    "CLAUDE_AGENT_NAME", "CLAUDE_AGENT_TYPE", "CLAUDE_SUBAGENT",
    "CLAUDE_TEAM_NAME", "CLAUDE_AGENT_ID",
)


# ---------------------------------------------------------------------------
# Fixtures and drivers
# ---------------------------------------------------------------------------

@pytest.fixture
def signal_dir(tmp_path):
    return tmp_path / "signal"


@pytest.fixture
def serena_project(tmp_path):
    """A git project with a non-empty .serena/memories: Serena is onboarded."""
    project = tmp_path / "project"
    (project / ".git").mkdir(parents=True)
    memories = project / ".serena" / "memories"
    memories.mkdir(parents=True)
    (memories / "architecture.md").write_text("notes", encoding="utf-8")
    return project


@pytest.fixture
def bare_project(tmp_path):
    """A git project with NO .serena/memories."""
    project = tmp_path / "project"
    (project / ".git").mkdir(parents=True)
    return project


def _large(project: Path, relative: str) -> Path:
    path = project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_LARGE_SOURCE, encoding="utf-8")
    return path


def _run(payload: dict, cwd: Path, signal_dir: Path, **extra_env: str) -> dict:
    """Invoke the hook as the host does; return its parsed stdout ({} = allow)."""
    env = {k: v for k, v in os.environ.items()
           if k not in _SUBAGENT_VARS and k != "BEADS_DIR"}
    env["GATE_SIGNAL_FALLBACK_DIR"] = str(signal_dir)
    env.update(extra_env)
    result = subprocess.run(
        [sys.executable, str(_HOOK)],
        input=json.dumps(payload),
        capture_output=True, text=True, cwd=cwd, env=env, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout.strip()
    return json.loads(out) if out else {}


def _claude_read(file_path, cwd, **tool_input) -> dict:
    return {
        "session_id": "claude-session",
        "hook_event_name": "PreToolUse",
        "tool_name": "Read",
        "tool_input": {"file_path": str(file_path), **tool_input},
        "cwd": str(cwd),
    }


def _pi_read(path, cwd, *, offset=None, limit=None) -> dict:
    """What Pi's extension forwards for Pi `read` {path, offset, limit}."""
    tool_input = {"file_path": str(path)}
    if offset is not None:
        tool_input["offset"] = offset
    if limit is not None:
        tool_input["limit"] = limit
    return {
        "session_id": "pi-session",
        "cwd": str(cwd),
        "hook_event_name": "PreToolUse",
        "tool_name": "Read",
        "tool_input": tool_input,
    }


def _codex_bash(command: str, cwd: Path) -> dict:
    """The captured Codex Bash payload, pointed at this command and project."""
    captured = json.loads(_CODEX_FIXTURE.read_text(encoding="utf-8"))["payloads"]["bash"]
    return {
        **captured,
        "session_id": "codex-session",
        "hook_event_name": "PreToolUse",
        "tool_input": {**captured["tool_input"], "command": command},
        "cwd": str(cwd),
    }


def _deny_reason(parsed: dict) -> str | None:
    output = parsed.get("hookSpecificOutput", {})
    if output.get("permissionDecision") != "deny":
        return None
    return output["permissionDecisionReason"]


# ---------------------------------------------------------------------------
# Negative controls: the full read the gate exists to catch, on every host.
# ---------------------------------------------------------------------------

def test_claude_full_read_of_large_source_is_denied(serena_project, signal_dir):
    """A denied read names the file relative to cwd and redirects to Serena's
    symbol tools; the decision lands in the gate-signal store."""
    big = _large(serena_project, "pkg/campaign.py")

    reason = _deny_reason(_run(_claude_read(big, serena_project), serena_project, signal_dir))

    assert reason is not None, "large source full-read must be denied"
    assert "pkg/campaign.py" in reason, reason
    assert "get_symbols_overview" in reason, reason
    records = [
        json.loads(line)
        for line in (signal_dir / "gate-signal-fallback.jsonl").read_text().splitlines()
    ]
    assert any(
        r.get("gate") == "serena_preference_gate" and r.get("decision") == "deny"
        for r in records
    ), records


def test_codex_full_cat_of_large_source_is_denied(serena_project, signal_dir):
    _large(serena_project, "pkg/service.py")

    reason = _deny_reason(
        _run(_codex_bash("cat pkg/service.py", serena_project), serena_project, signal_dir)
    )

    assert reason is not None, "full-file `cat` of large source must be denied"
    assert "pkg/service.py" in reason, reason


def test_codex_full_nl_of_large_source_is_denied(serena_project, signal_dir):
    """Codex's habitual whole-file read, `nl -ba FILE`, is a full read too —
    including after a `cd` into the package."""
    _large(serena_project, "pkg/service.py")

    for command in ("nl -ba pkg/service.py", "cd pkg && nl -ba service.py"):
        reason = _deny_reason(
            _run(_codex_bash(command, serena_project), serena_project, signal_dir)
        )
        assert reason is not None, command
        assert "service.py" in reason, reason


def test_pi_read_of_large_source_is_denied(serena_project, signal_dir):
    _large(serena_project, "src/engine.py")

    reason = _deny_reason(
        _run(_pi_read("src/engine.py", serena_project), serena_project, signal_dir)
    )

    assert reason is not None, "Pi full read of large source must be denied"
    assert "src/engine.py" in reason, reason


# ---------------------------------------------------------------------------
# Positive controls: every documented exemption must pass through.
# ---------------------------------------------------------------------------

def test_codex_ranged_sed_read_is_allowed(serena_project, signal_dir):
    """Ranged shell reads are the shell's offset/limit: allowed on a large
    source file, whether read directly or by piping a full read into a limiter."""
    _large(serena_project, "pkg/service.py")

    for command in (
        "sed -n '1,120p' pkg/service.py",
        "nl -ba pkg/service.py | sed -n '200,260p'",
        "head -n 80 pkg/service.py",
        "tail -n 40 pkg/service.py",
        "cat pkg/service.py | grep -n 'def '",
    ):
        parsed = _run(_codex_bash(command, serena_project), serena_project, signal_dir)
        assert _deny_reason(parsed) is None, command


def test_pi_ranged_read_is_allowed(serena_project, signal_dir):
    _large(serena_project, "src/engine.py")

    parsed = _run(
        _pi_read("src/engine.py", serena_project, offset=100, limit=50),
        serena_project, signal_dir,
    )
    assert _deny_reason(parsed) is None


def test_claude_targeted_read_is_allowed(serena_project, signal_dir):
    big = _large(serena_project, "campaign.py")

    parsed = _run(_claude_read(big, serena_project, offset=100, limit=50),
                  serena_project, signal_dir)
    assert _deny_reason(parsed) is None


def test_non_source_file_is_allowed(serena_project, signal_dir):
    """A large markdown file is not Serena's domain — on Read and on cat."""
    _large(serena_project, "README.md")

    assert _deny_reason(_run(_claude_read(serena_project / "README.md", serena_project),
                             serena_project, signal_dir)) is None
    assert _deny_reason(_run(_codex_bash("cat README.md", serena_project),
                             serena_project, signal_dir)) is None


def test_small_source_file_is_allowed(serena_project, signal_dir):
    small = serena_project / "tiny.py"
    small.write_text("def f():\n    return 1\n", encoding="utf-8")

    assert _deny_reason(_run(_claude_read(small, serena_project),
                             serena_project, signal_dir)) is None
    assert _deny_reason(_run(_codex_bash("cat tiny.py", serena_project),
                             serena_project, signal_dir)) is None


def test_project_without_serena_memories_is_allowed(bare_project, signal_dir):
    """Serena not onboarded here: the gate stays silent on every host shape."""
    _large(bare_project, "campaign.py")

    for payload in (
        _claude_read(bare_project / "campaign.py", bare_project),
        _pi_read("campaign.py", bare_project),
        _codex_bash("cat campaign.py", bare_project),
    ):
        assert _deny_reason(_run(payload, bare_project, signal_dir)) is None


def test_subagent_is_exempt(serena_project, signal_dir):
    big = _large(serena_project, "campaign.py")

    parsed = _run(_claude_read(big, serena_project), serena_project, signal_dir,
                  CLAUDE_AGENT_NAME="explorer-1")
    assert _deny_reason(parsed) is None
