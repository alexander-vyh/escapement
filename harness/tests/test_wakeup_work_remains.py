#!/usr/bin/env python3
"""Wakeup path must not launder a stop past session-fresh work (escapement-51w3).

The bug: would_block_stop returns ("allow", "wakeup_registered") for any
future-dated wakeup. In stop_hook.main() that allow is returned BEFORE
_verification_work_remains (verification_passed path only) and _winddown_override
(conversational path only) run — so a session can file a session-fresh bead,
schedule a trivial wakeup (a deploy/CI check), and stop with that work abandoned.
This is the exact shape of the cro-dashboard grain-adaptation deferral: fresh bead
filed, deploy-check wakeup scheduled, session stopped.

The fix wires the wakeup allow through the SAME watermark-scoped queue oracle the
task-mode wakeup path already uses (_check_bd_queue_implicit), via the testable
helper _wakeup_work_remains.

Business invariant
------------------
- wakeup + a SESSION-FRESH bead (created_at >= watermark) ⇒ BLOCK. The wakeup
  pauses for an external event; it does not discharge in-session work.
- wakeup + ONLY prior backlog (created_at < watermark) ⇒ ALLOW. A completed
  session that merely shares a repo with unrelated backlog must still stop —
  this is the regression the naive "any ready bead blocks" fix introduces.

Fragile implementations these tests REJECT
-------------------------------------------
- No check at all (today's bug): fails test_wakeup_blocks_on_session_fresh_work.
- Unscoped `bd ready` check (whole-repo backlog blocks): fails
  test_wakeup_allows_when_only_backlog — the negative control that proves scope.
- Prose-matching the wakeup prompt text: not exercised here and would pass the
  wrong cases; the banned approach per would_block_stop.py's own docstring.

Run: python3 -m pytest harness/tests/test_wakeup_work_remains.py -q
"""

from __future__ import annotations

import datetime as _dt
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "harness" / "bin"))

import stop_hook  # noqa: E402

W = _dt.datetime(2026, 7, 4, 4, 34, 0, tzinfo=_dt.timezone.utc)  # session watermark
FRESH = "2026-07-04T05:30:00+00:00"   # >= W  (session-fresh — filed this session)
OLD = "2026-07-01T04:00:00+00:00"     # <  W  (prior backlog)


def _item(id_: str, created_at: str) -> dict:
    return {"id": id_, "created_at": created_at}


def _bd_check_factory(decision: str, reason: str):
    """A stand-in _check_bd_queue_implicit that records it was called with the
    session's cwd + thread_dir (so we prove the helper delegates to the scoped
    oracle rather than inventing its own unscoped query)."""
    calls = {}

    def bd_check(cwd, thread_dir=None):
        calls["cwd"] = cwd
        calls["thread_dir"] = thread_dir
        return (decision, reason)

    bd_check.calls = calls
    return bd_check


def test_wakeup_blocks_on_session_fresh_work() -> None:
    """NEGATIVE CONTROL: a session-fresh bead present ⇒ the wakeup allow is
    overridden to a block. This is the dashboard grain-adaptation case."""
    bd_check = _bd_check_factory("block", "implicit_queue_scoped")
    result = stop_hook._wakeup_work_remains("/repo", pathlib.Path("/thread"), bd_check=bd_check)
    assert result is not None, "session-fresh work must block the wakeup stop"
    decision, reason = result
    assert decision == "block"
    assert reason == "implicit_queue_scoped"
    # proves delegation to the scoped oracle with the real session identity
    assert bd_check.calls["cwd"] == "/repo"
    assert bd_check.calls["thread_dir"] == pathlib.Path("/thread")


def test_wakeup_allows_when_only_backlog() -> None:
    """POSITIVE CONTROL: the scoped oracle allows (only prior backlog, drained
    session scope) ⇒ the wakeup stop stands. Rejects any unscoped whole-repo
    check that would trap a done session behind unrelated backlog."""
    bd_check = _bd_check_factory("allow", "implicit_queue_scoped_drained")
    result = stop_hook._wakeup_work_remains("/repo", pathlib.Path("/thread"), bd_check=bd_check)
    assert result is None, "backlog-only scope must let the wakeup stop stand"


def test_wakeup_allows_when_no_watermark() -> None:
    """The scoped oracle fails open (no watermark ⇒ advisory allow) ⇒ wakeup
    stop stands; the wakeup gate never hard-blocks on unscoped backlog."""
    bd_check = _bd_check_factory("allow", "scope_no_watermark")
    result = stop_hook._wakeup_work_remains("/repo", pathlib.Path("/thread"), bd_check=bd_check)
    assert result is None


def test_wakeup_allows_when_bd_unavailable() -> None:
    """Capability-probe: bd cannot resolve a queue ⇒ advisory allow (fail-open,
    never crash or hard-block the Stop path)."""
    bd_check = _bd_check_factory("allow", "scope_bd_failed")
    result = stop_hook._wakeup_work_remains("/repo", pathlib.Path("/thread"), bd_check=bd_check)
    assert result is None


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
