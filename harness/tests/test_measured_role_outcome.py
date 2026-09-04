"""The receipt collector observes roles but cannot become completion authority."""

from __future__ import annotations

import json
import stat
import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
BIN = REPO / "harness" / "bin"
sys.path.insert(0, str(BIN))

from measured_role_outcome import run_measured_role_outcome  # noqa: E402
from model_call_receipts import RoleReceipt, measured_call  # noqa: E402
from verified_outcome_loop import FrozenSpec, Invariant, VerifierBinding  # noqa: E402


def _contract(tmp_path: Path) -> FrozenSpec:
    verifier = tmp_path / "verifier"
    verifier.write_text(
        """#!/usr/bin/env python3
import json, sys
r=json.load(sys.stdin)
ok=bytes.fromhex(r['candidate_hex']) == b'right'
json.dump({'request_id':r['request_id'],'request_digest':r['request_digest'],'verifier_digest':r['verifier']['digest'],'results':[{'invariant_id':i['id'],'verifier_id':r['verifier']['id'],'result':'PASS' if ok else 'FAIL','detail':'exact'} for i in r['invariants']]},sys.stdout)
""",
        encoding="utf-8",
    )
    verifier.chmod(verifier.stat().st_mode | stat.S_IXUSR)
    binding = VerifierBinding.freeze(verifier_id="exact", executable=verifier.resolve())
    invariant = Invariant.freeze(
        identifier="right",
        statement="candidate is exactly right",
        verifier=binding,
        positive_control=b"right",
        negative_controls=(b"wrong", b""),
    )
    return FrozenSpec.freeze([invariant])


def _invoker(*, complete_measurement: bool):
    def invoke(role: str, prompt: str, system_prompt: str, generation: int):
        del system_prompt
        if role == "generator":
            output = json.dumps({"candidate": "right"})
        else:
            invariant_id = json.loads(prompt)["frozen_spec"]["invariants"][0]["id"]
            output = json.dumps(
                {
                    "assessments": [
                        {
                            "invariant_id": invariant_id,
                            "result": "SATISFIED",
                            "detail": "model opinion only",
                        }
                    ]
                }
            )
        call = measured_call(
            runtime="fixture",
            role=role,
            generation=generation,
            requested_provider="anthropic",
            requested_model="claude-haiku-4-5",
            observed_provider="anthropic",
            observed_model="claude-haiku-4-5",
            response_id=f"{role}-{generation}",
            input_tokens=10 if complete_measurement else None,
            output_tokens=2,
            cache_read_tokens=0,
            cache_write_tokens=0,
            total_tokens=12,
            cost_usd=0.001,
            duration_ms=3.0,
            stop_reason="stop",
            stop_detail=None,
        )
        return RoleReceipt(
            role=role,
            status="SETTLED",
            output=output,
            candidate_generation=generation,
            model_calls=(call,),
            topology_status="ELIGIBLE",
        )

    return invoke


def test_telemetry_never_changes_the_verified_outcome(tmp_path: Path) -> None:
    frozen = _contract(tmp_path)

    measured = run_measured_role_outcome(
        frozen,
        task="return right",
        max_attempts=1,
        max_input_bytes=1024,
        invoke_role=_invoker(complete_measurement=True),
    )
    missing = run_measured_role_outcome(
        frozen,
        task="return right",
        max_attempts=1,
        max_input_bytes=1024,
        invoke_role=_invoker(complete_measurement=False),
    )

    assert measured.result == missing.result
    assert measured.result.status == "COMPLETE"
    assert measured.result.completion is not None
    assert len(measured.receipts) == 2
    assert [item.model_calls[0].measurement_status for item in measured.receipts] == [
        "COMPLETE",
        "COMPLETE",
    ]
    assert [item.model_calls[0].measurement_status for item in missing.receipts] == [
        "MISSING",
        "MISSING",
    ]


def test_schema_invalid_role_output_is_unresolved_but_remains_measured(
    tmp_path: Path,
) -> None:
    base = _invoker(complete_measurement=True)

    def malformed(role: str, prompt: str, system_prompt: str, generation: int):
        receipt = base(role, prompt, system_prompt, generation)
        return RoleReceipt(
            **{
                **receipt.__dict__,
                "output": "not generator JSON",
            }
        )

    run = run_measured_role_outcome(
        _contract(tmp_path),
        task="return right",
        max_attempts=1,
        max_input_bytes=1024,
        invoke_role=malformed,
    )

    assert run.result.status == "UNRESOLVED"
    assert run.result.reason == "stage_failure:ValueError"
    assert len(run.receipts) == 1
    assert run.receipts[0].model_calls[0].measurement_status == "COMPLETE"
