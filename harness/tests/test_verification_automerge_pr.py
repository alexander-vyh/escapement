"""Deterministic Stop-gate backstop for repo-outcome-authorization: after a
verification_passed allow, an OPEN green PR in a repo that declared auto_merge_on_green
must BLOCK the stop — enforcement that does not rely on the agent reading any rule.

This lives on the verification_passed path, so "green" is a precondition established by
the caller: a red/unverified PR never reaches here (design anti-metric #1 — never
force-merge a red PR).

Oracle quality:
  - POSITIVE CONTROL: bd drained, no git work, repo authorizes + open PR
      -> block, reason=verification_passed_unmerged_automerge_pr
  - NEGATIVE CONTROLS:
      * repo does NOT authorize (no declaration / auto_merge false) -> allow (None).
        Never force a merge in a repo that did not grant it (anti-metric #2).
      * repo authorizes but NO open PR -> allow (None). Nothing to merge.
  - PRECEDENCE preserved: bd-queue block wins first; git-work block wins before automerge.
  - FRAGILE IMPL REJECTED: a check that blocks whenever an open PR exists, ignoring
    authorization — the not-authorized case must allow.
  - gate-design: the denial names the escape path (gh pr merge).
"""
import pathlib
import sys

BIN = pathlib.Path(__file__).resolve().parent.parent / "bin"
sys.path.insert(0, str(BIN))

import stop_hook as sh


def _bd_drained(cwd, thread_dir=None):
    return ("allow", "implicit_queue_scoped_drained")


def _bd_block(cwd, thread_dir=None):
    return ("block", "tasks_remain_in_queue")


_NO_GIT = lambda cwd: False
_GIT_WORK = lambda cwd: True


# --- POSITIVE CONTROL ------------------------------------------------------

def test_open_pr_in_automerge_repo_blocks(tmp_path):
    out = sh._verification_work_remains(
        "/repo", tmp_path,
        bd_check=_bd_drained, git_check=_NO_GIT,
        automerge_check=lambda cwd: 7,  # PR #7 open, repo authorizes
    )
    assert out == ("block", "verification_passed_unmerged_automerge_pr")


# --- NEGATIVE CONTROLS -----------------------------------------------------

def test_no_open_pr_allows(tmp_path):
    out = sh._verification_work_remains(
        "/repo", tmp_path,
        bd_check=_bd_drained, git_check=_NO_GIT,
        automerge_check=lambda cwd: None,  # authorizes but nothing open
    )
    assert out is None


def test_repo_not_authorized_allows(tmp_path):
    # authorize_check False => _unmerged_automerge_pr returns None => allow.
    # (Modeled here as automerge_check returning None for an unconfigured repo.)
    out = sh._verification_work_remains(
        "/repo", tmp_path,
        bd_check=_bd_drained, git_check=_NO_GIT,
        automerge_check=lambda cwd: None,
    )
    assert out is None


# --- PRECEDENCE ------------------------------------------------------------

def test_bd_queue_block_wins_first(tmp_path):
    out = sh._verification_work_remains(
        "/repo", tmp_path,
        bd_check=_bd_block, git_check=_NO_GIT,
        automerge_check=lambda cwd: 7,
    )
    assert out == ("block", "tasks_remain_in_queue")


def test_git_work_block_wins_before_automerge(tmp_path):
    out = sh._verification_work_remains(
        "/repo", tmp_path,
        bd_check=_bd_drained, git_check=_GIT_WORK,
        automerge_check=lambda cwd: 7,
    )
    assert out == ("block", "verification_passed_git_work_remains")


# --- the standalone check: authorization gates it (fragile impl rejected) ---

def test_unmerged_automerge_pr_requires_authorization(tmp_path):
    # authorize=False -> None even though a PR is open (fragile impl that keys only on
    # PR presence would wrongly return the number here).
    got = sh._unmerged_automerge_pr(
        "/repo",
        authorize_check=lambda cwd: False,
        pr_lookup=lambda cwd: 7,
    )
    assert got is None


def test_unmerged_automerge_pr_returns_number_when_authorized_and_open(tmp_path):
    got = sh._unmerged_automerge_pr(
        "/repo",
        authorize_check=lambda cwd: True,
        pr_lookup=lambda cwd: 7,
    )
    assert got == 7


def test_unmerged_automerge_pr_none_when_authorized_but_no_pr(tmp_path):
    got = sh._unmerged_automerge_pr(
        "/repo",
        authorize_check=lambda cwd: True,
        pr_lookup=lambda cwd: None,
    )
    assert got is None


def test_empty_cwd_allows(tmp_path):
    assert sh._unmerged_automerge_pr("", authorize_check=lambda cwd: True,
                                     pr_lookup=lambda cwd: 7) is None


# --- gate-design: denial names the escape path -----------------------------

def test_blocking_message_names_merge_escape_path(tmp_path):
    msg = sh._TASK_MODE_DISPLAY.get("verification_passed_unmerged_automerge_pr", "")
    assert msg, "verification_passed_unmerged_automerge_pr must have a display message"
    low = msg.lower()
    assert "gh pr merge" in low or "merge" in low
    assert "wakeup" in low  # the real blocker escape (if a merge genuinely can't happen)
