#!/usr/bin/env python3
"""Neutral capability declarations and evidence-backed adapter coverage."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from neutral_contract import ACTIONS, CLIENTS, ENFORCEMENT_LEVELS, ContractError


CAPABILITY_ID = "outcome-oracle-continuation"


@dataclass(frozen=True)
class CapabilitySpec:
    capability_id: str
    required_event_fields: tuple[str, ...]
    actions: tuple[str, ...]
    evidence_requirements: tuple[str, ...]
    owner: str = "neutral-runtime"
    source_host: str | None = None

    def __post_init__(self) -> None:
        if not self.capability_id.strip():
            raise ContractError("capability_id is required")
        if self.owner != "neutral-runtime":
            raise ContractError("neutral capabilities must be owned by neutral-runtime")
        if self.source_host:
            raise ContractError("host-derived authority is not allowed")
        if not self.required_event_fields:
            raise ContractError("required event fields cannot be empty")
        if not self.actions or any(action not in ACTIONS for action in self.actions):
            raise ContractError("capability contains an unknown action")


@dataclass(frozen=True)
class AdapterEvidence:
    client: str
    client_version: str
    realization: str
    fixture_hash: str
    native_event_ref: str
    point_of_effect: str

    def __post_init__(self) -> None:
        if self.client not in CLIENTS:
            raise ContractError(f"unsupported selected client: {self.client}")
        if self.realization not in ENFORCEMENT_LEVELS:
            raise ContractError(f"unknown realization: {self.realization}")
        if not self.client_version.strip():
            raise ContractError("client_version is required")
        for field in ("fixture_hash", "native_event_ref", "point_of_effect"):
            if not isinstance(getattr(self, field), str) or not getattr(self, field).strip():
                raise ContractError(f"{field} is required for adapter evidence")

    @property
    def hard_proven(self) -> bool:
        return self.realization == "hard" and all(
            (self.fixture_hash, self.native_event_ref, self.point_of_effect)
        )


class CapabilityRegistry:
    """Canonical capability declarations plus per-client evidence."""

    def __init__(self, capabilities: Iterable[CapabilitySpec] = ()) -> None:
        self._capabilities: dict[str, CapabilitySpec] = {}
        self._evidence: dict[tuple[str, str], AdapterEvidence] = {}
        for capability in capabilities:
            self.register(capability)

    def register(self, capability: CapabilitySpec) -> None:
        if capability.capability_id in self._capabilities:
            raise ContractError(f"duplicate capability: {capability.capability_id}")
        self._capabilities[capability.capability_id] = capability

    def add_evidence(self, capability_id: str, evidence: AdapterEvidence) -> None:
        self.require(capability_id)
        key = (capability_id, evidence.client)
        if key in self._evidence:
            raise ContractError(f"duplicate adapter evidence: {capability_id}/{evidence.client}")
        self._evidence[key] = evidence

    def set_evidence(self, capability_id: str, evidence: AdapterEvidence) -> None:
        self.require(capability_id)
        self._evidence[(capability_id, evidence.client)] = evidence

    def require(self, capability_id: str) -> CapabilitySpec:
        try:
            return self._capabilities[capability_id]
        except KeyError as error:
            raise ContractError(f"unknown capability: {capability_id}") from error

    def evidence(self, capability_id: str, client: str) -> AdapterEvidence | None:
        self.require(capability_id)
        return self._evidence.get((capability_id, client))

    def realization(
        self,
        capability_id: str,
        client: str,
        client_version: str | None = None,
    ) -> str:
        evidence = self.evidence(capability_id, client)
        if evidence is None or evidence.realization == "unavailable":
            return "unavailable"
        if client_version is not None and evidence.client_version != client_version:
            return "advisory"
        return evidence.realization

    def assert_hard(
        self,
        capability_id: str,
        client: str,
        client_version: str | None = None,
    ) -> None:
        evidence = self.evidence(capability_id, client)
        if (
            evidence is None
            or not evidence.hard_proven
            or (client_version is not None and evidence.client_version != client_version)
        ):
            raise ContractError(f"hard realization is not proven: {capability_id}/{client}")

    def to_dict(self) -> dict[str, object]:
        return {
            "capabilities": [
                {
                    "capability_id": capability.capability_id,
                    "required_event_fields": list(capability.required_event_fields),
                    "actions": list(capability.actions),
                    "evidence_requirements": list(capability.evidence_requirements),
                    "owner": capability.owner,
                }
                for capability in self._capabilities.values()
            ],
            "adapters": [
                {
                    "capability_id": capability_id,
                    **{
                        "client": evidence.client,
                        "client_version": evidence.client_version,
                        "realization": evidence.realization,
                        "fixture_hash": evidence.fixture_hash,
                        "native_event_ref": evidence.native_event_ref,
                        "point_of_effect": evidence.point_of_effect,
                    },
                }
                for (capability_id, _), evidence in self._evidence.items()
            ],
        }


def registry_from_document(document: Mapping[str, Any]) -> CapabilityRegistry:
    if not isinstance(document, Mapping):
        raise ContractError("capability registry must be an object")
    try:
        capability_rows = document["capabilities"]
        adapter_rows = document["adapters"]
    except KeyError as error:
        raise ContractError(f"capability registry is missing {error.args[0]}") from error
    if not isinstance(capability_rows, list) or not isinstance(adapter_rows, list):
        raise ContractError("capability and adapter registry entries must be arrays")
    registry = CapabilityRegistry(
        [
            CapabilitySpec(
                capability_id=row["capability_id"],
                required_event_fields=tuple(row["required_event_fields"]),
                actions=tuple(row["actions"]),
                evidence_requirements=tuple(row["evidence_requirements"]),
                owner=row.get("owner", "neutral-runtime"),
            )
            for row in capability_rows
        ]
    )
    for row in adapter_rows:
        capability_id = row["capability_id"]
        registry.add_evidence(
            capability_id,
            AdapterEvidence(
                client=row["client"],
                client_version=row["client_version"],
                realization=row["realization"],
                fixture_hash=row["fixture_hash"],
                native_event_ref=row["native_event_ref"],
                point_of_effect=row["point_of_effect"],
            ),
        )
    return registry


def default_registry() -> CapabilityRegistry:
    path = Path(__file__).resolve().parents[1] / "schemas" / "neutral-capabilities.json"
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ContractError(f"cannot load neutral capability registry: {path}") from error
    return registry_from_document(document)
