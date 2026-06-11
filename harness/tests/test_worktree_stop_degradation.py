"""A3 — stop_hook._check_task_mode_queue worktree degradation.

WHY THIS EXISTS
A cake session operated inside a pre-existing foreign worktree. `_check_task_mode_queue`
keys its bd-unavailable degradation on `has_beads_dir = (Path(repo_cwd)/".beads").exists()`.
A git worktree has NO literal `.beads/` directory (it uses `.beads/redirect` or a
`.git`-file gitdir pointer), so when bd cannot resolve a queue the gate degrades to
("allow","task_mode_bd_unavailable") — silently ungating the Stop gate. That is the
same laundering channel R2/R3 closed from a different angle.

THE FIX (A3): when `repo_cwd` is a LINKED WORKTREE (its `.git` is a FILE containing
`gitdir: ...`) whose RESOLVED MAIN REPO has `.beads/`, a bd-unavailable result must
degrade to BLOCK, not allow. A genuinely non-beads cwd (no `.git` file, no resolvable
main `.beads/`) keeps the current allow.

FRAGILE IMPLEMENTATION REJECTED
- "dir-check degradation": has_beads_dir = (cwd/'.beads').exists() ALONE. Defeated by
  test_foreign_worktree_bd_unavailable_blocks (worktree .git file -> main .beads/ ->
  bd None -> must BLOCK) paired with test_genuine_non_beads_cwd_still_allows.

These tests are hermetic: injected run_bd (returns None to simulate bd-unavailable),
fabricated worktree layouts under tmp_path, no real git, no real bd.

Run: python3 -m pytest harness/tests/test_worktree_stop_degradation.py -q
"""

from __future__ import annotations

import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "harness" / "bin"))

import stop_hook  # noqa: E402


def _bd_unavailable(args):
    """Simulate bd that cannot resolve any queue (the worktree case where bd has
    no DB)."""
    return None


def _make_worktree(tmp_path, *, main_has_beads: bool):
    """Fabricate a linked-worktree layout. The worktree's `.git` is a FILE
    pointing at the main repo's worktrees admin dir (the real git marker).
    Returns the worktree path (used as repo_cwd)."""
    main = tmp_path / "main"
    (main / ".git" / "worktrees" / "wt").mkdir(parents=True)
    if main_has_beads:
        (main / ".beads").mkdir()
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {main}/.git/worktrees/wt\n", encoding="utf-8")
    return wt


def test_foreign_worktree_bd_unavailable_blocks(tmp_path):
    """POSITIVE CONTROL / the laundering channel: repo_cwd is a linked worktree
    whose resolved main repo has .beads/, and bd is unavailable -> must BLOCK.
    The current dir-only check allows here (the bug)."""
    wt = _make_worktree(tmp_path, main_has_beads=True)
    session_mode = {"repo_cwd": str(wt), "parent_id": "cake-m95.4"}
    decision, reason = stop_hook._check_task_mode_queue(session_mode, run_bd=_bd_unavailable)
    assert decision == "block", (
        "a foreign beads worktree with bd unavailable must not free-allow Stop "
        f"(the laundering channel); got {decision}/{reason}"
    )


def test_genuine_non_beads_cwd_still_allows(tmp_path):
    """NEGATIVE CONTROL: a genuinely non-beads cwd (no .git file, no .beads/ dir,
    no resolvable main .beads/) with bd unavailable keeps the current graceful
    allow. A3 must not over-block real non-beads contexts."""
    plain = tmp_path / "plain"
    plain.mkdir()
    session_mode = {"repo_cwd": str(plain), "parent_id": "cake-m95.4"}
    decision, reason = stop_hook._check_task_mode_queue(session_mode, run_bd=_bd_unavailable)
    assert (decision, reason) == ("allow", "task_mode_bd_unavailable"), (
        f"a genuine non-beads cwd must still degrade to allow; got {decision}/{reason}"
    )


def test_plain_git_worktree_bd_unavailable_allows(tmp_path):
    """NEGATIVE CONTROL: a linked worktree whose MAIN repo has NO .beads/ is a
    plain-git multi-worktree repo — not a beads context. bd unavailable here must
    still allow (over-block control: A3 keys on the MAIN repo's .beads/, not merely
    on being a worktree)."""
    wt = _make_worktree(tmp_path, main_has_beads=False)
    session_mode = {"repo_cwd": str(wt), "parent_id": "cake-m95.4"}
    decision, reason = stop_hook._check_task_mode_queue(session_mode, run_bd=_bd_unavailable)
    assert decision == "allow", (
        "a plain-git worktree (main repo has no .beads/) is not a beads context; "
        f"bd-unavailable must still allow; got {decision}/{reason}"
    )


def test_real_beads_dir_bd_unavailable_still_blocks(tmp_path):
    """REGRESSION GUARD: the existing behavior — a real beads repo (literal .beads/
    at cwd) with bd unavailable already BLOCKS. A3 must not weaken this."""
    (tmp_path / ".beads").mkdir()
    session_mode = {"repo_cwd": str(tmp_path), "parent_id": "cake-m95.4"}
    decision, reason = stop_hook._check_task_mode_queue(session_mode, run_bd=_bd_unavailable)
    assert decision == "block", (
        f"a real beads repo with bd unavailable must still block; got {decision}/{reason}"
    )


def test_worktree_with_ready_work_still_blocks(tmp_path):
    """POSITIVE CONTROL: a foreign beads worktree where bd DOES resolve ready work
    blocks as normal (A3 only changes the bd-UNAVAILABLE degradation, not the
    ready-work path)."""
    wt = _make_worktree(tmp_path, main_has_beads=True)
    session_mode = {"repo_cwd": str(wt), "parent_id": "cake-m95.4"}

    def run_bd(args):
        if args[0] == "ready":
            return [{"id": "cake-m95.4.2"}]
        return []

    decision, reason = stop_hook._check_task_mode_queue(session_mode, run_bd=run_bd)
    assert (decision, reason) == ("block", "tasks_remain_in_queue"), (
        f"ready work in a worktree must still block; got {decision}/{reason}"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
