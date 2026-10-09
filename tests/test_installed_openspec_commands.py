"""Claude retains OpenSpec operations when repo-local skills are removed."""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("operation", ["apply", "archive", "explore", "propose"])
def test_claude_plugin_ships_current_openspec_command(operation):
    installed = ROOT / "plugins/escapement-claude/commands/opsx" / f"{operation}.md"
    project = ROOT / ".claude/commands/opsx" / f"{operation}.md"
    assert installed.is_file(), f"installed Claude lacks {operation} after local removal"
    assert installed.read_bytes() == project.read_bytes()
