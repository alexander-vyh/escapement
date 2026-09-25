"""project-bootstrap.sh wires a project for the host that is actually running.

Business outcome
----------------
Opening a fresh repository in Codex (or Pi) initialises OpenSpec for that host,
checks the instructions file that host reads, and tells the agent how to
dispatch subagents in that host's own tool vocabulary. A Codex session must not
be told to run `TeamCreate` or to write a CLAUDE.md.

Independent source of truth
---------------------------
The command the rendered Codex plugin registers (plugins/escapement/hooks/
hooks.json), run through a shell the way Codex runs it with PLUGIN_ROOT set, on
the SessionStart payload captured from codex-cli 0.156.1. `openspec init
--help` (1.2.0) lists `claude`, `codex` and `pi` as tool ids; a stub records
the arguments it was given. Codex adds SessionStart additionalContext to the
model's context (documented; captured for other SessionStart hooks here).

Rejects
-------
- the Claude bootstrap running unchanged under Codex (wrong OpenSpec tools,
  CLAUDE.md nag, TeamCreate prime);
- a Codex registration that never reaches the script, or loses the host.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CODEX_PLUGIN = ROOT / "plugins" / "escapement"
SCRIPT = ROOT / "scripts" / "project-bootstrap.sh"
SESSION_START = json.loads(
    (ROOT / "claude" / "hooks" / "tests" / "fixtures" / "codex_agent_mcp_stop_payloads.json").read_text()
)["payloads"]["session_start"]


def _stub_bin(tmp_path: Path) -> Path:
    """git and jq from the system; an openspec that records its arguments."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("git", "jq"):
        real = shutil.which(tool)
        assert real, f"{tool} is required"
        (bin_dir / tool).symlink_to(real)
    openspec = bin_dir / "openspec"
    openspec.write_text(
        "#!/bin/bash\n"
        f'printf "%s\\n" "$@" > "{tmp_path}/openspec-args"\n'
        'mkdir -p openspec\n'
    )
    openspec.chmod(0o755)
    return bin_dir


def _repo(tmp_path: Path, *files: str) -> Path:
    repo = tmp_path / "project"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    for rel in files:
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n" if rel.endswith(".json") else "x\n")
    return repo


def _run(command: list[str], repo: Path, tmp_path: Path, **env: str) -> str:
    result = subprocess.run(
        command,
        input=json.dumps({**SESSION_START, "cwd": str(repo)}),
        env={"PATH": f"{_stub_bin(tmp_path)}:/usr/bin:/bin", "HOME": str(tmp_path), **env},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    return out["hookSpecificOutput"]["additionalContext"]


def _codex_command() -> str:
    hooks = json.loads((CODEX_PLUGIN / "hooks" / "hooks.json").read_text())["hooks"]
    [command] = [
        hook["command"]
        for group in hooks.get("SessionStart", [])
        for hook in group["hooks"]
        if "project-bootstrap.sh" in hook["command"]
    ]
    return command


def _openspec_args(tmp_path: Path) -> list[str]:
    return (tmp_path / "openspec-args").read_text().split()


def test_codex_plugin_command_bootstraps_for_codex(tmp_path):
    repo = _repo(tmp_path)
    context = _run(["bash", "-c", _codex_command()], repo, tmp_path, PLUGIN_ROOT=str(CODEX_PLUGIN))

    assert _openspec_args(tmp_path) == ["init", "--tools", "codex", "."]
    assert "openspec: initialized with codex tools" in context
    assert "No AGENTS.md found" in context and "CLAUDE.md" not in context
    assert "spawn_agent" in context and "task_name" in context
    assert "TeamCreate" not in context
    assert "continuation-harness.md" not in context, "a rule Codex does not carry"


def test_codex_existing_project_gets_only_the_codex_prime(tmp_path):
    repo = _repo(tmp_path, "openspec/project.md", "AGENTS.md", ".escapement/repo.json")
    context = _run(["bash", "-c", _codex_command()], repo, tmp_path, PLUGIN_ROOT=str(CODEX_PLUGIN))

    assert not (tmp_path / "openspec-args").exists(), "an initialised project is left alone"
    assert context.startswith("## Agent Dispatch Rules") and "spawn_agent" in context
    assert "Project Bootstrap Report" not in context


def test_pi_host_bootstraps_with_pi_tools(tmp_path):
    """The contract the Pi extension relies on: ESCAPEMENT_HOST=pi, bash, stdin."""
    repo = _repo(tmp_path, "CLAUDE.md")
    context = _run(["bash", str(SCRIPT)], repo, tmp_path, ESCAPEMENT_HOST="pi")

    assert _openspec_args(tmp_path) == ["init", "--tools", "pi", "."]
    assert "No AGENTS.md found" not in context, "Pi also reads CLAUDE.md"
    assert "subagent tool" in context and "TeamCreate" not in context


def test_claude_default_is_unchanged(tmp_path):
    """Control: with no host declared the script still bootstraps for Claude."""
    repo = _repo(tmp_path)
    context = _run(["bash", str(SCRIPT)], repo, tmp_path)

    assert _openspec_args(tmp_path) == ["init", "--tools", "claude", "."]
    assert "No CLAUDE.md found" in context and "TeamCreate" in context
