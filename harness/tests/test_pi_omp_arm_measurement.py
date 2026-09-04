"""Aggregate and paired-result controls for Pi versus OMP measurements."""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
BIN = REPO / "harness" / "bin"
sys.path.insert(0, str(BIN))

from model_call_receipts import (  # noqa: E402
    ModelCallReceipt,
    RoleReceipt,
    measured_call,
)
from pi_omp_comparison import (  # noqa: E402
    ArmMeasurement,
    compare_arms,
)


def _receipt(*calls: ModelCallReceipt) -> RoleReceipt:
    return RoleReceipt(
        role="generator",
        status="SETTLED",
        output="answer",
        candidate_generation=1,
        model_calls=tuple(calls),
        topology_status="ELIGIBLE" if len(calls) == 1 else "INELIGIBLE",
    )


def _call(runtime: str = "pi", **changes: object) -> ModelCallReceipt:
    values: dict = {
        "runtime": runtime,
        "role": "generator",
        "generation": 1,
        "requested_provider": "anthropic",
        "requested_model": "claude-haiku-4-5",
        "observed_provider": "anthropic",
        "observed_model": "claude-haiku-4-5",
        "response_id": f"{runtime}-response",
        "input_tokens": 17,
        "output_tokens": 3,
        "cache_read_tokens": 4,
        "cache_write_tokens": 1,
        "total_tokens": 25,
        "cost_usd": 0.002,
        "duration_ms": 9.0,
        "stop_reason": "stop",
        "stop_detail": None,
    }
    values.update(changes)
    return measured_call(**values)


def _arm(runtime: str, call: ModelCallReceipt, *, contract: str = "same"):
    return ArmMeasurement.from_receipts(
        runtime=runtime,
        contract_digest=contract,
        outcome_status="COMPLETE",
        receipts=(_receipt(call),),
    )


def test_identical_calls_preserve_cardinality_and_literal_aggregates() -> None:
    call = _call("omp", response_id="same")
    arm = ArmMeasurement.from_receipts(
        runtime="omp",
        contract_digest="digest",
        outcome_status="COMPLETE",
        receipts=(_receipt(call), _receipt(call)),
    )

    assert arm.model_call_count == 2
    assert arm.total_tokens == 50
    assert arm.total_input_tokens == 34
    assert arm.total_output_tokens == 6
    assert arm.total_cache_read_tokens == 8
    assert arm.total_cache_write_tokens == 2
    assert arm.total_cost_usd == 0.004
    assert arm.total_duration_ms == 18.0


def test_fallback_or_missing_data_makes_pair_inconclusive() -> None:
    exact = _call("pi")
    fallback = replace(
        exact,
        runtime="omp",
        observed_model="different-model",
        response_id="omp-fallback",
    )
    missing = _call("omp", cost_usd=None)

    for call in (fallback, missing):
        result = compare_arms(_arm("pi", exact), _arm("omp", call))
        assert result.status == "INCONCLUSIVE"
        assert result.token_delta is None
        assert result.cost_delta_usd is None


def test_complete_equal_contract_without_external_input_observation_is_inconclusive() -> (
    None
):
    pi = _call("pi", input_tokens=20, total_tokens=25, cost_usd=0.005, duration_ms=10.0)
    omp = _call(
        "omp", input_tokens=15, total_tokens=20, cost_usd=0.003, duration_ms=8.0
    )

    result = compare_arms(_arm("pi", pi), _arm("omp", omp))

    assert result.status == "INCONCLUSIVE"
    assert result.reason == "effective_input_equality_unobservable"
    assert result.token_delta is None


def test_no_caller_supplied_receipt_can_manufacture_comparability() -> None:
    pi = _arm(
        "pi",
        _call("pi", input_tokens=20, total_tokens=25, cost_usd=0.005, duration_ms=10.0),
    )
    omp = _arm(
        "omp",
        _call("omp", input_tokens=15, total_tokens=20, cost_usd=0.003, duration_ms=8.0),
    )

    result = compare_arms(pi, omp)

    assert result.status == "INCONCLUSIVE"
    assert result.reason == "effective_input_equality_unobservable"
    assert result.token_delta is None
    assert result.cost_delta_usd is None
    assert result.duration_delta_ms is None
