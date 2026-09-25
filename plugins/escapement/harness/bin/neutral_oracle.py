#!/usr/bin/env python3
"""Independent behavioral oracle for the Pi, Codex, and Claude adapters."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from neutral_adapters import AdapterResult, adapter_for
from neutral_contract import IncompleteEvent
from neutral_registry import (
    CAPABILITY_ID,
    AdapterEvidence,
    CapabilityRegistry,
    CapabilitySpec,
    default_registry,
)
from neutral_supervisor import LifecycleBridge


_CLIENTS = ("pi", "codex", "claude")
_EXPECTED_PENDING = {
    "action": "ask",
    "enforcement": "hard",
    "state_transition": "outcome-awaiting",
    "operation": "resume-after-outcome",
}


def _registry() -> CapabilityRegistry:
    registry = default_registry()
    for client in _CLIENTS:
        registry.set_evidence(
            CAPABILITY_ID,
            AdapterEvidence(
                client=client,
                client_version=f"fixture-{client}-1.0",
                realization="hard",
                fixture_hash=f"fixture:{client}:outcome-pending:v1",
                native_event_ref=f"native:{client}:lifecycle-pending",
                point_of_effect=f"native-{client}-lifecycle-boundary",
            ),
        )
    return registry


def _fixture(client: str, status: str, correlation_id: str = "corr-pending-1") -> dict[str, Any]:
    common = {
        "capability_id": CAPABILITY_ID,
        "session_id": "session-fixture-1",
        "actor_id": f"{client}-fixture-agent",
        "correlation_id": correlation_id,
        "repository": "fixture-repository",
        "cwd": "/fixture/worktree",
    }
    if client == "pi":
        return {
            **common,
            "event": "before_agent_start",
            "version": f"fixture-{client}-1.0",
            "input": {"outcome_status": status},
        }
    if client == "codex":
        return {
            **common,
            "hook_event_name": "Stop",
            "version": f"fixture-{client}-1.0",
            "payload": {"outcome_status": status},
        }
    if client == "claude":
        return {
            **common,
            "hook_event_name": "Stop",
            "version": f"fixture-{client}-1.0",
            "outcome": {"outcome_status": status},
        }
    raise AssertionError(f"unknown fixture client: {client}")


def _semantic(result: AdapterResult) -> tuple[str, str, str, str | None]:
    pending = result.decision.pending_action
    return (
        result.decision.action,
        result.decision.enforcement,
        result.decision.state_transition,
        pending.operation if pending else None,
    )


def _expect(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_fixture_suite(state_root: str | Path | None = None) -> dict[str, Any]:
    """Return observed evidence, raising on any positive or negative failure."""
    registry = _registry()
    root = Path(state_root) if state_root is not None else Path(tempfile.mkdtemp(prefix="neutral-oracle-"))
    client_reports: dict[str, dict[str, Any]] = {}
    pending_ids: set[str] = set()

    for client in _CLIENTS:
        adapter = adapter_for(
            client,
            client_version=f"fixture-{client}-1.0",
            registry=registry,
        )
        immediate = adapter.dispatch(_fixture(client, "verified", "corr-verified-1"))
        _expect(_semantic(immediate) == ("continue", "hard", "outcome-verified", None), f"{client} immediate mismatch")
        _expect(not immediate.native.blocked and immediate.native.executed, f"{client} immediate was not applied")

        bridge = LifecycleBridge(root / client)
        pending = adapter.dispatch(_fixture(client, "pending"))
        _expect(_semantic(pending) == tuple(_EXPECTED_PENDING.values()), f"{client} pending mismatch")
        _expect(pending.native.blocked and not pending.native.executed, f"{client} pending was not held")
        _expect(bridge.persist(pending.decision), f"{client} pending was not persisted")
        _expect(bridge.pending_count() == 1, f"{client} pending count mismatch")
        pending_ids.add(pending.decision.pending_action.request_id)

        resumed = bridge.resume(pending.decision.pending_action.request_id, adapter)
        _expect(resumed.state_transition == "outcome-resumed", f"{client} did not resume")
        _expect(resumed.executed and resumed.enforcement == "hard", f"{client} resume was not hard")
        _expect(bridge.pending_count() == 0, f"{client} pending state was not cleared")
        _expect(
            bridge.completed_snapshot()[pending.decision.pending_action.request_id]["result"]
            == resumed.to_dict(),
            f"{client} native resume evidence was not persisted",
        )
        client_reports[client] = {
            "immediate": immediate.native.to_dict(),
            "pending": pending.native.to_dict(),
            "resumed": resumed.to_dict(),
        }

    _expect(len(pending_ids) == 1, "semantic pending request identity diverged by client")

    unsupported = adapter_for(
        "claude",
        client_version="fixture-claude-1.0",
        registry=registry,
        resume_supported=False,
    )
    unsupported_bridge = LifecycleBridge(root / "unsupported")
    unsupported_pending = unsupported.dispatch(_fixture("claude", "pending", "corr-unsupported-1"))
    unsupported_bridge.persist(unsupported_pending.decision)
    advisory = unsupported_bridge.resume(
        unsupported_pending.decision.pending_action.request_id,
        unsupported,
    )
    _expect(advisory.enforcement == "advisory", "unsupported resume claimed hard enforcement")
    _expect(advisory.state_transition == "outcome-advisory", "unsupported resume hid its limitation")
    _expect(not advisory.executed, "unsupported resume auto-allowed the pending action")
    _expect(unsupported_bridge.pending_count() == 1, "unsupported pending action was discarded")

    missing_identity = _fixture("pi", "pending")
    del missing_identity["actor_id"]
    try:
        adapter_for("pi", client_version="fixture-pi-1.0", registry=registry).dispatch(missing_identity)
    except IncompleteEvent:
        pass
    else:
        raise AssertionError("missing actor identity was silently inferred")

    version_mismatch = _fixture("pi", "pending", "corr-version-mismatch-1")
    version_mismatch["version"] = "untrusted-client-version"
    mismatch = adapter_for(
        "pi", client_version="fixture-pi-1.0", registry=registry
    ).dispatch(version_mismatch)
    _expect(mismatch.decision.enforcement == "advisory", "version mismatch claimed hard evidence")
    _expect(not mismatch.native.executed, "version mismatch auto-allowed a pending action")

    empty_registry = CapabilityRegistry(
        [
            CapabilitySpec(
                capability_id=CAPABILITY_ID,
                required_event_fields=("outcome_status",),
                actions=("allow", "ask", "deny", "continue", "record"),
                evidence_requirements=("installed_client_version",),
            )
        ]
    )
    unavailable = adapter_for(
        "pi", client_version="fixture-pi-1.0", registry=empty_registry
    ).dispatch(_fixture("pi", "pending", "corr-unavailable-1"))
    _expect(unavailable.decision.enforcement == "unavailable", "missing evidence was not explicit")
    _expect(not unavailable.native.executed and not unavailable.native.blocked, "unavailable path auto-allowed")

    host_derived_rejected = False
    try:
        CapabilitySpec(
            capability_id="invalid-host-capability",
            required_event_fields=("outcome_status",),
            actions=("ask",),
            evidence_requirements=("fixture_hash",),
            source_host="claude/hooks",
        )
    except ValueError:
        host_derived_rejected = True
    _expect(host_derived_rejected, "host-derived policy authority was accepted")

    return {
        "capability_id": CAPABILITY_ID,
        "clients": client_reports,
        "pending_request_ids": sorted(pending_ids),
        "negative_controls": {
            "unsupported_resume": "advisory-and-retained",
            "missing_identity": "rejected",
            "missing_evidence": "unavailable-and-not-allowed",
            "host_derived_authority": "rejected",
            "version_mismatch": "advisory-and-not-allowed",
        },
    }
