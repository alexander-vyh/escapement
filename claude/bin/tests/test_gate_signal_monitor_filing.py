"""Tests for the gate-signal monitor's bead-filing report contract.

The monitor is the only automated channel from the guardrail back-stage to
the one human who can change a rule. `_file_bead()` returns `None` when
`bd create` fails or when its stdout cannot be parsed, and for four months
all three call sites appended `{"action": "filed"}` regardless. The weekly
log therefore printed `[FILED]` 45 times while exactly one bead reached the
queue, and the discrepancy was invisible.

The absence of any `deduped` record is what makes the failure self-proving:
dedup matches against *open* beads, so a genuinely filed finding deduplicates
on every later run. Forty-five filings and zero dedups cannot both be true.

Two load-bearing behaviors:

  1. Positive control — when `bd create` succeeds, the action MUST be `filed`
     and MUST carry the new bead id.

  2. Negative control — when `bd create` fails, the action MUST be
     `file-failed`, MUST NOT claim an id, and `main()` MUST exit non-zero.
     A monitor that reports success on a dark channel is worse than one that
     does not run: it manufactures the appearance of an empty queue.

Run from anywhere:
  python3 -m pytest claude/bin/tests/test_gate_signal_monitor_filing.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_bin_dir = Path(__file__).resolve().parent.parent
if str(_bin_dir) not in sys.path:
    sys.path.insert(0, str(_bin_dir))

import gate_signal_monitor as mon  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def summary_with_one_finding():
    """Minimal summary that triggers exactly one mock-bureaucracy filing."""
    return {
        "judge_availability": {"is_outage": False},
        "mock_bureaucracy_risk": [
            {"gate": "file-complexity", "ratio": 5.52, "waivers": 1554, "denies": 341},
        ],
        "shirking_fp_heavy": [],
    }


# ---------------------------------------------------------------------------
# Positive control — a real filing is reported as filed, with its id
# ---------------------------------------------------------------------------

def test_successful_filing_reports_filed_with_id(
    summary_with_one_finding, tmp_path, monkeypatch,
):
    monkeypatch.setattr(mon, "_file_bead", lambda *a, **k: "escapement-abc")
    monkeypatch.setattr(mon, "_list_open_monitor_beads", lambda *a, **k: [])

    actions = mon.file_concerning_patterns(
        summary_with_one_finding, tmp_path, "7d",
    )

    assert len(actions) == 1
    assert actions[0]["action"] == "filed"
    assert actions[0]["id"] == "escapement-abc"


# ---------------------------------------------------------------------------
# Negative control — the regression that ran dark for four months
# ---------------------------------------------------------------------------

def test_failed_filing_is_not_reported_as_filed(
    summary_with_one_finding, tmp_path, monkeypatch,
):
    """`bd create` failing MUST NOT be recorded as a successful filing."""
    monkeypatch.setattr(mon, "_file_bead", lambda *a, **k: None)
    monkeypatch.setattr(mon, "_list_open_monitor_beads", lambda *a, **k: [])

    actions = mon.file_concerning_patterns(
        summary_with_one_finding, tmp_path, "7d",
    )

    assert len(actions) == 1
    assert actions[0]["action"] == "file-failed", (
        "a finding that never reached the queue was reported as filed"
    )
    assert "id" not in actions[0]


def test_failed_filing_never_claims_an_id(
    summary_with_one_finding, tmp_path, monkeypatch,
):
    """No action may carry `id: None` — the shape that made this invisible."""
    monkeypatch.setattr(mon, "_file_bead", lambda *a, **k: None)
    monkeypatch.setattr(mon, "_list_open_monitor_beads", lambda *a, **k: [])

    actions = mon.file_concerning_patterns(
        summary_with_one_finding, tmp_path, "7d",
    )

    for a in actions:
        assert a.get("id") is not None or "id" not in a


def test_every_filing_call_site_is_guarded(
    tmp_path, monkeypatch,
):
    """All three finding classes must honour the failure value.

    The judge-outage, mock-bureaucracy and shirking-FP branches each call
    `_file_bead` independently. A guard added to one and missed on another
    leaves that finding class dark, which is exactly how this shipped.
    """
    monkeypatch.setattr(mon, "_file_bead", lambda *a, **k: None)
    monkeypatch.setattr(mon, "_list_open_monitor_beads", lambda *a, **k: [])

    summary = {
        "judge_availability": {
            "is_outage": True,
            "unavailable": 3954,
            "stop_events": 17044,
            "rate": 0.232,
            "by_repo": {"cake": 1573, "dashboards": 1238},
        },
        "mock_bureaucracy_risk": [
            {"gate": "file-complexity", "ratio": 5.52, "waivers": 1554, "denies": 341},
        ],
        "shirking_fp_heavy": [
            {
                "category": "pre-existing",
                "waivers": 1584,
                "denies": 96,
                "ratio": 16.5,
            },
        ],
    }

    actions = mon.file_concerning_patterns(summary, tmp_path, "120d")

    assert len(actions) == 3, "expected one action per finding class"
    assert {a["action"] for a in actions} == {"file-failed"}, (
        "a call site still reports success when bd create fails"
    )
