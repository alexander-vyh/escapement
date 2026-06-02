#!/usr/bin/env python3
"""Watermark-scoped implicit Stop-path (beads 858.2 + 858.4).

Design: openspec/changes/gate-session-scope-model/design.md Steps 2 + 2c.
THE delicate cut: _check_bd_queue_implicit must block on SESSION-FRESH work
(created_at >= watermark) and NOT nag on older backlog — without re-opening
the premature-stop bug (false-negative = rank-1 danger).

Business invariant
------------------
- Session-fresh work (created_at >= watermark) in ANY of {in_progress, ready,
  open} ⇒ BLOCK (don't abandon it).
- Only older backlog (created_at < watermark) ⇒ ALLOW (the a2n incident: a
  completed session is not trapped by unrelated prior-session backlog).
- No watermark / bd failure ⇒ advisory ALLOW (never a hard block on unscoped
  backlog; never substitute now()).
- Capability-probe (858.4): a worktree with no .beads/ dir must still be scoped
  (gate via bd, not via a directory check — the E-1 bug PR #12 missed here).

Fragile implementations these tests REJECT (each NC kills one named shortcut)
---------------------------------------------------------------------------
- NC-2 (FN-4): filtering only ready+in_progress (dropping --status=open) lets a
  session-fresh BLOCKED bead slip ⇒ premature stop. test_fn4_fresh_blocked_open_blocks.
- "no .beads dir ⇒ allow" (the E-1 directory-proxy) ⇒ test_worktree_no_dir_still_scopes.
- "watermark missing ⇒ block everything" (coercive) / "⇒ use now()" (filters all
  fresh ⇒ premature stop) ⇒ test_no_watermark_degrades_to_allow.

Run: python3 -m pytest harness/tests/test_implicit_queue_scope.py -q
"""

from __future__ import annotations

import datetime as _dt
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "harness" / "bin"))

import stop_hook  # noqa: E402

W = _dt.datetime(2026, 6, 2, 5, 0, 0, tzinfo=_dt.timezone.utc)  # the watermark
FRESH = "2026-06-02T05:30:00+00:00"   # >= W  (session-fresh)
OLD = "2026-06-02T04:00:00+00:00"     # <  W  (prior backlog)


def _item(id_: str, created_at: str) -> dict:
    return {"id": id_, "created_at": created_at}


def _runner(in_progress=None, ready=None, open_=None, fail=False):
    """Fake run_bd(args)->list|None keyed on the bd subcommand."""
    ip, rd, op = in_progress or [], ready or [], open_ or []

    def run_bd(args):
        if fail:
            return None
        if "--status=in_progress" in args:
            return ip
        if args[:1] == ["ready"]:
            return rd
        if "--status=open" in args:
            return op
        return []

    return run_bd


def _check(cwd="/repo", watermark=W, run_bd=None):
    return stop_hook._check_bd_queue_implicit(cwd, watermark=watermark, run_bd=run_bd)


def test_incident_replay_allows() -> None:
    """The a2n incident: every queue item predates the watermark ⇒ ALLOW."""
    rb = _runner(in_progress=[_item("a2n", OLD)], ready=[_item("uf5", OLD)], open_=[_item("385", OLD)])
    decision, reason = _check(run_bd=rb)
    assert decision == "allow", f"prior-session backlog must not trap a completed session; got {decision}/{reason}"


def test_fresh_in_progress_blocks() -> None:
    """NC-1: a session-fresh in_progress bead ⇒ BLOCK (never abandon in-scope work)."""
    rb = _runner(in_progress=[_item("x.1", FRESH)], ready=[_item("old", OLD)])
    decision, _ = _check(run_bd=rb)
    assert decision == "block"


def test_fresh_ready_blocks() -> None:
    """Positive control: a session-fresh ready bead ⇒ BLOCK."""
    rb = _runner(ready=[_item("x.2", FRESH)])
    decision, _ = _check(run_bd=rb)
    assert decision == "block"


def test_fn4_fresh_blocked_open_blocks() -> None:
    """NC-2 / FN-4: a session-fresh bead that is OPEN with unmet deps (in neither
    ready nor in_progress) ⇒ BLOCK. Rejects any impl whose query set omits open."""
    rb = _runner(in_progress=[], ready=[], open_=[_item("x.3", FRESH)])
    decision, reason = _check(run_bd=rb)
    assert decision == "block", (
        f"a session-fresh blocked bead (only in `open`) must still block — dropping "
        f"--status=open re-opens FN-4; got {decision}/{reason}"
    )


def test_no_watermark_degrades_to_allow() -> None:
    """No watermark ⇒ advisory ALLOW (never hard-block unscoped backlog, never now())."""
    rb = _runner(ready=[_item("anything", FRESH)])
    decision, reason = _check(watermark=None, run_bd=rb)
    assert decision == "allow", f"absent watermark must fail-open to advisory allow; got {decision}/{reason}"


def test_bd_failure_degrades_to_allow() -> None:
    """bd cannot resolve a queue ⇒ advisory ALLOW (capability-probe degrade on FAILURE)."""
    rb = _runner(fail=True)
    decision, _ = _check(run_bd=rb)
    assert decision == "allow"


def test_worktree_no_dir_still_scopes() -> None:
    """858.4 / E-1: a worktree path with no literal .beads/ dir must STILL be scoped
    via bd (capability-probe), not allowed by a directory check."""
    rb = _runner(ready=[_item("fresh", FRESH)])
    # cwd points at a path with no .beads dir; with run_bd injected the function must
    # not short-circuit on the missing directory.
    decision, _ = _check(cwd="/tmp/worktree-no-beads", run_bd=rb)
    assert decision == "block", "the implicit path must gate worktrees via bd, not via a .beads/ dir check"


def test_unparseable_created_at_is_treated_in_scope() -> None:
    """Fail-safe: an item with a missing/bad created_at biases to BLOCK (avoid a
    premature stop), not to allow."""
    rb = _runner(ready=[{"id": "no-ts"}])
    decision, _ = _check(run_bd=rb)
    assert decision == "block"


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
