#!/usr/bin/env python3
"""Runtime-neutral, literal model-call measurement receipts."""

from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelCallReceipt:
    runtime: str
    role: str
    generation: int | None
    requested_provider: str | None
    requested_model: str | None
    observed_provider: str | None
    observed_model: str | None
    response_id: str | None
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    cache_write_tokens: int | None
    total_tokens: int | None
    cost_usd: float | None
    duration_ms: float | None
    stop_reason: str | None
    stop_detail: str | None
    measurement_status: str
    measurement_reason: str = ""

    @property
    def requested_identity_observed(self) -> bool:
        return (
            self.requested_provider is not None
            and self.requested_model is not None
            and self.observed_provider == self.requested_provider
            and self.observed_model == self.requested_model
        )


@dataclass(frozen=True)
class RoleReceipt:
    role: str
    status: str
    output: str = ""
    candidate_generation: int | None = None
    reason: str = ""
    config_dir: str = ""
    command: tuple[str, ...] = ()
    stdout_bytes: int = 0
    stderr_bytes: int = 0
    model_calls: tuple[ModelCallReceipt, ...] = ()
    topology_status: str = "INELIGIBLE"
    runtime_version: str = ""
    raw_events_digest: str = ""
    raw_events: str = field(default="", repr=False)


def _valid_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _valid_amount(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def measured_call(
    *,
    runtime: str,
    role: str,
    generation: int | None,
    requested_provider: str | None,
    requested_model: str | None,
    observed_provider: str | None,
    observed_model: str | None,
    response_id: str | None,
    input_tokens: object,
    output_tokens: object,
    cache_read_tokens: object,
    cache_write_tokens: object,
    total_tokens: object,
    cost_usd: object,
    duration_ms: object,
    stop_reason: str | None,
    stop_detail: str | None,
) -> ModelCallReceipt:
    """Keep literal provider values; incomplete or malformed measurement is unknown."""
    counts = (
        input_tokens,
        output_tokens,
        cache_read_tokens,
        cache_write_tokens,
        total_tokens,
    )
    complete = all(_valid_count(value) for value in counts)
    complete = complete and _valid_amount(cost_usd) and _valid_amount(duration_ms)
    if not complete:
        return ModelCallReceipt(
            runtime=runtime,
            role=role,
            generation=generation,
            requested_provider=requested_provider,
            requested_model=requested_model,
            observed_provider=observed_provider,
            observed_model=observed_model,
            response_id=response_id,
            input_tokens=None,
            output_tokens=None,
            cache_read_tokens=None,
            cache_write_tokens=None,
            total_tokens=None,
            cost_usd=None,
            duration_ms=None,
            stop_reason=stop_reason,
            stop_detail=stop_detail,
            measurement_status="MISSING",
            measurement_reason="incomplete_or_invalid_call_measurement",
        )
    return ModelCallReceipt(
        runtime=runtime,
        role=role,
        generation=generation,
        requested_provider=requested_provider,
        requested_model=requested_model,
        observed_provider=observed_provider,
        observed_model=observed_model,
        response_id=response_id,
        input_tokens=int(input_tokens),
        output_tokens=int(output_tokens),
        cache_read_tokens=int(cache_read_tokens),
        cache_write_tokens=int(cache_write_tokens),
        total_tokens=int(total_tokens),
        cost_usd=float(cost_usd),
        duration_ms=float(duration_ms),
        stop_reason=stop_reason,
        stop_detail=stop_detail,
        measurement_status="COMPLETE",
    )


def call_from_assistant_message(
    message: object,
    *,
    runtime: str,
    role: str,
    generation: int | None,
    requested_provider: str | None,
    requested_model: str | None,
    duration_ms: object,
) -> ModelCallReceipt:
    """Normalize one finalized assistant message without inventing missing values."""
    if not isinstance(message, dict):
        message = {}
    usage = message.get("usage")
    if not isinstance(usage, dict):
        usage = {}
    cost = usage.get("cost")
    if not isinstance(cost, dict):
        cost = {}
    stop_details = message.get("stopDetails")
    stop_detail = (
        stop_details.get("type")
        if isinstance(stop_details, dict) and isinstance(stop_details.get("type"), str)
        else None
    )
    return measured_call(
        runtime=runtime,
        role=role,
        generation=generation,
        requested_provider=requested_provider,
        requested_model=requested_model,
        observed_provider=(
            message.get("provider")
            if isinstance(message.get("provider"), str)
            else None
        ),
        observed_model=(
            message.get("model") if isinstance(message.get("model"), str) else None
        ),
        response_id=(
            message.get("responseId")
            if isinstance(message.get("responseId"), str)
            else None
        ),
        input_tokens=usage.get("input"),
        output_tokens=usage.get("output"),
        cache_read_tokens=usage.get("cacheRead"),
        cache_write_tokens=usage.get("cacheWrite"),
        total_tokens=usage.get("totalTokens"),
        cost_usd=cost.get("total"),
        duration_ms=duration_ms,
        stop_reason=(
            message.get("stopReason")
            if isinstance(message.get("stopReason"), str)
            else None
        ),
        stop_detail=stop_detail,
    )
