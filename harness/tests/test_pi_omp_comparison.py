"""Behavioral oracle for measured installed-Pi versus OMP comparisons."""

from __future__ import annotations

import json
import hashlib
import math
import stat
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
BIN = REPO / "harness" / "bin"
sys.path.insert(0, str(BIN))

from pi_omp_comparison import (  # noqa: E402
    ArmMeasurement,
    compare_arms,
    contract_bundle_digest,
    parse_omp_adapter_output,
)
from verified_outcome_loop import FrozenSpec, Invariant, VerifierBinding  # noqa: E402


def _write_executable(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _frozen(
    tmp_path: Path,
    *,
    verifier_name: str = "verifier-a",
    verifier_bytes: bytes = b"#!/bin/sh\nexit 0\n",
    task_statement: str = "candidate returns the expected value",
) -> FrozenSpec:
    tmp_path.mkdir(parents=True, exist_ok=True)
    executable = tmp_path / verifier_name
    executable.write_bytes(verifier_bytes)
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    binding = VerifierBinding.freeze(
        verifier_id="frozen-outcome-v1",
        executable=executable.resolve(),
    )
    return FrozenSpec.freeze(
        [
            Invariant.freeze(
                identifier="expected-value",
                statement=task_statement,
                verifier=binding,
                positive_control=b"correct",
                negative_controls=(b"wrong", b""),
            )
        ]
    )


def _usage(
    *,
    input_tokens: int = 11,
    output_tokens: int = 7,
    cache_read: int = 3,
    cache_write: int = 2,
    total_tokens: int = 23,
    cost: float = 0.0042,
) -> dict[str, object]:
    return {
        "input": input_tokens,
        "output": output_tokens,
        "cacheRead": cache_read,
        "cacheWrite": cache_write,
        "totalTokens": total_tokens,
        "cost": {
            "input": 0.001,
            "output": 0.003,
            "cacheRead": 0.0001,
            "cacheWrite": 0.0001,
            "total": cost,
        },
    }


_DEFAULT_USAGE = object()


def _assistant(
    text: str,
    *,
    response_id: str,
    elapsed_ms: float,
    usage: object = _DEFAULT_USAGE,
    model: str = "claude-haiku-4-5",
    stop_details: object | None = None,
) -> dict[str, object]:
    message: dict[str, object] = {
        "role": "assistant",
        "content": [{"type": "text", "text": text}],
        "provider": "anthropic",
        "model": model,
        "responseId": response_id,
        "usage": _usage() if usage is _DEFAULT_USAGE else usage,
        "stopReason": "stop",
    }
    if stop_details is not None:
        message["stopDetails"] = stop_details
    return {
        "elapsed_ms": elapsed_ms,
        "event": {"type": "message_end", "message": message},
    }


def _adapter_payload(*events: object, wall_time_ms: float = 30.0) -> str:
    records = [
        {
            "record_type": "header",
            "protocol_version": 2,
            "runtime_version": "18.1.4",
        }
    ]
    for sequence, event in enumerate(events):
        records.append(
            {
                "record_type": "event",
                "sequence": sequence,
                **event,
            }
        )
    records.append(
        {
            "record_type": "terminal",
            "sequence": len(events),
            "wall_time_ms": wall_time_ms,
        }
    )
    return "\n".join(
        json.dumps(record, separators=(",", ":")) for record in records
    )


def _start(elapsed_ms: float) -> dict[str, object]:
    return {
        "elapsed_ms": elapsed_ms,
        "event": {"type": "message_start", "message": {"role": "assistant"}},
    }


def _terminal(elapsed_ms: float, *, is_terminal: bool = True) -> dict[str, object]:
    return {
        "elapsed_ms": elapsed_ms,
        "event": {"type": "agent_end", "isTerminal": is_terminal},
    }


def test_run_independent_contract_digest_uses_content_not_paths(tmp_path: Path) -> None:
    first = _frozen(tmp_path / "first", verifier_name="alpha")
    second = _frozen(tmp_path / "second", verifier_name="renamed")

    first_digest = contract_bundle_digest(
        first,
        task="solve the contract",
        provider="anthropic",
        model="claude-haiku-4-5",
        max_attempts=3,
    )
    second_digest = contract_bundle_digest(
        second,
        task="solve the contract",
        provider="anthropic",
        model="claude-haiku-4-5",
        max_attempts=3,
    )

    assert first.run_id != second.run_id
    assert first.digest != second.digest
    assert first_digest == second_digest


def test_contract_digest_changes_for_semantic_or_execution_policy_changes(
    tmp_path: Path,
) -> None:
    baseline = _frozen(tmp_path / "base")
    changed_bytes = _frozen(tmp_path / "bytes", verifier_bytes=b"#!/bin/sh\nexit 1\n")
    changed_statement = _frozen(
        tmp_path / "statement", task_statement="candidate returns another value"
    )

    def digest(spec: FrozenSpec, **changes: object) -> str:
        arguments: dict[str, object] = {
            "task": "solve the contract",
            "provider": "anthropic",
            "model": "claude-haiku-4-5",
            "max_attempts": 3,
            "generator_system_prompt": "generator-system-v1",
            "assessor_system_prompt": "assessor-system-v1",
            "generator_prompt_template": "generator-template-v1:{task}:{feedback}",
            "assessor_prompt_template": "assessor-template-v1:{candidate}",
            "cwd_policy": "fresh-empty-role-directory",
            "thinking": "off",
            "role_timeout_seconds": 120.0,
            "max_input_bytes": 1_048_576,
            "runtime_versions": (("pi", "0.52.1"), ("omp", "18.1.4")),
            "package_versions": (("bun", "1.4.0"),),
        }
        arguments.update(changes)
        return contract_bundle_digest(spec, **arguments)  # type: ignore[arg-type]

    expected = digest(baseline)
    assert digest(changed_bytes) != expected
    assert digest(changed_statement) != expected
    assert digest(baseline, task="different task") != expected
    assert digest(baseline, provider="openai") != expected
    assert digest(baseline, model="other-model") != expected
    assert digest(baseline, max_attempts=4) != expected
    for field, changed in (
        ("generator_system_prompt", "changed-generator-system"),
        ("assessor_system_prompt", "changed-assessor-system"),
        ("generator_prompt_template", "changed-generator-template"),
        ("assessor_prompt_template", "changed-assessor-template"),
        ("cwd_policy", "repository-cwd"),
        ("thinking", "low"),
        ("role_timeout_seconds", 121.0),
        ("max_input_bytes", 2048),
        ("runtime_versions", (("pi", "mutant"), ("omp", "18.1.4"))),
        ("package_versions", (("bun", "mutant"),)),
    ):
        assert digest(baseline, **{field: changed}) != expected


def test_contract_digest_marks_omitted_execution_policy_as_unobserved(
    tmp_path: Path,
) -> None:
    frozen = _frozen(tmp_path / "unobserved")

    digest = contract_bundle_digest(
        frozen,
        task="solve the contract",
        provider="anthropic",
        model="claude-haiku-4-5",
        max_attempts=3,
    )

    assert digest != contract_bundle_digest(
        frozen,
        task="solve the contract",
        provider="anthropic",
        model="claude-haiku-4-5",
        max_attempts=3,
        generator_system_prompt="generator-system-v1",
        assessor_system_prompt="assessor-system-v1",
        generator_prompt_template="generator-template-v1:{task}:{feedback}",
        assessor_prompt_template="assessor-template-v1:{candidate}",
        cwd_policy="fresh-empty-role-directory",
        thinking="off",
        role_timeout_seconds=120.0,
        max_input_bytes=1_048_576,
        runtime_versions=(("pi", "0.52.1"), ("omp", "18.1.4")),
        package_versions=(("bun", "1.4.0"),),
    )


def test_v2_partial_nonzero_stream_retains_finalized_calls_and_fails_closed() -> None:
    complete = _adapter_payload(
        _start(1.0),
        _assistant("captured", response_id="msg-before-timeout", elapsed_ms=5.0),
        _terminal(6.0),
    )
    partial = "\n".join(complete.splitlines()[:-2])

    receipt = parse_omp_adapter_output(
        role="generator",
        generation=1,
        requested_provider="anthropic",
        requested_model="claude-haiku-4-5",
        stdout=partial,
        stderr="timed out",
        returncode=124,
    )

    assert [call.response_id for call in receipt.model_calls] == [
        "msg-before-timeout"
    ]
    assert receipt.output == "captured"
    assert receipt.status == "UNRESOLVED"
    assert receipt.topology_status == "INELIGIBLE"
    assert receipt.reason == "omp_exit_124"
    assert receipt.raw_events == partial


def test_v2_sequence_gap_is_protocol_invalid_but_keeps_complete_prefix_call() -> None:
    records = _adapter_payload(
        _start(1.0),
        _assistant("captured", response_id="msg-prefix", elapsed_ms=5.0),
        _terminal(6.0),
    ).splitlines()
    bad = json.loads(records[3])
    bad["sequence"] = 99
    stream = "\n".join((*records[:3], json.dumps(bad, separators=(",", ":"))))

    receipt = parse_omp_adapter_output(
        role="generator",
        generation=1,
        requested_provider="anthropic",
        requested_model="claude-haiku-4-5",
        stdout=stream,
        stderr="",
        returncode=0,
    )

    assert [call.response_id for call in receipt.model_calls] == ["msg-prefix"]
    assert receipt.status == "UNRESOLVED"
    assert receipt.reason == "omp_protocol_invalid"


def test_pause_turn_continuations_are_counted_but_make_topology_ineligible() -> None:
    payload = _adapter_payload(
        _start(1.0),
        _assistant(
            "progress",
            response_id="msg-pause",
            elapsed_ms=9.0,
            stop_details={"type": "pause_turn"},
        ),
        _start(10.0),
        _assistant("final", response_id="msg-final", elapsed_ms=19.0),
        _terminal(20.0),
    )

    receipt = parse_omp_adapter_output(
        role="generator",
        generation=1,
        requested_provider="anthropic",
        requested_model="claude-haiku-4-5",
        stdout=payload,
        stderr="",
        returncode=0,
    )

    assert [call.response_id for call in receipt.model_calls] == [
        "msg-pause",
        "msg-final",
    ]
    assert [call.duration_ms for call in receipt.model_calls] == [8.0, 9.0]
    assert receipt.topology_status == "INELIGIBLE"
    assert receipt.status == "UNRESOLVED"
    assert receipt.reason == "omp_multiple_model_calls"
    assert receipt.raw_events == payload
    assert receipt.raw_events_digest == hashlib.sha256(payload.encode()).hexdigest()

    arm = ArmMeasurement.from_receipts(
        runtime="omp",
        contract_digest="same-contract",
        outcome_status="COMPLETE",
        receipts=(receipt,),
    )
    comparison = compare_arms(arm, arm)
    assert arm.model_call_count == 2
    assert comparison.status == "INCONCLUSIVE"
    assert comparison.token_delta is None
    assert comparison.cost_delta_usd is None


def test_updates_are_not_calls_and_final_literal_usage_is_not_recomputed() -> None:
    update = {
        "elapsed_ms": 4.0,
        "event": {
            "type": "message_update",
            "usage": _usage(input_tokens=999, total_tokens=999),
        },
    }
    final_usage = _usage(
        input_tokens=13,
        output_tokens=5,
        cache_read=2,
        cache_write=1,
        total_tokens=29,
        cost=0.007,
    )
    receipt = parse_omp_adapter_output(
        role="assessor",
        generation=2,
        requested_provider="anthropic",
        requested_model="claude-haiku-4-5",
        stdout=_adapter_payload(
            _start(2.0),
            update,
            update,
            _assistant(
                "final",
                response_id="msg-one",
                elapsed_ms=12.0,
                usage=final_usage,
            ),
            _terminal(13.0),
        ),
        stderr="",
        returncode=0,
    )

    assert len(receipt.model_calls) == 1
    call = receipt.model_calls[0]
    assert (
        call.input_tokens,
        call.output_tokens,
        call.cache_read_tokens,
        call.cache_write_tokens,
        call.total_tokens,
        call.cost_usd,
    ) == (13, 5, 2, 1, 29, 0.007)


def test_missing_or_invalid_measurement_never_becomes_zero() -> None:
    invalid_measurements = [
        None,
        {},
        _usage(input_tokens=-1),
        _usage(input_tokens=True),
        _usage(cost=-0.1),
        _usage(cost=math.inf),
        {**_usage(), "totalTokens": "23"},
    ]

    for index, usage in enumerate(invalid_measurements):
        receipt = parse_omp_adapter_output(
            role="generator",
            generation=index + 1,
            requested_provider="anthropic",
            requested_model="claude-haiku-4-5",
            stdout=_adapter_payload(
                _start(1.0),
                _assistant(
                    "final",
                    response_id=f"msg-{index}",
                    elapsed_ms=2.0,
                    usage=usage,
                ),
                _terminal(3.0),
            ),
            stderr="",
            returncode=0,
        )
        call = receipt.model_calls[0]
        assert call.measurement_status != "COMPLETE"
        assert call.total_tokens is None
        assert call.cost_usd is None


def test_rejected_shape_still_preserves_the_measured_model_call() -> None:
    receipt = parse_omp_adapter_output(
        role="generator",
        generation=4,
        requested_provider="anthropic",
        requested_model="claude-haiku-4-5",
        stdout=_adapter_payload(
            _start(1.0),
            _assistant(
                "not valid generator JSON",
                response_id="msg-malformed-output",
                elapsed_ms=5.0,
            ),
            _terminal(6.0),
        ),
        stderr="",
        returncode=0,
    )

    assert receipt.status == "SETTLED"
    assert receipt.output == "not valid generator JSON"
    assert len(receipt.model_calls) == 1
    assert receipt.model_calls[0].total_tokens == 23


def test_nonterminal_end_does_not_settle_and_late_work_is_retained() -> None:
    receipt = parse_omp_adapter_output(
        role="assessor",
        generation=5,
        requested_provider="anthropic",
        requested_model="claude-haiku-4-5",
        stdout=_adapter_payload(
            _start(1.0),
            _assistant("first", response_id="msg-first", elapsed_ms=4.0),
            _terminal(5.0, is_terminal=False),
            _start(6.0),
            _assistant("late", response_id="msg-late", elapsed_ms=8.0),
            _terminal(9.0),
        ),
        stderr="",
        returncode=0,
    )

    assert [item.response_id for item in receipt.model_calls] == [
        "msg-first",
        "msg-late",
    ]
    assert receipt.status == "UNRESOLVED"
    assert receipt.topology_status == "INELIGIBLE"


def test_tool_activity_and_unknown_events_fail_comparison_closed() -> None:
    for event in [
        {"elapsed_ms": 1.5, "event": {"type": "tool_execution_start"}},
        {"elapsed_ms": 1.5, "event": {"type": "future_provider_side_call"}},
    ]:
        receipt = parse_omp_adapter_output(
            role="generator",
            generation=1,
            requested_provider="anthropic",
            requested_model="claude-haiku-4-5",
            stdout=_adapter_payload(
                _start(1.0),
                event,
                _assistant("final", response_id="msg-one", elapsed_ms=2.0),
                _terminal(3.0),
            ),
            stderr="",
            returncode=0,
        )
        assert receipt.status == "UNRESOLVED"
        assert receipt.topology_status == "INELIGIBLE"
