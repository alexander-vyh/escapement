#!/usr/bin/env python3
"""Corpus-bridge: Stop-gate scope decisions reach .gate-signal.jsonl (858.2 signal req).

Design: openspec/changes/gate-session-scope-model/design.md (Signal / Rule 2).
The half-life toolchain (claude/bin/gate_signal_*) and the running launchd monitor
read ONLY `.beads/.gate-signal.jsonl`. stop_hook.py logs to `incidents.jsonl`, so
without a bridge every scope decision is invisible to half-life review. This tests
that the harness-local writer emits the canonical _gate_signal line shape.

Run: python3 -m pytest harness/tests/test_gate_signal_bridge.py -q
"""

from __future__ import annotations

import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "harness" / "bin"))

import stop_hook  # noqa: E402


def test_writes_canonical_line_shape(tmp_path, monkeypatch) -> None:
    beads = tmp_path / ".beads"
    beads.mkdir()
    monkeypatch.setenv("BEADS_DIR", str(beads))

    stop_hook._record_gate_signal("block", "implicit_queue_scoped", "sess-abc", "implicit_queue_check")

    lines = (beads / ".gate-signal.jsonl").read_text().strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["gate"] == "continuation-harness"
    assert rec["decision"] == "block"
    assert rec["reason"] == "implicit_queue_scoped"
    assert rec["session_id"] == "sess-abc"
    assert rec["extras"] == {"notes": "implicit_queue_check"}
    assert rec["ts"].endswith("Z")


def test_advisory_allow_is_also_recorded(tmp_path, monkeypatch) -> None:
    """Per the design, scope_decision is emitted on EVERY path including allow."""
    beads = tmp_path / ".beads"
    beads.mkdir()
    monkeypatch.setenv("BEADS_DIR", str(beads))
    stop_hook._record_gate_signal("allow", "scope_no_watermark", "s1")
    rec = json.loads((beads / ".gate-signal.jsonl").read_text().strip())
    assert rec["decision"] == "allow" and rec["reason"] == "scope_no_watermark"


def test_no_beads_is_silent_noop(tmp_path, monkeypatch) -> None:
    """No locatable .beads/ ⇒ best-effort no-op, never raises."""
    monkeypatch.setenv("BEADS_DIR", str(tmp_path / "does-not-exist"))
    monkeypatch.chdir(tmp_path)  # tmp_path has no .beads/ to walk up into
    stop_hook._record_gate_signal("allow", "scope_bd_failed", "s2")  # must not raise


def test_log_incident_bridges_to_gate_signal(tmp_path, monkeypatch) -> None:
    """_log_incident must mirror the decision into .gate-signal.jsonl."""
    beads = tmp_path / ".beads"
    beads.mkdir()
    monkeypatch.setenv("BEADS_DIR", str(beads))
    stop_hook._log_incident({
        "timestamp": "2026-06-02T00:00:00Z",
        "session_id": "s3",
        "decision": "block",
        "reason": "tasks_remain_in_queue",
        "notes": "task_mode",
    })
    rec = json.loads((beads / ".gate-signal.jsonl").read_text().strip())
    assert rec["decision"] == "block" and rec["reason"] == "tasks_remain_in_queue"
    assert rec["session_id"] == "s3"


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
