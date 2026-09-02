#!/usr/bin/env python3
"""Pi-backed walking skeleton for the verified-outcome authority kernel."""

from __future__ import annotations

import argparse
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from pi_role_invocation import PiRoleRequest, RoleReceipt, invoke_pi_role
from verified_outcome_loop import (
    AssessmentReceipt,
    AttemptReceipt,
    Candidate,
    CandidateProposal,
    FrozenSpec,
    Invariant,
    InvariantAssessment,
    RunResult,
    VerifierBinding,
    run_verified_outcome,
)

_ASSESSMENT_RESULTS = frozenset({"SATISFIED", "VIOLATED", "INSUFFICIENT_EVIDENCE"})
DEFAULT_MAX_INPUT_BYTES = 1_048_576


@dataclass(frozen=True)
class PiOutcomeConfig:
    pi_runtime: str | Path
    config_root: str | Path
    cwd: str | Path
    provider: str | None = None
    model: str | None = None
    thinking: str = "off"
    timeout: float = 60.0
    max_attempts: int = 3
    max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES
    auth_env: Mapping[str, str] | None = None


def _exact_object(raw: str, keys: set[str], label: str) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} output contains duplicate keys")
            result[key] = value
        return result

    payload = raw
    if raw.startswith("```"):
        prefix, suffix = "```json\n", "\n```"
        if not raw.startswith(prefix) or not raw.endswith(suffix):
            raise ValueError(f"{label} output has an invalid JSON fence")
        payload = raw[len(prefix) : -len(suffix)]
    try:
        value = json.loads(payload, object_pairs_hook=reject_duplicates)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} output must be one JSON object") from exc
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{label} output has an invalid schema")
    return value


def parse_candidate_output(raw: str) -> str:
    """Parse the complete generator response; commentary and extra fields fail."""
    value = _exact_object(raw, {"candidate"}, "generator")
    candidate = value["candidate"]
    if not isinstance(candidate, str):
        raise ValueError("generator candidate must be a string")
    return candidate


def parse_assessment_output(raw: str) -> tuple[dict[str, str], ...]:
    """Parse strict assessor rows without trusting model-supplied bindings."""
    value = _exact_object(raw, {"assessments"}, "assessor")
    rows = value["assessments"]
    if not isinstance(rows, list):
        raise ValueError("assessments must be a list")
    parsed: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "invariant_id",
            "result",
            "detail",
        }:
            raise ValueError("assessment row has an invalid schema")
        if not all(isinstance(row[key], str) for key in row):
            raise ValueError("assessment row values must be strings")
        result = row["result"]
        if result not in _ASSESSMENT_RESULTS:
            raise ValueError("assessment result is invalid")
        parsed.append(
            {
                "invariant_id": row["invariant_id"],
                "result": result,
                "detail": row["detail"],
            }
        )
    return tuple(parsed)


def _invariants_for_generator(frozen: FrozenSpec) -> list[dict[str, str]]:
    return [
        {"id": item.identifier, "statement": item.statement}
        for item in frozen.invariants
    ]


def _prior_attempt(feedback: AttemptReceipt | None) -> dict[str, object] | None:
    if feedback is None:
        return None
    return {
        "candidate_digest": feedback.candidate.digest,
        "generation": feedback.candidate.generation,
        "verdict": feedback.verdict,
        "assessment": [
            {
                "invariant_id": item.invariant_id,
                "result": item.result,
                "detail": item.detail,
            }
            for item in feedback.assessor.assessments
        ],
        "verification": [
            {
                "invariant_id": item.invariant_id,
                "result": item.result,
                "detail": item.detail,
            }
            for item in feedback.evidence
        ],
    }


def _generator_prompt(
    frozen: FrozenSpec, task: str, feedback: AttemptReceipt | None
) -> str:
    return json.dumps(
        {
            "task": task,
            "invariants": _invariants_for_generator(frozen),
            "prior_attempt": _prior_attempt(feedback),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _assessor_prompt(frozen: FrozenSpec, candidate: Candidate) -> str:
    return json.dumps(
        {
            "frozen_spec": {
                "run_id": frozen.run_id,
                "digest": frozen.digest,
                "invariants": [
                    {
                        "id": item.identifier,
                        "statement": item.statement,
                        "digest": item.digest,
                    }
                    for item in frozen.invariants
                ],
            },
            "candidate": {
                "generation": candidate.generation,
                "digest": candidate.digest,
                "content": candidate.canonical_bytes.decode("utf-8", errors="strict"),
            },
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _invoke(
    config: PiOutcomeConfig,
    *,
    role: str,
    prompt: str,
    system_prompt: str,
    generation: int,
) -> RoleReceipt:
    return invoke_pi_role(
        PiRoleRequest(
            role=role,
            prompt=prompt,
            provider=config.provider,
            model=config.model,
            system_prompt=system_prompt,
            thinking=config.thinking,
            timeout=config.timeout,
            candidate_generation=generation,
        ),
        pi_runtime=config.pi_runtime,
        config_root=config.config_root,
        cwd=config.cwd,
        auth_env=config.auth_env,
    )


def _require_settled(receipt: RoleReceipt, role: str, generation: int) -> str:
    if (
        receipt.status != "SETTLED"
        or receipt.role != role
        or receipt.candidate_generation != generation
    ):
        raise RuntimeError(f"{role} did not settle for generation {generation}")
    return receipt.output


def _bind_assessment(
    frozen: FrozenSpec, candidate: Candidate, raw: str
) -> AssessmentReceipt:
    rows = parse_assessment_output(raw)
    by_id = {item.identifier: item for item in frozen.invariants}
    row_ids = [row["invariant_id"] for row in rows]
    if len(row_ids) != len(set(row_ids)) or set(row_ids) != set(by_id):
        raise ValueError("assessor must return one row for every invariant")
    assessments = tuple(
        InvariantAssessment.bind(
            frozen=frozen,
            candidate=candidate,
            invariant=by_id[row["invariant_id"]],
            result=row["result"],
            detail=row["detail"],
        )
        for row in rows
    )
    return AssessmentReceipt(
        role="assessor",
        status="SETTLED",
        run_id=frozen.run_id,
        frozen_spec_digest=frozen.digest,
        candidate_generation=candidate.generation,
        candidate_digest=candidate.digest,
        assessments=assessments,
    )


def _require_bounded(value: bytes, *, label: str, maximum: int) -> bytes:
    if maximum < 1:
        raise ValueError("max_input_bytes must be positive")
    if len(value) > maximum:
        raise ValueError(f"{label} exceeds max_input_bytes")
    return value


def _validate_frozen_inputs(frozen: FrozenSpec, maximum: int) -> None:
    for invariant in frozen.invariants:
        _require_bounded(
            invariant.positive_control,
            label="positive control",
            maximum=maximum,
        )
        for negative in invariant.negative_controls:
            _require_bounded(
                negative,
                label="negative control",
                maximum=maximum,
            )


def run_pi_verified_outcome(
    frozen: FrozenSpec,
    *,
    task: str,
    config: PiOutcomeConfig,
) -> RunResult:
    """Run a fresh generator and assessor process for each bounded attempt."""
    task_text = task.strip()
    if not task_text:
        raise ValueError("task must be non-empty")
    _require_bounded(
        task_text.encode("utf-8"), label="task", maximum=config.max_input_bytes
    )
    _validate_frozen_inputs(frozen, config.max_input_bytes)

    def candidate_role(
        generation: int, feedback: AttemptReceipt | None
    ) -> CandidateProposal:
        receipt = _invoke(
            config,
            role="generator",
            prompt=_generator_prompt(frozen, task_text, feedback),
            system_prompt=(
                'Return exactly one JSON object: {"candidate":"<complete content>"}. '
                "Do not add fields, fences, or commentary."
            ),
            generation=generation,
        )
        output = _require_settled(receipt, "generator", generation)
        candidate_bytes = parse_candidate_output(output).encode("utf-8")
        return CandidateProposal(
            _require_bounded(
                candidate_bytes,
                label="candidate",
                maximum=config.max_input_bytes,
            )
        )

    def assessor_role(spec: FrozenSpec, candidate: Candidate) -> AssessmentReceipt:
        receipt = _invoke(
            config,
            role="assessor",
            prompt=_assessor_prompt(spec, candidate),
            system_prompt=(
                "Return exactly one JSON object with only an assessments array. "
                "Each row must have invariant_id, result, and detail; result is "
                "SATISFIED, VIOLATED, or INSUFFICIENT_EVIDENCE. No commentary."
            ),
            generation=candidate.generation,
        )
        output = _require_settled(receipt, "assessor", candidate.generation)
        return _bind_assessment(spec, candidate, output)

    return run_verified_outcome(
        frozen,
        candidate_role=candidate_role,
        assessor_role=assessor_role,
        max_attempts=config.max_attempts,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True)
    parser.add_argument("--invariant-id", required=True)
    parser.add_argument("--invariant", required=True)
    parser.add_argument("--verifier-id", required=True)
    parser.add_argument("--verifier", type=Path, required=True)
    parser.add_argument("--positive-control", type=Path, required=True)
    parser.add_argument("--negative-control", type=Path, action="append", required=True)
    parser.add_argument("--pi-runtime", type=Path, required=True)
    parser.add_argument("--config-root", type=Path, required=True)
    parser.add_argument("--cwd", type=Path, default=Path.cwd())
    parser.add_argument("--provider")
    parser.add_argument("--model")
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--max-input-bytes", type=int, default=DEFAULT_MAX_INPUT_BYTES)
    parser.add_argument("--auth-env-key", action="append", default=[])
    return parser


def _read_bounded_control(path: Path, *, label: str, maximum: int) -> bytes:
    if maximum < 1:
        raise ValueError("max_input_bytes must be positive")
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError(f"{label} must be a regular non-symlink file")
        if info.st_size > maximum:
            raise ValueError(f"{label} exceeds max_input_bytes")
        stream = os.fdopen(descriptor, "rb")
        descriptor = -1
        with stream:
            value = stream.read(maximum + 1)
    except OSError as exc:
        raise ValueError(f"{label} must be a regular non-symlink file") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return _require_bounded(value, label=label, maximum=maximum)


def _result_json(result: RunResult) -> dict[str, object]:
    return {
        "status": result.status,
        "reason": result.reason,
        "attempts": [
            {
                "generation": attempt.candidate.generation,
                "candidate_digest": attempt.candidate.digest,
                "verdict": attempt.verdict,
                "assessment": [
                    {
                        "run_id": item.run_id,
                        "candidate_generation": item.candidate_generation,
                        "candidate_digest": item.candidate_digest,
                        "invariant_id": item.invariant_id,
                        "invariant_digest": item.invariant_digest,
                        "result": item.result,
                        "detail": item.detail,
                    }
                    for item in attempt.assessor.assessments
                ],
                "evidence": [
                    {
                        "run_id": item.run_id,
                        "candidate_generation": item.candidate_generation,
                        "candidate_digest": item.candidate_digest,
                        "invariant_id": item.invariant_id,
                        "invariant_digest": item.invariant_digest,
                        "verifier_id": item.verifier_id,
                        "verifier_digest": item.verifier_digest,
                        "result": item.result,
                        "detail": item.detail,
                    }
                    for item in attempt.evidence
                ],
            }
            for attempt in result.attempts
        ],
        "completion": None
        if result.completion is None
        else {
            "run_id": result.completion.run_id,
            "frozen_spec_digest": result.completion.frozen_spec_digest,
            "candidate_generation": result.completion.candidate_generation,
            "candidate_digest": result.completion.candidate_digest,
            "invariant_bindings": [
                {
                    "invariant_id": invariant_id,
                    "invariant_digest": invariant_digest,
                    "verifier_id": verifier_id,
                    "verifier_digest": verifier_digest,
                }
                for (
                    invariant_id,
                    invariant_digest,
                    verifier_id,
                    verifier_digest,
                ) in result.completion.invariant_bindings
            ],
        },
    }


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.max_input_bytes < 1:
        raise ValueError("max_input_bytes must be positive")
    auth_env = {key: os.environ[key] for key in args.auth_env_key if key in os.environ}
    binding = VerifierBinding.freeze(
        verifier_id=args.verifier_id,
        executable=args.verifier.resolve(),
    )
    invariant = Invariant.freeze(
        identifier=args.invariant_id,
        statement=args.invariant,
        verifier=binding,
        positive_control=_read_bounded_control(
            args.positive_control,
            label="positive control",
            maximum=args.max_input_bytes,
        ),
        negative_controls=tuple(
            _read_bounded_control(
                path,
                label="negative control",
                maximum=args.max_input_bytes,
            )
            for path in args.negative_control
        ),
    )
    result = run_pi_verified_outcome(
        FrozenSpec.freeze([invariant]),
        task=args.task,
        config=PiOutcomeConfig(
            pi_runtime=args.pi_runtime,
            config_root=args.config_root,
            cwd=args.cwd,
            provider=args.provider,
            model=args.model,
            timeout=args.timeout,
            max_attempts=args.max_attempts,
            max_input_bytes=args.max_input_bytes,
            auth_env=auth_env,
        ),
    )
    print(json.dumps(_result_json(result), sort_keys=True))
    return 0 if result.status == "COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
