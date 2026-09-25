"""inject_rules.py injects the rules bundle that ships beside it, in every
host package layout, and fails loud when the bundle is missing."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "inject_rules.py"


def _install(root: Path, hooks_rel: str, rules_rel: str, rules: dict[str, str]) -> Path:
    hook = root / hooks_rel / HOOK.name
    hook.parent.mkdir(parents=True)
    shutil.copy2(HOOK, hook)
    if rules:
        rules_dir = root / rules_rel
        rules_dir.mkdir(parents=True)
        for name, text in rules.items():
            (rules_dir / name).write_text(text, encoding="utf-8")
    return hook


def _run(hook: Path, event: str = "SessionStart") -> dict:
    completed = subprocess.run(
        [sys.executable, str(hook)],
        input=json.dumps({"hook_event_name": event, "session_id": "s"}),
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    return json.loads(completed.stdout)["hookSpecificOutput"]


def test_codex_plugin_layout_injects_the_packages_own_rule_variants(tmp_path):
    hook = _install(
        tmp_path, "plugin/claude/hooks", "plugin/claude/rules",
        {"teams.md": "Dispatch reviewers with spawn_agent.\n"},
    )
    output = _run(hook)

    assert output["hookEventName"] == "SessionStart"
    assert "Dispatch reviewers with spawn_agent." in output["additionalContext"]


def test_claude_plugin_layout_reads_rules_beside_hooks(tmp_path):
    hook = _install(tmp_path, "plugin/hooks", "plugin/rules", {"a.md": "Rule A body.\n", "b.md": "Rule B body.\n"})
    context = _run(hook)["additionalContext"]

    assert context.index("Rule A body.") < context.index("Rule B body.")
    assert "MUST follow" in context


def test_codex_precompact_reinjection_names_its_event(tmp_path):
    hook = _install(tmp_path, "p/claude/hooks", "p/claude/rules", {"a.md": "Rule A.\n"})
    output = _run(hook, event="PreCompact")

    assert output["hookEventName"] == "PreCompact"
    assert "Rule A." in output["additionalContext"]
