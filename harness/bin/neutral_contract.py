#!/usr/bin/env python3
"""Client-neutral event, decision, and pending-action value objects.

Adapters are allowed to know native payload names.  The runtime and supervisor
consume only the types in this module.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping


CLIENTS = frozenset({"pi", "codex", "claude"})
ENFORCEMENT_LEVELS = frozenset({"hard", "advisory", "unavailable"})
ACTIONS = frozenset({"allow", "ask", "deny", "continue", "record"})


class ContractError(ValueError):
    """A native event or runtime decision violates the neutral contract."""


class IncompleteEvent(ContractError):
    """An event lacks identity or provenance required for a decision."""


class AmbiguousEvent(ContractError):
    """An event contains conflicting aliases or an ambiguous payload."""


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IncompleteEvent(f"{field} is required")
    return value.strip()


def _alias(raw: Mapping[str, Any], field: str, *aliases: str) -> Any:
    values = [raw[name] for name in (field, *aliases) if name in raw]
    if not values:
        return None
    if any(value != values[0] for value in values[1:]):
        raise AmbiguousEvent(f"conflicting values for {field}")
    return values[0]


@dataclass(frozen=True)
class NeutralEvent:
    """Normalized native input with enough provenance for an audit trail."""

    capability_id: str
    event_kind: str
    session_id: str
    actor_id: str
    client: str
    client_version: str
    correlation_id: str
    payload: dict[str, Any]
    repository: str | None = None
    worktree: str | None = None

    def __post_init__(self) -> None:
        for field in (
            "capability_id",
            "event_kind",
            "session_id",
            "actor_id",
            "client",
            "client_version",
            "correlation_id",
        ):
            _text(getattr(self, field), field)
        if self.client not in CLIENTS:
            raise ContractError(f"unsupported client: {self.client}")
        if not isinstance(self.payload, dict):
            raise AmbiguousEvent("payload must be an object")
        for field in ("repository", "worktree"):
            value = getattr(self, field)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise AmbiguousEvent(f"{field} must be a non-empty string when present")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_event(raw: Mapping[str, Any]) -> NeutralEvent:
    """Normalize one native adapter payload; never infer missing identity."""
    if not isinstance(raw, Mapping):
        raise IncompleteEvent("event must be an object")
    payload = raw.get("payload", {})
    if not isinstance(payload, Mapping):
        raise AmbiguousEvent("payload must be an object")
    return NeutralEvent(
        capability_id=_text(_alias(raw, "capability_id", "capability"), "capability_id"),
        event_kind=_text(_alias(raw, "event_kind", "event", "hook_event_name"), "event_kind"),
        session_id=_text(_alias(raw, "session_id", "sessionId"), "session_id"),
        actor_id=_text(_alias(raw, "actor_id", "agent_id", "agentId"), "actor_id"),
        client=_text(_alias(raw, "client", "host"), "client"),
        client_version=_text(_alias(raw, "client_version", "version"), "client_version"),
        correlation_id=_text(_alias(raw, "correlation_id", "correlationId"), "correlation_id"),
        payload=dict(payload),
        repository=_alias(raw, "repository", "repo"),
        worktree=_alias(raw, "worktree", "cwd"),
    )


@dataclass(frozen=True)
class PendingAction:
    """Durable lifecycle work emitted by the neutral runtime."""

    request_id: str
    capability_id: str
    operation: str
    state_transition: str
    session_id: str
    actor_id: str
    client: str
    client_version: str
    correlation_id: str
    status: str = "pending"

    def __post_init__(self) -> None:
        for field in (
            "request_id",
            "capability_id",
            "operation",
            "state_transition",
            "session_id",
            "actor_id",
            "client",
            "client_version",
            "correlation_id",
        ):
            _text(getattr(self, field), field)
        if self.client not in CLIENTS:
            raise ContractError(f"unsupported client: {self.client}")
        if self.status not in {"pending", "advisory"}:
            raise ContractError(f"unknown pending action status: {self.status}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class NeutralDecision:
    """Structured semantic result; adapters only realize this result."""

    capability_id: str
    action: str
    enforcement: str
    state_transition: str
    explanation: str
    correlation_id: str
    pending_action: PendingAction | None = None

    def __post_init__(self) -> None:
        if self.action not in ACTIONS:
            raise ContractError(f"unknown decision action: {self.action}")
        if self.enforcement not in ENFORCEMENT_LEVELS:
            raise ContractError(f"unknown enforcement level: {self.enforcement}")
        for field in (
            "capability_id",
            "state_transition",
            "explanation",
            "correlation_id",
        ):
            _text(getattr(self, field), field)
        if self.pending_action is not None:
            if self.pending_action.correlation_id != self.correlation_id:
                raise ContractError("pending action correlation does not match decision")
            if self.pending_action.capability_id != self.capability_id:
                raise ContractError("pending action capability does not match decision")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        return value
