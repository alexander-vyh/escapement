"""An existing committed design can be updated without restarting discovery."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "claude/hooks/discovery_input_gate.py"
DESIGN = "# Collector design\n\n## Scope\nExtend the existing collector and archive source contract.\n"


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


@pytest.mark.parametrize("tool", ["Write", "Edit", "apply_patch"])
@pytest.mark.parametrize("state", ["committed", "untracked", "empty-committed", "todo-committed", "comment-committed", "fence-committed", "staged-only"])
def test_reusing_design_does_not_require_new_framing(tmp_path: Path, tool: str, state: str):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.name", "Fixture")
    git(tmp_path, "config", "user.email", "fixture@example.test")
    path = tmp_path / "openspec/changes/collector/design.md"
    path.parent.mkdir(parents=True)
    stubs = {"empty-committed": "# Design\n", "todo-committed": "# Design\n- **TODO**\n",
             "comment-committed": "# Design\n<!--\nOnly an agent note.\n-->\n",
             "fence-committed": "# Design\n```\n```\n"}
    path.write_text(stubs.get(state, DESIGN))
    if state != "untracked":
        git(tmp_path, "add", ".")
        if state != "staged-only":
            git(tmp_path, "commit", "-qm", "Existing reviewed design")
    if tool == "apply_patch":
        tool_input = {"command": "*** Begin Patch\n*** Update File: openspec/changes/collector/design.md\n@@\n-# Collector design\n+# Updated collector design\n*** End Patch"}
    else:
        tool_input = {"file_path": str(path), "content": DESIGN, "old_string": "collector", "new_string": "collector additions"}
    result = subprocess.run([sys.executable, str(HOOK)], cwd=tmp_path, input=json.dumps({
        "hook_event_name": "PreToolUse", "tool_name": tool, "cwd": str(tmp_path), "tool_input": tool_input,
    }), text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    if state == "committed":
        assert not result.stdout.strip(), result.stdout
    else:
        assert json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"] == "deny"
