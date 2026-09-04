#!/usr/bin/env python3
"""Fail-closed normalization and paired measurement for Pi and Oh My Pi."""
# file-complexity-waiver: protocol parser and comparison receipt form one audit boundary

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass

from model_call_receipts import (
    ModelCallReceipt,
    RoleReceipt,
    call_from_assistant_message,
)
from verifier_protocol import digest_bytes, digest_json
from verified_outcome_loop import FrozenSpec


_KNOWN_NON_TOOL_EVENTS = frozenset(
    {
        "agent_start",
        "turn_start",
        "message_start",
        "message_update",
        "message_end",
        "turn_end",
        "agent_end",
    }
)


def contract_bundle_digest(
    frozen: FrozenSpec,
    *,
    task: str,
    provider: str,
    model: str,
    max_attempts: int,
    generator_system_prompt: str | None = None,
    assessor_system_prompt: str | None = None,
    generator_prompt_template: str | None = None,
    assessor_prompt_template: str | None = None,
    cwd_policy: str | None = None,
    thinking: str | None = None,
    role_timeout_seconds: float | None = None,
    max_input_bytes: int | None = None,
    runtime_versions: tuple[tuple[str, str], ...] | None = None,
    package_versions: tuple[tuple[str, str], ...] | None = None,
) -> str:
    """Hash semantic contract bytes and execution policy, excluding paths/run IDs."""
    material = []
    for invariant in frozen.invariants:
        material.append(
            {
                "identifier": invariant.identifier,
                "statement": invariant.statement,
                "verifier_id": invariant.verifier.verifier_id,
                "verifier_artifacts": [
                    artifact_digest
                    for _, artifact_digest in invariant.verifier.artifact_digests
                ],
                "positive": digest_bytes(invariant.positive_control),
                "negatives": [
                    digest_bytes(control) for control in invariant.negative_controls
                ],
            }
        )
    return digest_json(
        {
            "task": task,
            "provider": provider,
            "model": model,
            "max_attempts": max_attempts,
            "execution_policy": {
                "generator_system_prompt": generator_system_prompt,
                "assessor_system_prompt": assessor_system_prompt,
                "generator_prompt_template": generator_prompt_template,
                "assessor_prompt_template": assessor_prompt_template,
                "cwd_policy": cwd_policy,
                "thinking": thinking,
                "role_timeout_seconds": role_timeout_seconds,
                "max_input_bytes": max_input_bytes,
                "runtime_versions": runtime_versions,
                "package_versions": package_versions,
            },
            "invariants": material,
        }
    )


def _unresolved(
    role: str,
    generation: int | None,
    reason: str,
    *,
    stdout: str = "",
    stderr: str = "",
) -> RoleReceipt:
    raw_bytes = stdout.encode("utf-8", errors="surrogateescape")
    return RoleReceipt(
        role=role,
        status="UNRESOLVED",
        candidate_generation=generation,
        reason=reason,
        stdout_bytes=len(raw_bytes),
        stderr_bytes=len(stderr.encode("utf-8", errors="surrogateescape")),
        raw_events_digest=hashlib.sha256(raw_bytes).hexdigest(),
        raw_events=stdout,
    )


def _elapsed(record: object) -> float | None:
    if not isinstance(record, dict):
        return None
    value = record.get("elapsed_ms")
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    ):
        return float(value)
    return None


def _assistant_text(message: object) -> str | None:
    if not isinstance(message, dict) or message.get("role") != "assistant":
        return None
    content = message.get("content")
    if not isinstance(content, list):
        return None
    pieces: list[str] = []
    for part in content:
        if not isinstance(part, dict) or part.get("type") != "text":
            return None
        text = part.get("text")
        if not isinstance(text, str):
            return None
        pieces.append(text)
    return "".join(pieces)


def parse_omp_adapter_output(
    *,
    role: str,
    generation: int | None,
    requested_provider: str | None,
    requested_model: str | None,
    stdout: str,
    stderr: str,
    returncode: int,
    process_duration_ms: float | None = None,
) -> RoleReceipt:
    """Parse one OMP SDK process while retaining every finalized provider call."""
    raw_bytes = stdout.encode("utf-8", errors="surrogateescape")
    records: list[object] = []
    malformed = False
    for line in stdout.splitlines():
        if not line:
            malformed = True
            break
        try:
            records.append(json.loads(line))
        except (TypeError, ValueError):
            malformed = True
            break

    runtime_version = ""
    events: list[dict[str, object]] = []
    terminal_seen = False
    protocol_invalid = malformed or not records
    if records:
        header = records[0]
        if (
            not isinstance(header, dict)
            or set(header) != {"record_type", "protocol_version", "runtime_version"}
            or header.get("record_type") != "header"
            or header.get("protocol_version") != 2
            or not isinstance(header.get("runtime_version"), str)
            or not header.get("runtime_version")
        ):
            protocol_invalid = True
        else:
            runtime_version = header["runtime_version"]
            expected_sequence = 0
            for index, record in enumerate(records[1:], 1):
                if not isinstance(record, dict):
                    protocol_invalid = True
                    break
                record_type = record.get("record_type")
                if record_type == "event":
                    if (
                        terminal_seen
                        or set(record)
                        != {"record_type", "sequence", "elapsed_ms", "event"}
                        or record.get("sequence") != expected_sequence
                        or _elapsed(record) is None
                        or not isinstance(record.get("event"), dict)
                    ):
                        protocol_invalid = True
                        break
                    events.append(record)
                    expected_sequence += 1
                elif record_type == "terminal":
                    wall_time = record.get("wall_time_ms")
                    if (
                        set(record) != {"record_type", "sequence", "wall_time_ms"}
                        or record.get("sequence") != expected_sequence
                        or not isinstance(wall_time, (int, float))
                        or isinstance(wall_time, bool)
                        or not math.isfinite(wall_time)
                        or wall_time < 0
                        or index != len(records) - 1
                    ):
                        protocol_invalid = True
                        break
                    terminal_seen = True
                else:
                    protocol_invalid = True
                    break

    start_times: list[float] = []
    messages: list[dict[str, object]] = []
    calls: list[ModelCallReceipt] = []
    event_types: list[str] = []
    terminal_ends = 0
    nonterminal_ends = 0
    unknown_event = False
    tool_activity = False
    invalid_timing = False
    assistant_final_count = sum(
        1
        for record in events
        if isinstance(record, dict)
        and isinstance(record.get("event"), dict)
        and record["event"].get("type") == "message_end"
        and isinstance(record["event"].get("message"), dict)
        and record["event"]["message"].get("role") == "assistant"
    )

    for record in events:
        elapsed = _elapsed(record)
        event = record.get("event") if isinstance(record, dict) else None
        if elapsed is None or not isinstance(event, dict):
            unknown_event = True
            continue
        event_type = event.get("type")
        if not isinstance(event_type, str):
            unknown_event = True
            continue
        event_types.append(event_type)
        normalized_type = event_type.lower().replace("_", "")
        if normalized_type.startswith("tool"):
            tool_activity = True
        elif event_type not in _KNOWN_NON_TOOL_EVENTS:
            unknown_event = True
        if event_type == "message_start":
            message = event.get("message")
            if isinstance(message, dict) and message.get("role") == "assistant":
                start_times.append(elapsed)
        elif event_type == "message_end":
            message = event.get("message")
            if isinstance(message, dict) and message.get("role") == "assistant":
                messages.append(message)
                start = (
                    start_times[len(messages) - 1]
                    if len(start_times) >= len(messages)
                    else None
                )
                duration = (
                    process_duration_ms
                    if assistant_final_count == 1 and process_duration_ms is not None
                    else elapsed - start
                    if start is not None and elapsed >= start
                    else None
                )
                if duration is None:
                    invalid_timing = True
                calls.append(
                    call_from_assistant_message(
                        message,
                        runtime="omp",
                        role=role,
                        generation=generation,
                        requested_provider=requested_provider,
                        requested_model=requested_model,
                        duration_ms=duration,
                    )
                )
        elif event_type == "agent_end":
            if event.get("isTerminal") is False:
                nonterminal_ends += 1
            else:
                terminal_ends += 1

    reason = ""
    topology_eligible = True
    if returncode != 0:
        reason, topology_eligible = f"omp_exit_{returncode}", False
    elif protocol_invalid:
        reason, topology_eligible = "omp_protocol_invalid", False
    elif not terminal_seen:
        reason, topology_eligible = "omp_not_terminal", False
    elif tool_activity:
        reason, topology_eligible = "omp_tool_activity_forbidden", False
    elif unknown_event:
        reason, topology_eligible = "omp_unknown_event", False
    elif nonterminal_ends:
        reason, topology_eligible = "omp_nonterminal_continuation", False
    elif terminal_ends != 1 or not event_types or event_types[-1] != "agent_end":
        reason, topology_eligible = "omp_not_terminal", False
    elif len(messages) != 1:
        reason, topology_eligible = "omp_multiple_model_calls", False
    elif invalid_timing:
        reason, topology_eligible = "omp_call_timing_missing", False
    elif calls[0].stop_detail == "pause_turn":
        reason, topology_eligible = "omp_paused_turn", False

    output = _assistant_text(messages[0]) if len(messages) == 1 else None
    if not reason and calls[0].stop_reason != "stop":
        reason = "omp_model_not_stopped"
    elif not reason and output is None:
        reason = "omp_result_malformed"
    elif not reason and not output.strip():
        reason = "omp_result_empty"

    settled = not reason and topology_eligible
    return RoleReceipt(
        role=role,
        status="SETTLED" if settled else "UNRESOLVED",
        output=output or "",
        candidate_generation=generation,
        reason=reason,
        stdout_bytes=len(raw_bytes),
        stderr_bytes=len(stderr.encode("utf-8", errors="surrogateescape")),
        model_calls=tuple(calls),
        topology_status="ELIGIBLE" if topology_eligible else "INELIGIBLE",
        runtime_version=runtime_version,
        raw_events_digest=hashlib.sha256(raw_bytes).hexdigest(),
        raw_events=stdout,
    )


@dataclass(frozen=True)
class ArmMeasurement:
    runtime: str
    contract_digest: str
    outcome_status: str
    receipts: tuple[RoleReceipt, ...]
    model_call_count: int
    measurement_status: str
    topology_status: str
    identity_status: str
    total_input_tokens: int | None
    total_output_tokens: int | None
    total_cache_read_tokens: int | None
    total_cache_write_tokens: int | None
    total_tokens: int | None
    total_cost_usd: float | None
    total_duration_ms: float | None
    evidence_digest: str

    @classmethod
    def from_receipts(
        cls,
        *,
        runtime: str,
        contract_digest: str,
        outcome_status: str,
        receipts: tuple[RoleReceipt, ...],
    ) -> ArmMeasurement:
        calls = tuple(call for receipt in receipts for call in receipt.model_calls)
        complete = bool(calls) and all(
            call.measurement_status == "COMPLETE" for call in calls
        )
        missing = bool(calls) and all(
            call.measurement_status == "MISSING" for call in calls
        )
        measurement_status = (
            "COMPLETE" if complete else "MISSING" if missing else "PARTIAL"
        )
        topology = (
            "ELIGIBLE"
            if receipts
            and all(receipt.topology_status == "ELIGIBLE" for receipt in receipts)
            else "INELIGIBLE"
        )
        identity = (
            "EXACT"
            if calls and all(call.requested_identity_observed for call in calls)
            else "DEVIATED"
        )

        def total(attribute: str) -> int | float | None:
            if not complete:
                return None
            return sum(getattr(call, attribute) for call in calls)

        return cls(
            runtime=runtime,
            contract_digest=contract_digest,
            outcome_status=outcome_status,
            receipts=receipts,
            model_call_count=len(calls),
            measurement_status=measurement_status,
            topology_status=topology,
            identity_status=identity,
            total_input_tokens=total("input_tokens"),  # type: ignore[arg-type]
            total_output_tokens=total("output_tokens"),  # type: ignore[arg-type]
            total_cache_read_tokens=total("cache_read_tokens"),  # type: ignore[arg-type]
            total_cache_write_tokens=total("cache_write_tokens"),  # type: ignore[arg-type]
            total_tokens=total("total_tokens"),  # type: ignore[arg-type]
            total_cost_usd=total("cost_usd"),  # type: ignore[arg-type]
            total_duration_ms=total("duration_ms"),  # type: ignore[arg-type]
            evidence_digest=digest_json(
                {
                    "runtime": runtime,
                    "contract_digest": contract_digest,
                    "outcome_status": outcome_status,
                    "receipts": [
                        {
                            "role": receipt.role,
                            "generation": receipt.candidate_generation,
                            "runtime_version": receipt.runtime_version,
                            "raw_events_digest": receipt.raw_events_digest,
                            "response_ids": [
                                call.response_id for call in receipt.model_calls
                            ],
                        }
                        for receipt in receipts
                    ],
                }
            ),
        )


@dataclass(frozen=True)
class ComparisonResult:
    status: str
    reason: str
    token_delta: int | None = None
    cost_delta_usd: float | None = None
    duration_delta_ms: float | None = None


def compare_arms(first: ArmMeasurement, second: ArmMeasurement) -> ComparisonResult:
    """Fail closed until provider-boundary request equality is observable."""
    reasons = []
    if first.contract_digest != second.contract_digest:
        reasons.append("contract_mismatch")
    if first.outcome_status != "COMPLETE" or second.outcome_status != "COMPLETE":
        reasons.append("outcome_incomplete")
    if (
        first.measurement_status != "COMPLETE"
        or second.measurement_status != "COMPLETE"
    ):
        reasons.append("measurement_incomplete")
    if first.topology_status != "ELIGIBLE" or second.topology_status != "ELIGIBLE":
        reasons.append("topology_ineligible")
    if first.identity_status != "EXACT" or second.identity_status != "EXACT":
        reasons.append("model_identity_deviation")
    reasons.append("effective_input_equality_unobservable")
    return ComparisonResult("INCONCLUSIVE", ",".join(reasons))
