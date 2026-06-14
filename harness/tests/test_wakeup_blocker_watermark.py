"""Watermark-scope the wakeup-blocker gate.

Recovered from a pinned-deploy drift (bead claude-workflow-setup-d1e): a hand-edit
in the deployed copy scoped `_check_wakeup_blockers` to session-fresh blocked beads,
but it never reached main. Ported here with a test.

Business invariant: when a registered wakeup would release a task-mode stop, the
wakeup-blocker gate must audit only the blocked beads THIS session is responsible
for (created_at >= the session watermark). A pre-existing, dependency-blocked bead
from another session must NOT hold this session's wakeup gate hostage — that is the
same premature-block / over-scope bug the watermark already fixes for the implicit
bd queue (`_check_bd_queue_implicit`); this brings the wakeup-blocker path to parity.

Oracle quality:
  - NEGATIVE CONTROL (the recovered fix): a STALE unverified blocked bead (created
    before the watermark) is scoped out -> wakeup stands (allow). Pre-fix this blocked.
  - POSITIVE CONTROL: a SESSION-FRESH unverified blocked bead still blocks — the gate
    keeps its teeth for in-scope blockers.
  - BACKWARD COMPAT: no watermark (no contract) -> audit all (prior behavior),
    fail-safe toward block.
"""
import json
import pathlib
import sys

BIN = pathlib.Path(__file__).resolve().parent.parent / "bin"
sys.path.insert(0, str(BIN))

import stop_hook as sh

_WATERMARK = "2026-06-14T00:00:00+00:00"
_FRESH = "2026-06-14T01:00:00+00:00"   # after watermark (in scope)
_STALE = "2026-06-13T00:00:00+00:00"   # before watermark (out of scope)


def _thread_with_watermark(tmp_path):
    (tmp_path / "contract.json").write_text(
        json.dumps({"created_at": _WATERMARK, "goal": "g", "verification_command": "true"})
    )
    return tmp_path


def _bd_returns(blocked):
    def run_bd(args, **_kw):
        return blocked if (args and args[0] == "blocked") else []
    return run_bd


def _unverified_blocked(bead_id, created_at):
    # No blocker-verify: / blocker-waiver: -> blocker_satisfied() is not confirmed.
    return {"id": bead_id, "status": "blocked", "created_at": created_at,
            "description": "blocked on an upstream dependency"}


def test_stale_blocked_bead_scoped_out_allows_wakeup(tmp_path):
    """NEGATIVE CONTROL / recovered fix: a stale unverified blocker no longer holds the gate."""
    td = _thread_with_watermark(tmp_path)
    dec, _reason = sh._check_wakeup_blockers(
        {"repo_cwd": str(tmp_path)},
        run_bd=_bd_returns([_unverified_blocked("proj-1", _STALE)]),
        thread_dir=td,
    )
    assert dec == "allow"


def test_fresh_blocked_bead_still_blocks(tmp_path):
    """POSITIVE CONTROL: a session-fresh unverified blocker still blocks the wakeup path."""
    td = _thread_with_watermark(tmp_path)
    dec, reason = sh._check_wakeup_blockers(
        {"repo_cwd": str(tmp_path)},
        run_bd=_bd_returns([_unverified_blocked("proj-2", _FRESH)]),
        thread_dir=td,
    )
    assert (dec, reason) == ("block", "wakeup_blocker_unverified")


def test_no_watermark_audits_all(tmp_path):
    """BACKWARD COMPAT: no contract -> no watermark -> audit all (prior behavior)."""
    dec, reason = sh._check_wakeup_blockers(
        {"repo_cwd": str(tmp_path)},
        run_bd=_bd_returns([_unverified_blocked("proj-3", _STALE)]),
        thread_dir=tmp_path,  # no contract.json written -> watermark None
    )
    assert (dec, reason) == ("block", "wakeup_blocker_unverified")
