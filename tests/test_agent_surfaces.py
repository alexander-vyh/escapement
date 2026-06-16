import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
RENDERER = ROOT / "tools" / "render_agent_surfaces.py"
MANIFEST = ROOT / "agent-surfaces" / "manifest.json"
CODEX_WRAPPER = ROOT / "plugins" / "escapement"
EXPECTED_CODEX_GATE = {
    "event": "PreToolUse",
    "matcher": "Bash",
    "command": "python3 claude/hooks/test_oracle_brief_gate.py",
    "timeout": 5,
}
MINIMUM_VERIFIED_DELIVERY_FRAGMENTS = (
    "Escapement optimizes for minimum verified delivery.",
    "YAGNI forbids speculative",
    "never weakens the outcome oracle",
    "current user/business outcome still passes its independent verification",
    "DRY targets duplicated authority, not similar text.",
    "Preserve independent corroborating checks",
    "Add gates only for repeated or high-severity failures with a replayable oracle",
)


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


def test_generated_docs_include_minimum_verified_delivery_guidance():
    assert_minimum_verified_delivery_guidance(ROOT)


def test_minimum_verified_delivery_guidance_without_oracle_guardrail_fails(tmp_path):
    temp_root = copy_repo(tmp_path)
    for rel_path in ("agent-surfaces/onboarding/outcome-oracle.md", "AGENTS.md", "CLAUDE.md"):
        path = temp_root / rel_path
        path.write_text(
            path.read_text().replace(
                "never weakens the outcome oracle",
                "prefers fewer files",
            )
        )

    with pytest.raises(AssertionError):
        assert_minimum_verified_delivery_guidance(temp_root)


def test_codex_repo_marketplace_points_to_installable_wrapper():
    marketplace_path = ROOT / ".agents" / "plugins" / "marketplace.json"
    assert marketplace_path.exists(), "repo marketplace must expose the Escapement Codex wrapper"

    marketplace = json.loads(marketplace_path.read_text())
    entries = [entry for entry in marketplace["plugins"] if entry["name"] == "escapement"]

    assert marketplace["name"] == "escapement-local"
    assert entries == [
        {
            "name": "escapement",
            "source": {"source": "local", "path": "./plugins/escapement"},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
            "category": "Developer Tools",
        }
    ]


def test_codex_plugin_wrapper_manifest_uses_current_ingestion_contract():
    legacy_manifest = ROOT / ".codex-plugin" / "plugin.json"
    assert not legacy_manifest.exists(), "legacy root Codex manifest is invalid and must not be installable"

    manifest_path = CODEX_WRAPPER / ".codex-plugin" / "plugin.json"
    assert manifest_path.exists(), "Codex wrapper must include .codex-plugin/plugin.json"

    manifest = json.loads(manifest_path.read_text())

    assert manifest["name"] == "escapement"
    assert manifest["version"] == "1.0.0"
    assert manifest["skills"] == "./skills/"
    assert "hooks" not in manifest, "current Codex plugin validation rejects a hooks manifest field"
    assert (CODEX_WRAPPER / "skills").is_dir()
    assert (CODEX_WRAPPER / "hooks" / "hooks.json").is_file()


def test_codex_plugin_wrapper_contains_current_codex_skills():
    source_skills = {
        path.parent.name: path.read_text(encoding="utf-8")
        for path in sorted((ROOT / ".agents" / "skills").glob("*/SKILL.md"))
    }
    wrapper_skills = {
        path.parent.name: path.read_text(encoding="utf-8")
        for path in sorted((CODEX_WRAPPER / "skills").glob("*/SKILL.md"))
    }

    assert wrapper_skills == source_skills
    assert "openspec-apply-change" in wrapper_skills


def test_codex_plugin_wrapper_hooks_are_self_contained_and_codex_shaped():
    hooks_path = CODEX_WRAPPER / "hooks" / "hooks.json"
    assert hooks_path.exists(), "Codex wrapper must package hooks/hooks.json for plugin discovery"

    hooks_text = hooks_path.read_text()
    for forbidden in ("${CLAUDE_PLUGIN_ROOT}", "~/.claude", "CLAUDE_CODE_SESSION_ID", "ScheduleWakeup", "TeamCreate"):
        assert forbidden not in hooks_text

    hooks = json.loads(hooks_text)["hooks"]
    commands = [
        hook["command"]
        for event_items in hooks.values()
        for item in event_items
        for hook in item["hooks"]
    ]

    assert "bd prime" in commands
    assert any("test_oracle_brief_gate.py" in command for command in commands)
    assert any("implementation_echo_test_gate.py" in command for command in commands)
    assert any("oracle_downgrade_warning_gate.py" in command for command in commands)

    for command in commands:
        if "${PLUGIN_ROOT}/" not in command:
            continue
        rel = command.split("${PLUGIN_ROOT}/", 1)[1].split('"', 1)[0]
        assert (CODEX_WRAPPER / rel).is_file(), f"hook command references missing wrapper file: {rel}"

    manifest = json.loads(MANIFEST.read_text())
    ready_hook_sources = {
        hook["source"]
        for hook in manifest["hooks"]
        if hook.get("source") != "bd" and hook["hosts"]["codex"]["status"] == "ready"
    }
    packaged_hook_sources = {
        path.relative_to(CODEX_WRAPPER).as_posix()
        for path in sorted((CODEX_WRAPPER / "claude" / "hooks").glob("*"))
    }
    assert ready_hook_sources <= packaged_hook_sources


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


def assert_minimum_verified_delivery_guidance(root):
    for rel_path in ("agent-surfaces/onboarding/outcome-oracle.md", "AGENTS.md", "CLAUDE.md"):
        text = " ".join((root / rel_path).read_text().split())
        for fragment in MINIMUM_VERIFIED_DELIVERY_FRAGMENTS:
            assert fragment in text, f"{rel_path} missing minimum verified delivery fragment: {fragment}"


def copy_repo(tmp_path):
    temp_root = tmp_path / "repo"
    shutil.copytree(
        ROOT,
        temp_root,
        ignore=shutil.ignore_patterns(".git", ".worktrees", "__pycache__", ".pytest_cache"),
    )
    return temp_root
