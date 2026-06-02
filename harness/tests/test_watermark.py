#!/usr/bin/env python3
"""Watermark resolver for session-scope gating (bead 858.1).

Design: openspec/changes/gate-session-scope-model/design.md Step 1.
The implicit Stop-path scopes the bd queue by a per-session START timestamp
(the "watermark"): items with created_at >= watermark are session-fresh
(block on them); older items are prior backlog (don't nag). The watermark is
DERIVED, never agent-asserted (bureaucracy: derive-not-assert / gate-design
Rule 3) — so it reads contract.created_at (system-stamped at init_contract)
first, then a SessionStart-written file.

Business invariant
------------------
resolve_watermark(thread_dir) returns the session-start datetime by priority:
  1. contract.json#created_at (the lean common case — no new state)
  2. {thread_dir}/scope_watermark.json#watermark (fallback for contract-less sessions)
  3. None  -> caller degrades to advisory-allow (NEVER a hard block on unscoped backlog)

Fragile implementations these tests REJECT
-------------------------------------------
- "only read the watermark file" -> fails test_contract_created_at_is_primary
  (the common contract-bearing session would get no watermark).
- "return now() when nothing found" -> fails test_no_source_returns_none
  (a bogus now-watermark would filter out ALL real session-fresh work => premature stop).

Run: python3 -m pytest harness/tests/test_watermark.py -q
"""

from __future__ import annotations

import datetime as _dt
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "harness" / "bin"))

from would_block_stop import resolve_watermark  # noqa: E402


def _write(p: pathlib.Path, obj: dict) -> None:
    p.write_text(json.dumps(obj), encoding="utf-8")


def test_contract_created_at_is_primary(tmp_path) -> None:
    """Contract present => watermark is contract.created_at (no file needed)."""
    ts = "2026-06-02T05:00:00+00:00"
    _write(tmp_path / "contract.json", {"goal": "x", "created_at": ts})
    got = resolve_watermark(tmp_path)
    assert got == _dt.datetime.fromisoformat(ts), (
        f"contract.created_at must be the primary watermark source; got {got!r}"
    )


def test_watermark_file_is_fallback(tmp_path) -> None:
    """No contract, scope_watermark.json present => use the file."""
    ts = "2026-06-02T04:30:00+00:00"
    _write(tmp_path / "scope_watermark.json", {"watermark": ts, "session_id": "s1"})
    got = resolve_watermark(tmp_path)
    assert got == _dt.datetime.fromisoformat(ts), (
        f"the SessionStart watermark file must be the fallback source; got {got!r}"
    )


def test_contract_wins_over_file(tmp_path) -> None:
    """Both present => contract.created_at wins (it is the session's own anchor)."""
    c_ts = "2026-06-02T05:00:00+00:00"
    f_ts = "2026-06-02T04:00:00+00:00"
    _write(tmp_path / "contract.json", {"created_at": c_ts})
    _write(tmp_path / "scope_watermark.json", {"watermark": f_ts})
    assert resolve_watermark(tmp_path) == _dt.datetime.fromisoformat(c_ts)


def test_malformed_contract_ts_falls_through_to_file(tmp_path) -> None:
    """A contract with an unparseable created_at must fall through, not crash/None-early."""
    f_ts = "2026-06-02T04:00:00+00:00"
    _write(tmp_path / "contract.json", {"created_at": "not-a-date"})
    _write(tmp_path / "scope_watermark.json", {"watermark": f_ts})
    assert resolve_watermark(tmp_path) == _dt.datetime.fromisoformat(f_ts)


def test_no_source_returns_none(tmp_path) -> None:
    """NEGATIVE CONTROL: no contract, no file => None (caller degrades to advisory-allow).

    Crucially NOT now() — a now-watermark would filter out every real session-fresh
    bead and re-create the premature-stop bug.
    """
    assert resolve_watermark(tmp_path) is None


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
