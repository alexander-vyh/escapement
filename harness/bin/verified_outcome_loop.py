#!/usr/bin/env python3
"""Model proposals complete only from current, certified external evidence."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

from verifier_protocol import (
    VerifierBinding,
    VerifierSnapshot,
    digest_bytes,
    digest_json,
    invoke_snapshot,
    snapshot_binding,
)

_EVIDENCE_RESULTS = frozenset({"PASS", "FAIL", "SKIPPED", "CANNOT_VALIDATE"})
_ASSESSMENT_RESULTS = frozenset({"SATISFIED", "VIOLATED", "INSUFFICIENT_EVIDENCE"})


@dataclass(frozen=True)
class Invariant:
    identifier: str
    statement: str
    verifier: VerifierBinding
    positive_control: bytes = field(repr=False)
    negative_controls: tuple[bytes, ...] = field(repr=False)
    digest: str = ""

    @classmethod
    def freeze(
        cls,
        *,
        identifier: str,
        statement: str,
        verifier: VerifierBinding,
        positive_control: bytes,
        negative_controls: Iterable[bytes],
    ) -> Invariant:
        identity, text = identifier.strip(), statement.strip()
        if not identity or not text or not isinstance(verifier, VerifierBinding):
            raise ValueError("invariant identity, statement, and verifier are required")
        negatives = tuple(negative_controls)
        if not isinstance(positive_control, bytes) or any(
            not isinstance(item, bytes) for item in negatives
        ):
            raise TypeError("controls must be independently specified bytes")
        unique = len(set(negatives)) == len(negatives)
        if not negatives or positive_control in negatives or not unique:
            raise ValueError(
                "negative controls must be unique and differ from positive"
            )
        digest = digest_json(
            {
                "identifier": identity,
                "statement": text,
                "verifier_digest": verifier.digest,
                "positive": digest_bytes(positive_control),
                "negatives": [digest_bytes(item) for item in negatives],
            }
        )
        return cls(identity, text, verifier, positive_control, negatives, digest)


@dataclass(frozen=True)
class FrozenSpec:
    run_id: str
    invariants: tuple[Invariant, ...]
    digest: str
    _snapshots: tuple[VerifierSnapshot, ...] = field(repr=False)

    @classmethod
    def freeze(cls, invariants: Iterable[Invariant]) -> FrozenSpec:
        frozen = tuple(invariants)
        if any(not isinstance(item, Invariant) for item in frozen):
            raise TypeError("all invariants must be frozen Invariant values")
        bindings: dict[str, VerifierBinding] = {}
        verifier_ids: dict[str, str] = {}
        controls: dict[str, tuple[bytes, tuple[bytes, ...]]] = {}
        for item in frozen:
            previous = verifier_ids.setdefault(
                item.verifier.verifier_id, item.verifier.digest
            )
            if previous != item.verifier.digest:
                raise ValueError("one verifier id cannot identify multiple manifests")
            pair = (item.positive_control, item.negative_controls)
            if (
                item.verifier.digest in controls
                and controls[item.verifier.digest] != pair
            ):
                raise ValueError("invariants sharing a verifier must share controls")
            controls[item.verifier.digest] = pair
            bindings[item.verifier.digest] = item.verifier
        snapshots = tuple(snapshot_binding(binding) for binding in bindings.values())
        run_id = str(uuid.uuid4())
        digest = digest_json(
            {"run_id": run_id, "invariants": [item.digest for item in frozen]}
        )
        return cls(run_id, frozen, digest, snapshots)


@dataclass(frozen=True)
class Candidate:
    run_id: str
    generation: int
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        if not self.run_id or self.generation < 1:
            raise ValueError("candidate requires a run and positive generation")
        if not isinstance(self.canonical_bytes, bytes):
            raise TypeError("canonical_bytes must be harness-observed bytes")

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)


@dataclass(frozen=True)
class InvariantEvidence:
    run_id: str
    candidate_generation: int
    candidate_digest: str
    invariant_id: str
    invariant_digest: str
    verifier_id: str
    verifier_digest: str
    result: str
    detail: str = ""

    @classmethod
    def bind(
        cls,
        *,
        frozen: FrozenSpec,
        candidate: Candidate,
        invariant: Invariant,
        result: str,
        detail: str = "",
    ) -> InvariantEvidence:
        return cls(
            frozen.run_id,
            candidate.generation,
            candidate.digest,
            invariant.identifier,
            invariant.digest,
            invariant.verifier.verifier_id,
            invariant.verifier.digest,
            str(result).upper(),
            str(detail),
        )


@dataclass(frozen=True)
class InvariantAssessment:
    run_id: str
    candidate_generation: int
    candidate_digest: str
    invariant_id: str
    invariant_digest: str
    result: str
    detail: str = ""

    @classmethod
    def bind(
        cls,
        *,
        frozen: FrozenSpec,
        candidate: Candidate,
        invariant: Invariant,
        result: str,
        detail: str = "",
    ) -> InvariantAssessment:
        return cls(
            frozen.run_id,
            candidate.generation,
            candidate.digest,
            invariant.identifier,
            invariant.digest,
            str(result).upper(),
            str(detail),
        )


@dataclass(frozen=True)
class AssessmentReceipt:
    role: str
    status: str
    run_id: str
    frozen_spec_digest: str
    candidate_generation: int
    candidate_digest: str
    assessments: tuple[InvariantAssessment, ...]


@dataclass(frozen=True)
class CandidateProposal:
    canonical_bytes: bytes


@dataclass(frozen=True)
class AttemptReceipt:
    candidate: Candidate
    verdict: str
    evidence: tuple[InvariantEvidence, ...]
    assessor: AssessmentReceipt


@dataclass(frozen=True)
class CompletionReceipt:
    run_id: str
    frozen_spec_digest: str
    candidate_generation: int
    candidate_digest: str
    invariant_bindings: tuple[tuple[str, str, str, str], ...]


@dataclass(frozen=True)
class RunResult:
    status: str
    reason: str
    attempts: tuple[AttemptReceipt, ...]
    completion: CompletionReceipt | None = None


def _evidence_identity(item: InvariantEvidence) -> tuple[object, ...]:
    return (
        item.run_id,
        item.candidate_generation,
        item.candidate_digest,
        item.invariant_id,
        item.invariant_digest,
        item.verifier_id,
        item.verifier_digest,
    )


def _expected_evidence(frozen: FrozenSpec, candidate: Candidate, item: Invariant):
    return (
        frozen.run_id,
        candidate.generation,
        candidate.digest,
        item.identifier,
        item.digest,
        item.verifier.verifier_id,
        item.verifier.digest,
    )


def derive_candidate_verdict(
    frozen: FrozenSpec, candidate: Candidate, evidence: Sequence[object]
) -> str:
    if not frozen.invariants or candidate.run_id != frozen.run_id:
        return "UNRESOLVED"
    if len(evidence) != len(frozen.invariants) or any(
        not isinstance(item, InvariantEvidence) for item in evidence
    ):
        return "UNRESOLVED"
    typed = tuple(item for item in evidence if isinstance(item, InvariantEvidence))
    identities = tuple(_evidence_identity(item) for item in typed)
    expected = {
        _expected_evidence(frozen, candidate, item) for item in frozen.invariants
    }
    if len(set(identities)) != len(identities) or set(identities) != expected:
        return "UNRESOLVED"
    if any(item.result not in _EVIDENCE_RESULTS for item in typed):
        return "UNRESOLVED"
    if any(item.result in {"SKIPPED", "CANNOT_VALIDATE"} for item in typed):
        return "UNRESOLVED"
    if any(item.result == "FAIL" for item in typed):
        return "REJECTED"
    return "ACCEPTED" if all(item.result == "PASS" for item in typed) else "UNRESOLVED"


def derive_assessment_verdict(
    frozen: FrozenSpec, candidate: Candidate, receipt: object
) -> str:
    if not isinstance(receipt, AssessmentReceipt):
        return "UNRESOLVED"
    header = (
        receipt.role,
        receipt.status,
        receipt.run_id,
        receipt.frozen_spec_digest,
        receipt.candidate_generation,
        receipt.candidate_digest,
    )
    expected_header = (
        "assessor",
        "SETTLED",
        frozen.run_id,
        frozen.digest,
        candidate.generation,
        candidate.digest,
    )
    if header != expected_header or len(receipt.assessments) != len(frozen.invariants):
        return "UNRESOLVED"
    expected = {
        (
            frozen.run_id,
            candidate.generation,
            candidate.digest,
            item.identifier,
            item.digest,
        )
        for item in frozen.invariants
    }
    identities = {
        (
            item.run_id,
            item.candidate_generation,
            item.candidate_digest,
            item.invariant_id,
            item.invariant_digest,
        )
        for item in receipt.assessments
        if isinstance(item, InvariantAssessment)
    }
    if len(identities) != len(receipt.assessments) or identities != expected:
        return "UNRESOLVED"
    results = tuple(item.result for item in receipt.assessments)
    if any(item not in _ASSESSMENT_RESULTS for item in results):
        return "UNRESOLVED"
    if "INSUFFICIENT_EVIDENCE" in results:
        return "UNRESOLVED"
    return "VIOLATED" if "VIOLATED" in results else "SATISFIED"


def _invoke_snapshot(frozen, snapshot, invariants, candidate_bytes, generation):
    candidate = Candidate(frozen.run_id, generation, candidate_bytes)
    rows = invoke_snapshot(
        run_id=frozen.run_id,
        frozen_spec_digest=frozen.digest,
        snapshot=snapshot,
        invariants=tuple(
            {"id": item.identifier, "statement": item.statement, "digest": item.digest}
            for item in invariants
        ),
        candidate_bytes=candidate_bytes,
        generation=generation,
    )
    if rows is None:
        return ()
    by_id = {item.identifier: item for item in invariants}
    bound: list[InvariantEvidence] = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "invariant_id",
            "verifier_id",
            "result",
            "detail",
        }:
            return ()
        if any(not isinstance(row[key], str) for key in row):
            return ()
        invariant = by_id.get(row["invariant_id"])
        if invariant is None or row["verifier_id"] != snapshot.verifier_id:
            return ()
        if row["result"] not in _EVIDENCE_RESULTS or not isinstance(row["detail"], str):
            return ()
        bound.append(
            InvariantEvidence.bind(
                frozen=frozen,
                candidate=candidate,
                invariant=invariant,
                result=row["result"],
                detail=row["detail"],
            )
        )
    return tuple(bound)


def _groups(frozen: FrozenSpec):
    for snapshot in frozen._snapshots:
        invariants = tuple(
            item
            for item in frozen.invariants
            if item.verifier.digest == snapshot.binding_digest
        )
        yield snapshot, invariants


def certify_frozen_verifiers(frozen: FrozenSpec) -> bool:
    if not frozen.invariants:
        return False
    for snapshot, invariants in _groups(frozen):
        positive = invariants[0].positive_control
        negatives = invariants[0].negative_controls
        positive_candidate = Candidate(frozen.run_id, 1, positive)
        positive_evidence = _invoke_snapshot(frozen, snapshot, invariants, positive, 1)
        group = FrozenSpec(frozen.run_id, invariants, frozen.digest, (snapshot,))
        positive_verdict = derive_candidate_verdict(
            group, positive_candidate, positive_evidence
        )
        if positive_verdict != "ACCEPTED":
            return False
        for negative in negatives:
            candidate = Candidate(frozen.run_id, 1, negative)
            evidence = _invoke_snapshot(frozen, snapshot, invariants, negative, 1)
            if not evidence or any(item.result != "FAIL" for item in evidence):
                return False
            if derive_candidate_verdict(group, candidate, evidence) != "REJECTED":
                return False
    return True


def invoke_external_verifiers(
    frozen: FrozenSpec, candidate: Candidate
) -> tuple[InvariantEvidence, ...]:
    if candidate.run_id != frozen.run_id:
        return ()
    evidence: list[InvariantEvidence] = []
    for snapshot, invariants in _groups(frozen):
        evidence.extend(
            _invoke_snapshot(
                frozen,
                snapshot,
                invariants,
                candidate.canonical_bytes,
                candidate.generation,
            )
        )
    return tuple(evidence)


def _completion_receipt(frozen: FrozenSpec, candidate: Candidate) -> CompletionReceipt:
    return CompletionReceipt(
        frozen.run_id,
        frozen.digest,
        candidate.generation,
        candidate.digest,
        tuple(
            (
                item.identifier,
                item.digest,
                item.verifier.verifier_id,
                item.verifier.digest,
            )
            for item in frozen.invariants
        ),
    )


def run_verified_outcome(
    frozen: FrozenSpec,
    *,
    candidate_role: Callable[[int, AttemptReceipt | None], CandidateProposal],
    assessor_role: Callable[[FrozenSpec, Candidate], AssessmentReceipt],
    max_attempts: int,
) -> RunResult:
    if max_attempts < 1:
        return RunResult("UNRESOLVED", "invalid_attempt_budget", ())
    if not certify_frozen_verifiers(frozen):
        return RunResult("UNRESOLVED", "verifier_certification_failed", ())
    attempts: list[AttemptReceipt] = []
    feedback: AttemptReceipt | None = None
    for generation in range(1, max_attempts + 1):
        try:
            proposal = candidate_role(generation, feedback)
            if not isinstance(proposal, CandidateProposal):
                raise TypeError("candidate role returned an invalid proposal")
            candidate = Candidate(frozen.run_id, generation, proposal.canonical_bytes)
            assessor = assessor_role(frozen, candidate)
        except Exception as exc:
            return RunResult(
                "UNRESOLVED", f"stage_failure:{type(exc).__name__}", tuple(attempts)
            )
        assessment_verdict = derive_assessment_verdict(frozen, candidate, assessor)
        if assessment_verdict == "UNRESOLVED":
            return RunResult("UNRESOLVED", "assessment_unresolved", tuple(attempts))
        evidence = (
            ()
            if assessment_verdict == "VIOLATED"
            else invoke_external_verifiers(frozen, candidate)
        )
        verdict = (
            "REJECTED"
            if assessment_verdict == "VIOLATED"
            else derive_candidate_verdict(frozen, candidate, evidence)
        )
        attempt = AttemptReceipt(candidate, verdict, evidence, assessor)
        attempts.append(attempt)
        if verdict == "ACCEPTED":
            return RunResult(
                "COMPLETE",
                "all_invariants_satisfied",
                tuple(attempts),
                _completion_receipt(frozen, candidate),
            )
        if verdict == "UNRESOLVED":
            return RunResult("UNRESOLVED", "evidence_unresolved", tuple(attempts))
        feedback = attempt
    return RunResult("UNRESOLVED", "attempt_budget_exhausted", tuple(attempts))
