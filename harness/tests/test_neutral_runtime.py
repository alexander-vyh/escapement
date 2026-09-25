from __future__ import annotations

import sys
from pathlib import Path

import pytest

BIN = Path(__file__).resolve().parents[1] / "bin"
sys.path.insert(0, str(BIN))

from neutral_adapters import adapter_for  # noqa: E402
from neutral_contract import AmbiguousEvent, IncompleteEvent, normalize_event  # noqa: E402
from neutral_oracle import _registry, _fixture, run_fixture_suite  # noqa: E402
from neutral_supervisor import LifecycleBridge  # noqa: E402


def test_cross_client_oracle_observes_equivalent_behavior(tmp_path: Path) -> None:
    report = run_fixture_suite(tmp_path)

    assert set(report["clients"]) == {"pi", "codex", "claude"}
    assert report["negative_controls"]["unsupported_resume"] == "advisory-and-retained"
    assert report["pending_request_ids"]


def test_immediate_decision_does_not_start_supervisor(tmp_path: Path) -> None:
    registry = _registry()
    adapter = adapter_for("pi", client_version="fixture-pi-1.0", registry=registry)
    result = adapter.dispatch(_fixture("pi", "verified", "corr-immediate-1"))
    bridge = LifecycleBridge(tmp_path)

    assert result.decision.pending_action is None
    assert bridge.persist(result.decision) is False
    assert bridge.pending_count() == 0
    assert not bridge.state_path.exists()
    assert not any(tmp_path.iterdir())


def test_contract_rejects_missing_or_conflicting_identity() -> None:
    with pytest.raises(IncompleteEvent):
        normalize_event({"capability_id": "capability"})

    with pytest.raises(AmbiguousEvent):
        normalize_event(
            {
                "capability_id": "capability",
                "event_kind": "event",
                "session_id": "session-a",
                "sessionId": "session-b",
                "actor_id": "actor",
                "client": "pi",
                "client_version": "1.0",
                "correlation_id": "correlation",
                "payload": {},
            }
        )
