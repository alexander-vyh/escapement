#!/usr/bin/env python3
"""SessionStart watermark writer (bead 858.8).

Design: openspec/changes/gate-session-scope-model/design.md Step 1 (fallback).
A contract-less session has no contract.created_at, so resolve_watermark would
return None and the implicit Stop-path could not scope. This SessionStart hook
writes {thread_dir}/scope_watermark.json FIRST-WRITE-WINS so a resumed/compacted
session keeps its ORIGINAL start (a later watermark would mis-classify earlier
session-fresh work as backlog → premature stop).

Run: python3 -m pytest harness/tests/test_session_watermark.py -q
"""

from __future__ import annotations

import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "harness" / "bin"))

import session_watermark  # noqa: E402
from would_block_stop import resolve_watermark  # noqa: E402
import datetime as _dt


def test_writes_watermark_file(tmp_path) -> None:
    session_watermark.write_session_watermark(tmp_path, "sess-1", "2026-06-02T05:00:00+00:00")
    data = json.loads((tmp_path / "scope_watermark.json").read_text())
    assert data["watermark"] == "2026-06-02T05:00:00+00:00"
    assert data["session_id"] == "sess-1"


def test_first_write_wins(tmp_path) -> None:
    """A resumed session must keep its ORIGINAL watermark, not overwrite it."""
    session_watermark.write_session_watermark(tmp_path, "sess-1", "2026-06-02T05:00:00+00:00")
    session_watermark.write_session_watermark(tmp_path, "sess-1", "2026-06-02T09:00:00+00:00")
    data = json.loads((tmp_path / "scope_watermark.json").read_text())
    assert data["watermark"] == "2026-06-02T05:00:00+00:00", "must NOT overwrite the original start"


def test_resolve_watermark_reads_it_back(tmp_path) -> None:
    """End-to-end: the written file is consumed by the gate's resolver."""
    session_watermark.write_session_watermark(tmp_path, "sess-1", "2026-06-02T05:00:00+00:00")
    got = resolve_watermark(tmp_path)  # no contract present ⇒ falls to the file
    assert got == _dt.datetime.fromisoformat("2026-06-02T05:00:00+00:00")


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
