#!/usr/bin/env python3
"""Task 1.2 from openspec-beads-staleness/tasks.md: test archive-exclusion.

Constructs a fixture under a temp dir with one active change and one archived
change, each containing a `### Requirement:` block. Runs spec_index_build.py
against the fixture and asserts the resulting index contains EXACTLY one
entry sourced from the active change — proving the archive/** exclusion
invariant from spec-area-classifier.md.

This is the named, tested invariant the adversary panel flagged as the
single most load-bearing assumption in the design.

## Usage

    python3 claude/bin/tests/test_archive_exclusion.py

Exits 0 on success, 1 on assertion failure.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


_ACTIVE_SPEC = """\
<!-- Spec: active-capability -->

## Purpose

A capability that is actively in-flight; its specs must be indexed.

## Requirements

### Requirement: Active requirement that should be in the index

The active capability SHALL be visible to the spec-area classifier.

#### Scenario: Active spec is indexed
- **WHEN** the spec index builder runs
- **THEN** this requirement appears in `.beads/.spec-index.json`
"""

_ARCHIVED_SPEC = """\
<!-- Spec: archived-capability -->

## Purpose

A capability whose change has been archived; its specs must NOT be indexed
under openspec/changes/archive/. (Post-archive specs that get promoted to
openspec/specs/ ARE indexed; that's the lifecycle distinction.)

## Requirements

### Requirement: Archived requirement that must NOT appear in index

Archived change records must not generate false positives forever.

#### Scenario: Archived spec is skipped
- **WHEN** the spec index builder runs
- **THEN** this requirement is absent from `.beads/.spec-index.json`
"""


def build_fixture(root: Path) -> None:
    """Create the active + archived spec fixture under root."""
    active_dir = root / "openspec" / "changes" / "active-change" / "specs"
    archived_dir = root / "openspec" / "changes" / "archive" / "old-change" / "specs"
    active_dir.mkdir(parents=True)
    archived_dir.mkdir(parents=True)

    (active_dir / "active-capability.md").write_text(_ACTIVE_SPEC, encoding="utf-8")
    (archived_dir / "archived-capability.md").write_text(_ARCHIVED_SPEC, encoding="utf-8")

    # Pre-create the .beads/ dir so the script writes its index there.
    (root / ".beads").mkdir()


def run_builder(root: Path) -> Path:
    """Invoke spec_index_build.py against the fixture. Returns the index path."""
    script = (
        Path(__file__).resolve().parent.parent / "spec_index_build.py"
    )
    result = subprocess.run(
        ["uv", "run", str(script), "--project-dir", str(root)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        sys.stderr.write(
            f"spec_index_build.py exited {result.returncode}\n"
            f"stderr:\n{result.stderr}\n"
            f"stdout:\n{result.stdout}\n"
        )
        sys.exit(1)
    return root / ".beads" / ".spec-index.json"


def main() -> int:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        build_fixture(root)
        index_path = run_builder(root)

        with index_path.open(encoding="utf-8") as f:
            idx = json.load(f)

        requirements = idx["requirements"]

        # Assertion 1: exactly one requirement in the index
        if len(requirements) != 1:
            sys.stderr.write(
                f"FAIL: expected exactly 1 requirement, got {len(requirements)}\n"
                f"Requirements: {[r['requirement_id'] for r in requirements]}\n"
            )
            return 1

        # Assertion 2: the requirement came from the active change
        entry = requirements[0]
        source = entry["source_path"]
        if "/archive/" in source:
            sys.stderr.write(
                f"FAIL: indexed requirement came from archive/: {source}\n"
            )
            return 1
        if "active-change" not in source:
            sys.stderr.write(
                f"FAIL: indexed requirement not from active-change: {source}\n"
            )
            return 1

        # Assertion 3: archived requirement is genuinely absent
        for r in requirements:
            if "archive" in r["source_path"]:
                sys.stderr.write(
                    f"FAIL: archived requirement leaked into index: {r}\n"
                )
                return 1

        print(
            f"PASS: archive/** exclusion invariant verified. "
            f"Indexed 1 requirement from {source}; archived spec correctly skipped."
        )
        return 0


if __name__ == "__main__":
    sys.exit(main())
