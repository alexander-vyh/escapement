"""Fix 1 (shirking false-negative index-0): a `verification_passed` stop must
also be blocked when git work remains, not only when the bd queue is non-empty.

Business invariant: a passing contract verifies its own narrow oracle — it does
NOT authorize stopping while the session still owns unfinished work. The B3 path
already re-checks the bd queue after verification_passed; it omitted git work
(dirty tracked files / unpushed commits), so the index-0 miss ("Harness cleared.
Go ahead." → stopped with work remaining) slipped through. The conversational
path (`_winddown_override`) already checks both bd AND git; this brings the
verification_passed path to parity.

Oracle quality:
  - NEGATIVE CONTROL (the regression): bd drained BUT git work remains -> block.
    This is the index-0 shape and the case that previously slipped.
  - POSITIVE CONTROL: bd drained AND no git work -> None (a genuinely-finished
    verified stop is still allowed — the fix must not nag legitimate stops).
  - bd queue blocking still wins (preserves the existing B3 behavior).
  - Fragile impl rejected: checking only the bd queue (the pre-fix behavior) —
    the bd-drained + git-work case must fail it.
"""
import pathlib
import sys

BIN = pathlib.Path(__file__).resolve().parent.parent / "bin"
sys.path.insert(0, str(BIN))

import stop_hook as sh


def _bd_block(cwd, thread_dir=None):
    return ("block", "tasks_remain_in_queue")


def _bd_drained(cwd, thread_dir=None):
    return ("allow", "implicit_queue_scoped_drained")


def test_bd_drained_but_git_work_remains_blocks(tmp_path):
    """NEGATIVE CONTROL / index-0 regression: clean bead queue, dirty/unpushed git."""
    out = sh._verification_work_remains(
        "/repo", tmp_path, bd_check=_bd_drained, git_check=lambda cwd: True,
    )
    assert out is not None
    assert out[0] == "block"
    assert out[1] == "verification_passed_git_work_remains"


def test_bd_drained_and_no_git_work_allows(tmp_path):
    """POSITIVE CONTROL: genuinely finished verified stop is still allowed."""
    out = sh._verification_work_remains(
        "/repo", tmp_path, bd_check=_bd_drained, git_check=lambda cwd: False,
    )
    assert out is None


def test_bd_queue_block_preserved(tmp_path):
    """Existing B3 behavior (bd queue non-empty) still blocks, with its own reason."""
    out = sh._verification_work_remains(
        "/repo", tmp_path, bd_check=_bd_block, git_check=lambda cwd: False,
    )
    assert out == ("block", "tasks_remain_in_queue")


def test_no_cwd_no_git_check(tmp_path):
    """Empty cwd: git check is skipped (mirrors _git_work_remains' own guard)."""
    out = sh._verification_work_remains(
        "", tmp_path, bd_check=_bd_drained, git_check=lambda cwd: True,
    )
    assert out is None


def test_blocking_message_names_escape_path(tmp_path):
    """gate-design: the denial for the new reason names an agent-invokable way out."""
    msg = sh._TASK_MODE_DISPLAY.get("verification_passed_git_work_remains", "")
    assert msg, "verification_passed_git_work_remains must have a display message"
    low = msg.lower()
    # must point at the real escape paths: commit/push the work, or schedule a wakeup
    assert ("push" in low or "commit" in low) and "wakeup" in low
