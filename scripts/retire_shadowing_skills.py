#!/usr/bin/env python3
"""Move stale user-level copies of Escapement skills out of the way.

Codex and Pi both read user skills from ``~/.agents/skills``. Pi lets a user
skill win over a package skill of the same name, so an old copy there (for
example one migrated from Claude months ago) silently replaces the skill
Escapement ships, and Codex shows the model both. A copy that differs from the
shipped skill is moved, never deleted, to a dated backup directory OUTSIDE
``~/.agents/skills``: a renamed directory inside it would still be loaded,
because hosts read the ``name`` from SKILL.md, not the directory name.

Identical copies are left alone (they shadow nothing), and so is every user
skill whose name Escapement does not ship.
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


def _same_tree(left: Path, right: Path) -> bool:
    comparison = filecmp.dircmp(left, right)
    if comparison.left_only or comparison.right_only or comparison.funny_files:
        return False
    _, mismatch, errors = filecmp.cmpfiles(left, right, comparison.common_files, shallow=False)
    if mismatch or errors:
        return False
    return all(_same_tree(left / sub, right / sub) for sub in comparison.common_dirs)


def retire(shipped: Path, user: Path, backup_root: Path, keep: set[str]) -> list[tuple[str, Path]]:
    """Move each differing user copy of a shipped skill; return (name, backup)."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    moved: list[tuple[str, Path]] = []
    for skill in sorted(path.parent for path in shipped.glob("*/SKILL.md")):
        name = skill.name
        copy = user / name
        if name in keep or not (copy / "SKILL.md").is_file() or copy.is_symlink():
            continue
        if _same_tree(skill, copy):
            continue
        backup = backup_root / stamp / name
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(copy), str(backup))
        moved.append((name, backup))
    return moved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("shipped", type=Path, help="skills directory Escapement ships")
    parser.add_argument("user", type=Path, help="user skills directory, e.g. ~/.agents/skills")
    parser.add_argument("backup_root", type=Path, help="where retired copies are kept")
    parser.add_argument("--keep", action="append", default=[], help="skill name managed elsewhere")
    args = parser.parse_args(argv)

    if not args.user.is_dir():
        return 0
    for name, backup in retire(args.shipped, args.user, args.backup_root, set(args.keep)):
        print(f"moved stale user copy of skill '{name}' aside so Escapement's current one loads; backup: {backup}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
