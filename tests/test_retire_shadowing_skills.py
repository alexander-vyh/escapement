"""A stale user copy of an Escapement skill must stop replacing the shipped one,
without anything the user wrote being lost."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "retire_shadowing_skills.py"


def _skill(root: Path, name: str, body: str) -> Path:
    path = root / name / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(f"---\nname: {name}\ndescription: d\n---\n{body}\n", encoding="utf-8")
    return path


def _run(shipped: Path, user: Path, backup: Path, *extra: str) -> str:
    result = subprocess.run(
        [sys.executable, "-B", str(SCRIPT), str(shipped), str(user), str(backup), *extra],
        capture_output=True, text=True, check=True,
    )
    return result.stdout


def test_stale_copy_is_moved_out_of_the_skills_dir_and_kept(tmp_path):
    shipped, user, backup = tmp_path / "shipped", tmp_path / "user", tmp_path / "retired"
    _skill(shipped, "brainstorming", "current")
    _skill(user, "brainstorming", "from May")

    out = _run(shipped, user, backup)

    assert not (user / "brainstorming").exists(), "stale copy still shadows the shipped skill"
    kept = list(backup.glob("*/brainstorming/SKILL.md"))
    assert len(kept) == 1 and "from May" in kept[0].read_text(encoding="utf-8")
    assert "brainstorming" in out and str(kept[0].parent) in out


def test_identical_unrelated_and_kept_skills_are_untouched(tmp_path):
    shipped, user, backup = tmp_path / "shipped", tmp_path / "user", tmp_path / "retired"
    _skill(shipped, "vocab", "same")
    _skill(user, "vocab", "same")
    _skill(user, "my-own-skill", "mine")
    _skill(shipped, "beads-execution", "current")
    _skill(user, "beads-execution", "managed by its own migration")

    out = _run(shipped, user, backup, "--keep", "beads-execution")

    for name in ("vocab", "my-own-skill", "beads-execution"):
        assert (user / name / "SKILL.md").is_file(), f"{name} was moved"
    assert not backup.exists() and out == ""


def test_extra_file_in_user_copy_counts_as_different(tmp_path):
    """A user who added notes to their copy gets it preserved, not ignored."""
    shipped, user, backup = tmp_path / "shipped", tmp_path / "user", tmp_path / "retired"
    _skill(shipped, "build", "same")
    _skill(user, "build", "same")
    (user / "build" / "notes.md").write_text("mine", encoding="utf-8")

    _run(shipped, user, backup)

    assert not (user / "build").exists()
    assert list(backup.glob("*/build/notes.md"))
