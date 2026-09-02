from __future__ import annotations

import inspect
import stat
import sys
from pathlib import Path

import pytest

BIN = Path(__file__).resolve().parents[1] / "bin"
sys.path.insert(0, str(BIN))

from verified_outcome_loop import (  # noqa: E402
    AssessmentReceipt,
    Candidate,
    CandidateProposal,
    FrozenSpec,
    Invariant,
    InvariantAssessment,
    InvariantEvidence,
    VerifierBinding,
    certify_frozen_verifiers,
    derive_assessment_verdict,
    derive_candidate_verdict,
    invoke_external_verifiers,
    run_verified_outcome,
)


def _make_verifier(tmp_path: Path, mode: str = "honest") -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / f"verifier-{mode}"
    cache = tmp_path / "cached-response.json"
    audit = tmp_path / f"{mode}.calls"
    path.write_text(
        f"""#!/usr/bin/env python3
import json
import pathlib
import sys

request = json.load(sys.stdin)
mode = {mode!r}
cache = pathlib.Path({str(cache)!r})
with pathlib.Path({str(audit)!r}).open("a") as stream:
    stream.write(request["candidate_hex"] + "\\n")
if mode == "cached" and cache.exists():
    sys.stdout.write(cache.read_text())
    raise SystemExit(0)
result = "PASS" if request["candidate_hex"] == "676f6f640a" else "FAIL"
if mode == "always-pass":
    result = "PASS"
if mode == "cert-branch":
    result = result if request.get("purpose") == "certification" else "PASS"
if mode == "skipped":
    result = "SKIPPED"
rows = [{{
    "invariant_id": item["id"],
    "verifier_id": request["verifier"]["id"],
    "result": result,
    "detail": "external observation",
}} for item in request["invariants"]]
if mode == "duplicate":
    rows = rows + rows[:1]
response = {{
    "request_id": request["request_id"],
    "request_digest": request["request_digest"],
    "verifier_digest": request["verifier"]["digest"],
    "results": rows,
}}
encoded = json.dumps(response, sort_keys=True, separators=(",", ":"))
if mode == "cached":
    cache.write_text(encoded)
sys.stdout.write(encoded)
"""
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _contract(tmp_path: Path, mode: str = "honest") -> tuple[FrozenSpec, Invariant]:
    binding = VerifierBinding.freeze(
        verifier_id="exact-output", executable=_make_verifier(tmp_path, mode)
    )
    invariant = Invariant.freeze(
        identifier="exact-bytes",
        statement="candidate bytes are exactly good followed by a newline",
        verifier=binding,
        positive_control=b"good\n",
        negative_controls=(b"bad\n", b"", b"malformed\x00bytes"),
    )
    return FrozenSpec.freeze([invariant]), invariant


def _candidate(
    frozen: FrozenSpec, content: bytes = b"good\n", generation: int = 1
) -> Candidate:
    return Candidate(frozen.run_id, generation, content)


def _assessment(
    frozen: FrozenSpec,
    candidate: Candidate,
    invariant: Invariant,
    result: str = "SATISFIED",
    **receipt_changes: object,
) -> AssessmentReceipt:
    item = InvariantAssessment.bind(
        frozen=frozen, candidate=candidate, invariant=invariant, result=result
    )
    fields: dict[str, object] = {
        "role": "assessor",
        "status": "SETTLED",
        "run_id": frozen.run_id,
        "frozen_spec_digest": frozen.digest,
        "candidate_generation": candidate.generation,
        "candidate_digest": candidate.digest,
        "assessments": (item,),
    }
    fields.update(receipt_changes)
    return AssessmentReceipt(**fields)  # type: ignore[arg-type]


def test_verifier_and_spec_identity_are_frozen_before_candidates(
    tmp_path: Path,
) -> None:
    frozen_one, invariant = _contract(tmp_path)
    frozen_two = FrozenSpec.freeze([invariant])

    assert Path(invariant.verifier.executable).is_absolute()
    assert len(invariant.verifier.executable_digest) == 64
    assert invariant.verifier.artifact_digests[0][0] == invariant.verifier.executable
    assert frozen_one.run_id != frozen_two.run_id
    assert frozen_one.digest != frozen_two.digest
    assert "run_id" not in inspect.signature(FrozenSpec.freeze).parameters


def test_empty_contract_cannot_complete(tmp_path: Path) -> None:
    frozen = FrozenSpec.freeze([])
    candidate = _candidate(frozen)

    assert derive_candidate_verdict(frozen, candidate, ()) == "UNRESOLVED"


@pytest.mark.parametrize("result", ["SKIPPED", "CANNOT_VALIDATE", "UNKNOWN"])
def test_non_pass_evidence_fails_closed(tmp_path: Path, result: str) -> None:
    frozen, invariant = _contract(tmp_path)
    candidate = _candidate(frozen)
    evidence = InvariantEvidence.bind(
        frozen=frozen, candidate=candidate, invariant=invariant, result=result
    )

    assert derive_candidate_verdict(frozen, candidate, (evidence,)) == "UNRESOLVED"


def test_duplicate_and_cross_run_evidence_fail_closed(tmp_path: Path) -> None:
    frozen, invariant = _contract(tmp_path)
    candidate = _candidate(frozen)
    evidence = InvariantEvidence.bind(
        frozen=frozen, candidate=candidate, invariant=invariant, result="PASS"
    )
    other, _ = _contract(tmp_path / "other")
    replay = InvariantEvidence(
        other.run_id,
        evidence.candidate_generation,
        evidence.candidate_digest,
        evidence.invariant_id,
        evidence.invariant_digest,
        evidence.verifier_id,
        evidence.verifier_digest,
        "PASS",
    )

    assert (
        derive_candidate_verdict(frozen, candidate, (evidence, evidence))
        == "UNRESOLVED"
    )
    assert derive_candidate_verdict(frozen, candidate, (replay,)) == "UNRESOLVED"


def test_wrong_generation_candidate_and_verifier_fail_closed(tmp_path: Path) -> None:
    frozen, invariant = _contract(tmp_path)
    candidate = _candidate(frozen)
    valid = InvariantEvidence.bind(
        frozen=frozen, candidate=candidate, invariant=invariant, result="PASS"
    )
    mutations = [
        {"candidate_generation": 2},
        {"candidate_digest": "0" * 64},
        {"invariant_digest": "1" * 64},
        {"verifier_id": "other"},
        {"verifier_digest": "2" * 64},
    ]

    for changes in mutations:
        evidence = InvariantEvidence(
            **{**valid.__dict__, **changes},  # type: ignore[arg-type]
        )
        assert derive_candidate_verdict(frozen, candidate, (evidence,)) == "UNRESOLVED"


def test_external_verifier_binds_fresh_exact_request(tmp_path: Path) -> None:
    frozen, _ = _contract(tmp_path)
    candidate = _candidate(frozen)

    evidence = invoke_external_verifiers(frozen, candidate)

    assert derive_candidate_verdict(frozen, candidate, evidence) == "ACCEPTED"


def test_certification_runs_independent_positive_then_negative_controls(
    tmp_path: Path,
) -> None:
    frozen, _ = _contract(tmp_path)

    assert certify_frozen_verifiers(frozen) is True
    calls = (tmp_path / "honest.calls").read_text().splitlines()
    assert calls == [
        "676f6f640a",
        "6261640a",
        "",
        "6d616c666f726d6564006279746573",
    ]


def test_failed_certification_blocks_candidate_generation(tmp_path: Path) -> None:
    frozen, invariant = _contract(tmp_path, "always-pass")
    called = False

    def generate(_generation: int, _feedback: object) -> CandidateProposal:
        nonlocal called
        called = True
        return CandidateProposal(b"good\n")

    result = run_verified_outcome(
        frozen,
        candidate_role=generate,
        assessor_role=lambda spec, candidate: _assessment(spec, candidate, invariant),
        max_attempts=1,
    )

    assert result.status == "UNRESOLVED"
    assert result.reason == "verifier_certification_failed"
    assert called is False


def test_cached_response_cannot_be_replayed_for_a_new_run(tmp_path: Path) -> None:
    frozen_one, invariant = _contract(tmp_path, "cached")
    assert invoke_external_verifiers(frozen_one, _candidate(frozen_one))
    frozen_two = FrozenSpec.freeze([invariant])

    evidence = invoke_external_verifiers(frozen_two, _candidate(frozen_two))

    assert evidence == ()


def test_unchanged_response_cannot_be_replayed_within_same_run(tmp_path: Path) -> None:
    frozen, _ = _contract(tmp_path, "cached")

    first = invoke_external_verifiers(frozen, _candidate(frozen))
    second = invoke_external_verifiers(frozen, _candidate(frozen))

    assert first
    assert second == ()


def test_original_executable_mutation_after_snapshot_cannot_affect_execution(
    tmp_path: Path,
) -> None:
    frozen, invariant = _contract(tmp_path)
    executable = Path(invariant.verifier.executable)
    executable.write_text(executable.read_text() + "\n# changed after freeze\n")

    evidence = invoke_external_verifiers(frozen, _candidate(frozen))
    assert derive_candidate_verdict(frozen, _candidate(frozen), evidence) == "ACCEPTED"


def test_dependency_change_between_binding_and_snapshot_is_rejected(
    tmp_path: Path,
) -> None:
    executable = _make_verifier(tmp_path)
    helper = tmp_path / "oracle-rules.txt"
    helper.write_text("exact bytes: good newline\n")
    binding = VerifierBinding.freeze(
        verifier_id="manifest", executable=executable, dependencies=[helper]
    )
    helper.write_text("changed before snapshot\n")
    invariant = Invariant.freeze(
        identifier="exact-bytes",
        statement="candidate is exact",
        verifier=binding,
        positive_control=b"good\n",
        negative_controls=(b"bad\n",),
    )
    with pytest.raises(ValueError, match="artifact changed"):
        FrozenSpec.freeze([invariant])


def test_original_dependency_mutation_after_snapshot_cannot_affect_execution(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "verifier-with-helper"
    helper = tmp_path / "oracle_helper.py"
    helper.write_text('EXPECTED_HEX = "676f6f640a"\n')
    executable.write_text(
        """#!/usr/bin/env python3
import json
import sys
from oracle_helper import EXPECTED_HEX
request = json.load(sys.stdin)
result = "PASS" if request["candidate_hex"] == EXPECTED_HEX else "FAIL"
response = {
    "request_id": request["request_id"],
    "request_digest": request["request_digest"],
    "verifier_digest": request["verifier"]["digest"],
    "results": [{
        "invariant_id": item["id"],
        "verifier_id": request["verifier"]["id"],
        "result": result,
        "detail": "snapshotted helper",
    } for item in request["invariants"]],
}
json.dump(response, sys.stdout)
"""
    )
    executable.chmod(executable.stat().st_mode | stat.S_IXUSR)
    binding = VerifierBinding.freeze(
        verifier_id="manifest", executable=executable, dependencies=[helper]
    )
    invariant = Invariant.freeze(
        identifier="exact-bytes",
        statement="candidate is exact",
        verifier=binding,
        positive_control=b"good\n",
        negative_controls=(b"bad\n",),
    )
    frozen = FrozenSpec.freeze([invariant])
    helper.write_text('EXPECTED_HEX = "6261640a"\n')

    assert certify_frozen_verifiers(frozen) is True
    evidence = invoke_external_verifiers(frozen, _candidate(frozen))
    assert derive_candidate_verdict(frozen, _candidate(frozen), evidence) == "ACCEPTED"


def test_symlinked_manifest_artifacts_are_rejected(tmp_path: Path) -> None:
    executable = _make_verifier(tmp_path)
    link = tmp_path / "verifier-link"
    link.symlink_to(executable)

    with pytest.raises(ValueError, match="symlink"):
        VerifierBinding.freeze(verifier_id="linked", executable=link)


def test_certification_has_no_distinguishing_request_envelope(tmp_path: Path) -> None:
    frozen, _ = _contract(tmp_path, "cert-branch")

    assert certify_frozen_verifiers(frozen) is False


def test_duplicate_verifier_results_fail_closed(tmp_path: Path) -> None:
    frozen, _ = _contract(tmp_path, "duplicate")

    evidence = invoke_external_verifiers(frozen, _candidate(frozen))

    assert (
        derive_candidate_verdict(frozen, _candidate(frozen), evidence) == "UNRESOLVED"
    )


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"role": "generator"}, "UNRESOLVED"),
        ({"status": "ERROR"}, "UNRESOLVED"),
        ({"run_id": "stale"}, "UNRESOLVED"),
        ({"frozen_spec_digest": "0" * 64}, "UNRESOLVED"),
        ({"candidate_generation": 99}, "UNRESOLVED"),
        ({"candidate_digest": "1" * 64}, "UNRESOLVED"),
    ],
)
def test_assessment_receipt_requires_exact_current_identity(
    tmp_path: Path, changes: dict[str, object], expected: str
) -> None:
    frozen, invariant = _contract(tmp_path)
    candidate = _candidate(frozen)

    assert (
        derive_assessment_verdict(
            frozen, candidate, _assessment(frozen, candidate, invariant, **changes)
        )
        == expected
    )


def test_assessment_requires_full_unique_coverage(tmp_path: Path) -> None:
    frozen, invariant = _contract(tmp_path)
    candidate = _candidate(frozen)
    valid = _assessment(frozen, candidate, invariant)
    missing = AssessmentReceipt(**{**valid.__dict__, "assessments": ()})
    duplicate = AssessmentReceipt(
        **{**valid.__dict__, "assessments": valid.assessments * 2}
    )
    unknown_item = InvariantAssessment(
        candidate.run_id,
        candidate.generation,
        candidate.digest,
        "unknown",
        "2" * 64,
        "SATISFIED",
    )
    unknown = AssessmentReceipt(**{**valid.__dict__, "assessments": (unknown_item,)})

    assert derive_assessment_verdict(frozen, candidate, missing) == "UNRESOLVED"
    assert derive_assessment_verdict(frozen, candidate, duplicate) == "UNRESOLVED"
    assert derive_assessment_verdict(frozen, candidate, unknown) == "UNRESOLVED"


@pytest.mark.parametrize(
    ("assessment", "expected"),
    [
        ("SATISFIED", "SATISFIED"),
        ("VIOLATED", "VIOLATED"),
        ("INSUFFICIENT_EVIDENCE", "UNRESOLVED"),
        ("MAYBE", "UNRESOLVED"),
    ],
)
def test_assessment_result_derivation(
    tmp_path: Path, assessment: str, expected: str
) -> None:
    frozen, invariant = _contract(tmp_path)
    candidate = _candidate(frozen)
    receipt = _assessment(frozen, candidate, invariant, assessment)

    assert derive_assessment_verdict(frozen, candidate, receipt) == expected


def test_run_repairs_violation_then_requires_external_pass(tmp_path: Path) -> None:
    frozen, invariant = _contract(tmp_path)
    proposals = iter((CandidateProposal(b"bad\n"), CandidateProposal(b"good\n")))

    def assess(spec: FrozenSpec, candidate: Candidate) -> AssessmentReceipt:
        result = "VIOLATED" if candidate.canonical_bytes == b"bad\n" else "SATISFIED"
        return _assessment(spec, candidate, invariant, result)

    result = run_verified_outcome(
        frozen,
        candidate_role=lambda _generation, _feedback: next(proposals),
        assessor_role=assess,
        max_attempts=2,
    )

    assert result.status == "COMPLETE"
    assert [attempt.verdict for attempt in result.attempts] == ["REJECTED", "ACCEPTED"]
    assert result.completion is not None
    assert result.completion.candidate_generation == 2


def test_assessor_satisfaction_cannot_override_external_failure(tmp_path: Path) -> None:
    frozen, invariant = _contract(tmp_path)

    result = run_verified_outcome(
        frozen,
        candidate_role=lambda _generation, _feedback: CandidateProposal(b"bad\n"),
        assessor_role=lambda spec, candidate: _assessment(spec, candidate, invariant),
        max_attempts=1,
    )

    assert result.status == "UNRESOLVED"
    assert result.attempts[0].verdict == "REJECTED"


def test_run_has_no_caller_supplied_verifier_authority() -> None:
    assert "verifier" not in inspect.signature(run_verified_outcome).parameters


def test_attempt_exhaustion_is_not_completion(tmp_path: Path) -> None:
    frozen, invariant = _contract(tmp_path)

    result = run_verified_outcome(
        frozen,
        candidate_role=lambda _generation, _feedback: CandidateProposal(b"bad\n"),
        assessor_role=lambda spec, candidate: _assessment(
            spec, candidate, invariant, "VIOLATED"
        ),
        max_attempts=2,
    )

    assert result.status == "UNRESOLVED"
    assert result.reason == "attempt_budget_exhausted"
    assert len(result.attempts) == 2
