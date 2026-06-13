import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
RENDERER = ROOT / "tools" / "render_agent_surfaces.py"
MANIFEST = ROOT / "agent-surfaces" / "manifest.json"
EXPECTED_CODEX_GATE = {
    "event": "PreToolUse",
    "matcher": "Bash",
    "command": "python3 claude/hooks/test_oracle_brief_gate.py",
    "timeout": 5,
}


def run_renderer(*args, root=ROOT):
    return subprocess.run(
        [sys.executable, str(RENDERER), *args],
        cwd=root,
        capture_output=True,
        text=True,
    )


def test_generated_surfaces_are_current():
    result = run_renderer("--check")
    assert result.returncode == 0, result.stderr


def test_codex_hooks_include_prime_and_behavioral_gate():
    hooks = json.loads((ROOT / ".codex" / "hooks.json").read_text())["hooks"]
    commands = [
        hook["command"]
        for event_items in hooks.values()
        for item in event_items
        for hook in item["hooks"]
    ]
    assert "bd prime" in commands
    assert "python3 claude/hooks/test_oracle_brief_gate.py" in commands


def test_codex_behavioral_gate_has_exact_event_shape():
    hooks = json.loads((ROOT / ".codex" / "hooks.json").read_text())["hooks"]
    entries = hooks.get(EXPECTED_CODEX_GATE["event"], [])
    matches = [
        item
        for item in entries
        if item.get("matcher") == EXPECTED_CODEX_GATE["matcher"]
        for hook in item.get("hooks", [])
        if hook.get("command") == EXPECTED_CODEX_GATE["command"]
        and hook.get("timeout") == EXPECTED_CODEX_GATE["timeout"]
    ]
    assert matches, "Codex Test Oracle Brief gate must be PreToolUse/Bash with timeout"


def test_codex_generated_surfaces_do_not_use_claude_user_paths():
    forbidden = ("~/.claude", "CLAUDE_CODE_SESSION_ID", "ScheduleWakeup", "TeamCreate")
    text = (
        (ROOT / "AGENTS.md").read_text()
        + (ROOT / ".codex" / "hooks.json").read_text()
        + "\n".join(skill.read_text() for skill in sorted((ROOT / ".agents" / "skills").glob("*/SKILL.md")))
    )
    for needle in forbidden:
        assert needle not in text


def test_codex_ready_hook_without_fixture_fails(tmp_path):
    temp_root = copy_repo(tmp_path)
    manifest_path = temp_root / "agent-surfaces" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for hook in manifest["hooks"]:
        if hook["id"] == "test_oracle_brief_gate":
            hook["hosts"]["codex"]["fixtures"] = []
            break
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    result = run_renderer("--check", root=temp_root)

    assert result.returncode != 0
    assert "ready without fixtures" in result.stderr


def test_codex_ready_hook_with_bogus_fixture_fails(tmp_path):
    temp_root = copy_repo(tmp_path)
    manifest_path = temp_root / "agent-surfaces" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for hook in manifest["hooks"]:
        if hook["id"] == "test_oracle_brief_gate":
            hook["hosts"]["codex"]["fixtures"] = ["does/not/exist.py::test_fake"]
            break
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    result = run_renderer("--check", root=temp_root)

    assert result.returncode != 0
    assert "fixture does not exist" in result.stderr


def test_codex_ready_hook_with_non_pytest_fixture_fails(tmp_path):
    temp_root = copy_repo(tmp_path)
    manifest_path = temp_root / "agent-surfaces" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for hook in manifest["hooks"]:
        if hook["id"] == "test_oracle_brief_gate":
            hook["hosts"]["codex"]["fixtures"] = ["README.md"]
            break
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    result = run_renderer("--check", root=temp_root)

    assert result.returncode != 0
    assert "Codex hook fixture must be a pytest selector" in result.stderr


def test_codex_ready_hook_with_non_codex_fixture_fails(tmp_path):
    temp_root = copy_repo(tmp_path)
    manifest_path = temp_root / "agent-surfaces" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for hook in manifest["hooks"]:
        if hook["id"] == "test_oracle_brief_gate":
            hook["hosts"]["codex"]["fixtures"] = [
                "claude/hooks/tests/test_test_oracle_brief_gate.py::test_claude_edit_blocks_relevant_file_without_brief"
            ]
            break
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    result = run_renderer("--check", root=temp_root)

    assert result.returncode != 0
    assert "Codex hook fixture must be Codex-specific" in result.stderr


def test_codex_ready_hook_with_other_hook_codex_fixture_fails(tmp_path):
    temp_root = copy_repo(tmp_path)
    manifest_path = temp_root / "agent-surfaces" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for hook in manifest["hooks"]:
        if hook["id"] == "review_gate":
            hook["hosts"]["codex"] = {
                "status": "ready",
                "events": [
                    {
                        "event": "PreToolUse",
                        "matcher": "Bash",
                        "command": "python3 claude/hooks/review_gate.py",
                        "timeout_seconds": 5,
                    }
                ],
                "fixtures": [
                    "claude/hooks/tests/test_test_oracle_brief_gate.py::test_codex_commit_blocks_changed_code_without_brief"
                ],
            }
            break
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    render_result = run_renderer(root=temp_root)
    assert render_result.returncode == 0, render_result.stderr

    result = run_renderer("--check", root=temp_root)

    assert result.returncode != 0
    assert "Codex hook fixture must match hook source" in result.stderr


def test_codex_behavioral_gate_wrong_event_fails_drift_check(tmp_path):
    temp_root = copy_repo(tmp_path)
    manifest_path = temp_root / "agent-surfaces" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for hook in manifest["hooks"]:
        if hook["id"] == "test_oracle_brief_gate":
            hook["hosts"]["codex"]["events"][0]["event"] = "SessionStart"
            break
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    result = run_renderer("--check", root=temp_root)

    assert result.returncode != 0
    assert "generated target drift: .codex/hooks.json" in result.stderr


@pytest.mark.parametrize("target", ["AGENTS.md", "CLAUDE.md", ".codex/hooks.json"])
def test_generated_surface_drift_names_target(tmp_path, target):
    temp_root = copy_repo(tmp_path)
    generated = temp_root / target
    generated.write_text(generated.read_text() + "\nmanual edit\n")

    result = run_renderer("--check", root=temp_root)

    assert result.returncode != 0
    assert f"generated target drift: {target}" in result.stderr


def test_empty_codex_skill_fails(tmp_path):
    temp_root = copy_repo(tmp_path)
    skill = temp_root / ".agents" / "skills" / "openspec-apply-change" / "SKILL.md"
    skill.write_text("---\nname: openspec-apply-change\ndescription: x\n---\n")

    result = run_renderer("--check", root=temp_root)

    assert result.returncode != 0
    assert "empty or too small" in result.stderr


def test_unmanifested_codex_skill_fails(tmp_path):
    temp_root = copy_repo(tmp_path)
    skill_dir = temp_root / ".agents" / "skills" / "untracked-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: untracked-skill\ndescription: OpenSpec helper\n---\n\nRun openspec list.\n"
    )

    result = run_renderer("--check", root=temp_root)

    assert result.returncode != 0
    assert "skill target not listed in manifest" in result.stderr


def test_codex_skill_surfaces_do_not_reference_unavailable_tools():
    for skill in sorted((ROOT / ".agents" / "skills").glob("*/SKILL.md")):
        text = skill.read_text(encoding="utf-8")
        for token in ("TodoWrite", "AskUserQuestion", "Task tool", "subagent_type"):
            assert token not in text, f"{skill} must not reference {token}"


def test_codex_skill_with_claude_only_token_fails(tmp_path):
    temp_root = copy_repo(tmp_path)
    skill = temp_root / ".agents" / "skills" / "openspec-apply-change" / "SKILL.md"
    skill.write_text(skill.read_text() + "\nUse ~/.claude/local-state here.\n")

    result = run_renderer("--check", root=temp_root)

    assert result.returncode != 0
    assert "Codex skill contains forbidden Claude-only token" in result.stderr


def copy_repo(tmp_path):
    temp_root = tmp_path / "repo"
    shutil.copytree(
        ROOT,
        temp_root,
        ignore=shutil.ignore_patterns(".git", ".worktrees", "__pycache__", ".pytest_cache"),
    )
    return temp_root
