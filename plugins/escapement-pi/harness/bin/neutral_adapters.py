#!/usr/bin/env python3
"""Thin native adapters for Pi, Codex, and Claude."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

from neutral_contract import NeutralDecision, NeutralEvent, PendingAction, normalize_event
from neutral_registry import CAPABILITY_ID, CapabilityRegistry
from neutral_runtime import evaluate


@dataclass(frozen=True)
class NativeResult:
    client: str
    action: str
    enforcement: str
    state_transition: str
    correlation_id: str
    executed: bool
    blocked: bool
    advisory: str | None = None
    pending_request_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AdapterResult:
    event: NeutralEvent
    decision: NeutralDecision
    native: NativeResult


class NeutralAdapter:
    """Decode one client payload and realize a neutral decision."""

    client = ""
    resume_supported = True

    def __init__(
        self,
        *,
        client_version: str,
        registry: CapabilityRegistry,
        resume_supported: bool | None = None,
    ) -> None:
        self.client_version = client_version
        self.registry = registry
        if resume_supported is not None:
            self.resume_supported = resume_supported

    def _native_fields(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def normalize(self, raw: Mapping[str, Any]) -> NeutralEvent:
        event = normalize_event(self._native_fields(raw))
        if event.client != self.client:
            raise ValueError(f"adapter client mismatch: {event.client}")
        return event

    def dispatch(self, raw: Mapping[str, Any]) -> AdapterResult:
        event = self.normalize(raw)
        decision = evaluate(event, self.registry)
        return AdapterResult(event=event, decision=decision, native=self.apply(decision))

    def apply(self, decision: NeutralDecision) -> NativeResult:
        hard = decision.enforcement == "hard"
        if decision.action in {"deny", "ask"}:
            if hard:
                return NativeResult(
                    client=self.client,
                    action=decision.action,
                    enforcement=decision.enforcement,
                    state_transition=decision.state_transition,
                    correlation_id=decision.correlation_id,
                    executed=False,
                    blocked=True,
                    pending_request_id=(
                        decision.pending_action.request_id if decision.pending_action else None
                    ),
                )
            return NativeResult(
                client=self.client,
                action=decision.action,
                enforcement=decision.enforcement,
                state_transition=decision.state_transition,
                correlation_id=decision.correlation_id,
                executed=False,
                blocked=False,
                advisory=decision.explanation,
                pending_request_id=(
                    decision.pending_action.request_id if decision.pending_action else None
                ),
            )
        return NativeResult(
            client=self.client,
            action=decision.action,
            enforcement=decision.enforcement,
            state_transition=decision.state_transition,
            correlation_id=decision.correlation_id,
            executed=hard or decision.enforcement == "advisory",
            blocked=False,
            advisory=(None if hard else decision.explanation),
        )

    def resume(self, pending: PendingAction) -> NativeResult:
        """Realize a persisted action; never re-evaluate its policy."""
        if pending.client != self.client:
            raise ValueError("pending action belongs to another client")
        realization = self.registry.realization(
            pending.capability_id,
            self.client,
            pending.client_version,
        )
        if not self.resume_supported:
            return NativeResult(
                client=self.client,
                action="continue",
                enforcement=realization if realization != "hard" else "advisory",
                state_transition="outcome-advisory",
                correlation_id=pending.correlation_id,
                executed=False,
                blocked=False,
                advisory="client has no proven native resume mechanism",
                pending_request_id=pending.request_id,
            )
        return NativeResult(
            client=self.client,
            action="continue",
            enforcement=realization,
            state_transition="outcome-resumed",
            correlation_id=pending.correlation_id,
            executed=realization == "hard",
            blocked=False,
            advisory=(None if realization == "hard" else "resume realization is not hard"),
            pending_request_id=pending.request_id,
        )


class PiAdapter(NeutralAdapter):
    client = "pi"

    def _native_fields(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        payload = raw.get("input", raw.get("payload", {}))
        return {
            "capability_id": raw.get("capability_id"),
            "event_kind": raw.get("event_kind", raw.get("event")),
            "session_id": raw.get("session_id"),
            "actor_id": raw.get("actor_id"),
            "client": self.client,
            "client_version": raw.get("client_version", raw.get("version", self.client_version)),
            "correlation_id": raw.get("correlation_id"),
            "repository": raw.get("repository"),
            "worktree": raw.get("cwd"),
            "payload": payload,
        }


class CodexAdapter(NeutralAdapter):
    client = "codex"

    def _native_fields(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "capability_id": raw.get("capability_id"),
            "event_kind": raw.get("hook_event_name", raw.get("event_kind")),
            "session_id": raw.get("session_id", raw.get("sessionId")),
            "actor_id": raw.get("actor_id", raw.get("agentId")),
            "client": self.client,
            "client_version": raw.get("client_version", raw.get("version", self.client_version)),
            "correlation_id": raw.get("correlation_id", raw.get("correlationId")),
            "repository": raw.get("repository", raw.get("repo")),
            "worktree": raw.get("cwd"),
            "payload": raw.get("payload", {}),
        }


class ClaudeAdapter(NeutralAdapter):
    client = "claude"

    def _native_fields(self, raw: Mapping[str, Any]) -> dict[str, Any]:
        outcome = raw.get("outcome", raw.get("payload", {}))
        return {
            "capability_id": raw.get("capability_id"),
            "event_kind": raw.get("hook_event_name", raw.get("event_kind")),
            "session_id": raw.get("session_id"),
            "actor_id": raw.get("actor_id"),
            "client": self.client,
            "client_version": raw.get("client_version", raw.get("version", self.client_version)),
            "correlation_id": raw.get("correlation_id"),
            "repository": raw.get("repository"),
            "worktree": raw.get("cwd"),
            "payload": outcome,
        }


def adapter_for(
    client: str,
    *,
    client_version: str,
    registry: CapabilityRegistry,
    resume_supported: bool | None = None,
) -> NeutralAdapter:
    adapters = {"pi": PiAdapter, "codex": CodexAdapter, "claude": ClaudeAdapter}
    try:
        adapter_type = adapters[client]
    except KeyError as error:
        raise ValueError(f"unknown client adapter: {client}") from error
    return adapter_type(
        client_version=client_version,
        registry=registry,
        resume_supported=resume_supported,
    )
