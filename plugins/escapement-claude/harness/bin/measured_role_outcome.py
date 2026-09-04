#!/usr/bin/env python3
"""Collect role-call receipts around the unchanged verified-outcome kernel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from model_call_receipts import RoleReceipt
from pi_verified_outcome_demo import (
    _assessor_prompt,
    _bind_assessment,
    _generator_prompt,
    _require_bounded,
    _validate_frozen_inputs,
    parse_candidate_output,
)
from verified_outcome_loop import (
    AssessmentReceipt,
    AttemptReceipt,
    Candidate,
    CandidateProposal,
    FrozenSpec,
    RunResult,
    run_verified_outcome,
)


RoleInvoker = Callable[[str, str, str, int], RoleReceipt]
GENERATOR_SYSTEM_PROMPT = (
    'Return exactly one JSON object: {"candidate":"<complete content>"}. '
    "Do not add fields, fences, or commentary."
)
ASSESSOR_SYSTEM_PROMPT = (
    "Return exactly one JSON object with only an assessments array. "
    "Each row must have invariant_id, result, and detail; result is "
    "SATISFIED, VIOLATED, or INSUFFICIENT_EVIDENCE. No commentary."
)
GENERATOR_PROMPT_CONTRACT = "pi_verified_outcome_demo._generator_prompt:v1"
ASSESSOR_PROMPT_CONTRACT = "pi_verified_outcome_demo._assessor_prompt:v1"


@dataclass(frozen=True)
class MeasuredOutcomeRun:
    result: RunResult
    receipts: tuple[RoleReceipt, ...]


def _settled(receipt: RoleReceipt, role: str, generation: int) -> str:
    if (
        receipt.status != "SETTLED"
        or receipt.role != role
        or receipt.candidate_generation != generation
    ):
        raise RuntimeError(f"{role} did not settle for generation {generation}")
    return receipt.output


def run_measured_role_outcome(
    frozen: FrozenSpec,
    *,
    task: str,
    max_attempts: int,
    max_input_bytes: int,
    invoke_role: RoleInvoker,
) -> MeasuredOutcomeRun:
    """Run roles and retain receipts; only run_verified_outcome can complete."""
    task_text = task.strip()
    if not task_text:
        raise ValueError("task must be non-empty")
    _require_bounded(task_text.encode("utf-8"), label="task", maximum=max_input_bytes)
    _validate_frozen_inputs(frozen, max_input_bytes)
    receipts: list[RoleReceipt] = []

    def invoke(role: str, prompt: str, system_prompt: str, generation: int) -> str:
        receipt = invoke_role(role, prompt, system_prompt, generation)
        receipts.append(receipt)
        return _settled(receipt, role, generation)

    def candidate_role(
        generation: int, feedback: AttemptReceipt | None
    ) -> CandidateProposal:
        output = invoke(
            "generator",
            _generator_prompt(frozen, task_text, feedback),
            GENERATOR_SYSTEM_PROMPT,
            generation,
        )
        candidate = _require_bounded(
            parse_candidate_output(output).encode("utf-8"),
            label="candidate",
            maximum=max_input_bytes,
        )
        return CandidateProposal(candidate)

    def assessor_role(spec: FrozenSpec, candidate: Candidate) -> AssessmentReceipt:
        output = invoke(
            "assessor",
            _assessor_prompt(spec, candidate),
            ASSESSOR_SYSTEM_PROMPT,
            candidate.generation,
        )
        return _bind_assessment(spec, candidate, output)

    result = run_verified_outcome(
        frozen,
        candidate_role=candidate_role,
        assessor_role=assessor_role,
        max_attempts=max_attempts,
    )
    return MeasuredOutcomeRun(result, tuple(receipts))
