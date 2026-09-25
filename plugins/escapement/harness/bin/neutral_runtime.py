#!/usr/bin/env python3
"""Policy and state transitions for the first neutral capability slice."""

from __future__ import annotations

import hashlib
from typing import Any

from neutral_contract import NeutralDecision, NeutralEvent, PendingAction
from neutral_registry import CapabilityRegistry


_STATUS_TO_RESULT = {
    "verified": ("continue", "outcome-verified"),
    "failed": ("deny", "outcome-failed"),
}


def _request_id(event: NeutralEvent, operation: str) -> str:
    material = "\0".join(
        (event.capability_id, event.session_id, event.correlation_id, operation)
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def _incomplete(event: NeutralEvent, registry: CapabilityRegistry, reason: str) -> NeutralDecision:
    realization = registry.realization(
        event.capability_id,
        event.client,
        event.client_version,
    )
    return NeutralDecision(
        capability_id=event.capability_id,
        action="ask",
        enforcement=realization,
        state_transition="outcome-incomplete",
        explanation=reason,
        correlation_id=event.correlation_id,
    )


def evaluate(event: NeutralEvent, registry: CapabilityRegistry) -> NeutralDecision:
    """Evaluate one normalized event without consulting client-specific code."""
    capability = registry.require(event.capability_id)
    missing = [field for field in capability.required_event_fields if field not in event.payload]
    if missing:
        return _incomplete(event, registry, f"missing required outcome field(s): {', '.join(missing)}")

    status: Any = event.payload.get("outcome_status")
    realization = registry.realization(
        event.capability_id,
        event.client,
        event.client_version,
    )
    if not isinstance(status, str):
        return _incomplete(event, registry, "outcome_status must be a string")
    if status in _STATUS_TO_RESULT:
        action, transition = _STATUS_TO_RESULT[status]
        return NeutralDecision(
            capability_id=event.capability_id,
            action=action,
            enforcement=realization,
            state_transition=transition,
            explanation=f"outcome status is {status}",
            correlation_id=event.correlation_id,
        )
    if status != "pending":
        return _incomplete(event, registry, f"unknown outcome status: {status}")

    operation = "resume-after-outcome"
    pending = PendingAction(
        request_id=_request_id(event, operation),
        capability_id=event.capability_id,
        operation=operation,
        state_transition="outcome-awaiting",
        session_id=event.session_id,
        actor_id=event.actor_id,
        client=event.client,
        client_version=event.client_version,
        correlation_id=event.correlation_id,
    )
    return NeutralDecision(
        capability_id=event.capability_id,
        action="ask",
        enforcement=realization,
        state_transition="outcome-awaiting",
        explanation="outcome is unresolved; continuation remains pending",
        correlation_id=event.correlation_id,
        pending_action=pending,
    )
