#!/usr/bin/env python3
"""Transitive parent root-walk (bead 858.3 — closes FN-1 grandchild hole).

Design: openspec/changes/gate-session-scope-model/design.md Step 2b.
_lookup_parent_id read ONE level, so a deep molecule (epic → sub-epic → leaf)
scoped `bd ready --parent` to the immediate sub-epic and missed ready siblings
under OTHER sub-epics of the same root ⇒ premature stop. The fix walks to the
ROOT; `bd ready --parent <root>` is transitive downward, covering the whole
molecule.

Business invariant
------------------
_lookup_parent_id(leaf) returns the TOPMOST ancestor (the molecule root), or
None when the task has no parent. A cycle or runaway chain must not hang the
hook (capped walk).

Run: python3 -m pytest harness/tests/test_root_walk.py -q
"""

from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "harness" / "bin"))

import task_mode_entry  # noqa: E402


def _chain(mapping: dict):
    """Fake run_show(id)->dict|None from {id: parent_id} (None parent = root)."""

    def run_show(tid):
        if tid not in mapping:
            return None
        return {"id": tid, "parent_id": mapping[tid]}

    return run_show


def test_three_level_returns_root() -> None:
    """leaf → sub-epic → epic(root) ⇒ returns the epic, not the sub-epic (FN-1)."""
    rs = _chain({"leaf": "subepic", "subepic": "epic", "epic": None})
    assert task_mode_entry._lookup_parent_id("leaf", run_show=rs) == "epic"


def test_two_level_returns_root() -> None:
    rs = _chain({"task": "epic", "epic": None})
    assert task_mode_entry._lookup_parent_id("task", run_show=rs) == "epic"


def test_no_parent_returns_none() -> None:
    """A task that is itself a root (no parent) ⇒ None (nothing to scope to)."""
    rs = _chain({"solo": None})
    assert task_mode_entry._lookup_parent_id("solo", run_show=rs) is None


def test_cycle_does_not_hang() -> None:
    """A → B → A cycle must terminate (cap/seen-guard), not loop forever."""
    rs = _chain({"a": "b", "b": "a"})
    # Should return *some* ancestor and terminate; the contract is "does not hang".
    result = task_mode_entry._lookup_parent_id("a", run_show=rs)
    assert result in ("a", "b")


def test_missing_task_returns_none() -> None:
    rs = _chain({})
    assert task_mode_entry._lookup_parent_id("ghost", run_show=rs) is None


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
