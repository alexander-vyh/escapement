from __future__ import annotations

import json
import stat
import sys
import time
from dataclasses import replace
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
import verifier_protocol  # noqa: E402


def _verifier(tmp_path: Path, mode: str = "honest") -> Path:
    path = tmp_path / f"verifier-{mode}"
    audit = tmp_path / "calls"
    marker = tmp_path / "descendant-survived"
    envelopes = tmp_path / "envelopes"
    cache_path = tmp_path / "cached-response"
    requests = tmp_path / "requests"
    path.write_text(
        f"""#!/usr/bin/env python3
import json
import os
import pathlib
import subprocess
import sys
request = json.load(sys.stdin)
with pathlib.Path({str(requests)!r}).open("a") as stream:
    stream.write(json.dumps(request, sort_keys=True) + "\\n")
envelope = {{
    "argv_shape": [pathlib.Path(item).name for item in sys.argv],
    "cwd_name": pathlib.Path.cwd().name,
    "env_keys": sorted(os.environ),
    "request_keys": sorted(request),
}}
with pathlib.Path({str(envelopes)!r}).open("a") as stream:
    stream.write(json.dumps(envelope, sort_keys=True) + "\\n")
with pathlib.Path({str(audit)!r}).open("a") as stream:
    stream.write(request["candidate_hex"] + "\\n")
cache = pathlib.Path({str(cache_path)!r})
if {mode!r} == "cached" and cache.exists():
    sys.stdout.write(cache.read_text())
    raise SystemExit(0)
if {mode!r} == "descendant":
    code = "import pathlib,time;time.sleep(.5);pathlib.Path({str(marker)!r}).write_text('bad')"
    subprocess.Popen([sys.executable, "-c", code])
result = "PASS" if request["candidate_hex"] == "676f6f640a" else "FAIL"
rows = [{{
    "invariant_id": item["id"],
    "verifier_id": request["verifier"]["id"],
    "result": result,
    "detail": "observed",
}} for item in request["invariants"]]
if {mode!r} == "malformed":
    rows[0]["invariant_id"] = []
    rows[0]["result"] = []
response = {{
    "request_id": request["request_id"],
    "request_digest": request["request_digest"],
    "verifier_digest": request["verifier"]["digest"],
    "results": rows,
}}
encoded = json.dumps(response, sort_keys=True)
if {mode!r} == "cached":
    cache.write_text(encoded)
sys.stdout.write(encoded)
"""
    )
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _contract(tmp_path: Path, mode: str = "honest", count: int = 2) -> FrozenSpec:
    binding = VerifierBinding.freeze(
        verifier_id="semantic-oracle", executable=_verifier(tmp_path, mode)
    )
    controls = (b"bad\n", b"", b"malformed\x00bytes")
    invariants = [
        Invariant.freeze(
            identifier=identifier,
            statement=f"{identifier} must hold",
            verifier=binding,
            positive_control=b"good\n",
            negative_controls=controls,
        )
        for identifier in ("A", "B")[:count]
    ]
    return FrozenSpec.freeze(invariants)


def _assessment(
    frozen: FrozenSpec,
    candidate: Candidate,
    rows: tuple[InvariantAssessment, ...],
) -> AssessmentReceipt:
    return AssessmentReceipt(
        "assessor",
        "SETTLED",
        frozen.run_id,
        frozen.digest,
        candidate.generation,
        candidate.digest,
        rows,
    )


def test_assessor_rejects_identical_and_conflicting_a_a_when_b_missing(
    tmp_path: Path,
) -> None:
    frozen = _contract(tmp_path)
    candidate = Candidate(frozen.run_id, 1, b"good\n")
    a = InvariantAssessment.bind(
        frozen=frozen,
        candidate=candidate,
        invariant=frozen.invariants[0],
        result="SATISFIED",
    )
    conflicting = InvariantAssessment(**{**a.__dict__, "result": "VIOLATED"})

    assert (
        derive_assessment_verdict(
            frozen, candidate, _assessment(frozen, candidate, (a, a))
        )
        == "UNRESOLVED"
    )
    assert (
        derive_assessment_verdict(
            frozen, candidate, _assessment(frozen, candidate, (a, conflicting))
        )
        == "UNRESOLVED"
    )


def test_evidence_rejects_identical_and_conflicting_a_a_when_b_missing(
    tmp_path: Path,
) -> None:
    frozen = _contract(tmp_path)
    candidate = Candidate(frozen.run_id, 1, b"good\n")
    a = InvariantEvidence.bind(
        frozen=frozen,
        candidate=candidate,
        invariant=frozen.invariants[0],
        result="PASS",
    )
    conflicting = InvariantEvidence(**{**a.__dict__, "result": "FAIL"})

    assert derive_candidate_verdict(frozen, candidate, (a, a)) == "UNRESOLVED"
    assert derive_candidate_verdict(frozen, candidate, (a, conflicting)) == "UNRESOLVED"


def test_completion_receipt_carries_full_exact_invariant_bindings(
    tmp_path: Path,
) -> None:
    frozen = _contract(tmp_path)

    def assess(spec: FrozenSpec, candidate: Candidate) -> AssessmentReceipt:
        rows = tuple(
            InvariantAssessment.bind(
                frozen=spec,
                candidate=candidate,
                invariant=invariant,
                result="SATISFIED",
            )
            for invariant in spec.invariants
        )
        return _assessment(spec, candidate, rows)

    result = run_verified_outcome(
        frozen,
        candidate_role=lambda _generation, _feedback: CandidateProposal(b"good\n"),
        assessor_role=assess,
        max_attempts=1,
    )

    assert result.completion is not None
    assert result.completion.invariant_bindings == tuple(
        (
            invariant.identifier,
            invariant.digest,
            invariant.verifier.verifier_id,
            invariant.verifier.digest,
        )
        for invariant in frozen.invariants
    )


def test_malformed_unhashable_verifier_row_is_unresolved_not_exception(
    tmp_path: Path,
) -> None:
    frozen = _contract(tmp_path, "malformed", count=1)
    result = run_verified_outcome(
        frozen,
        candidate_role=lambda _generation, _feedback: CandidateProposal(b"good\n"),
        assessor_role=lambda _spec, _candidate: (_ for _ in ()).throw(
            AssertionError("generator and assessor must be blocked by certification")
        ),
        max_attempts=1,
    )

    assert result.status == "UNRESOLVED"
    assert result.reason == "verifier_certification_failed"
    assert result.completion is None


def test_all_negative_controls_use_same_envelope(tmp_path: Path) -> None:
    frozen = _contract(tmp_path, count=1)

    assert certify_frozen_verifiers(frozen) is True
    assert (tmp_path / "calls").read_text().splitlines() == [
        "676f6f640a",
        "6261640a",
        "",
        "6d616c666f726d6564006279746573",
    ]
    candidate = Candidate(frozen.run_id, 1, b"good\n")
    assert invoke_external_verifiers(frozen, candidate)
    envelopes = (tmp_path / "envelopes").read_text().splitlines()
    assert len(envelopes) == 5
    assert len(set(envelopes)) == 1


def test_successful_verifier_descendant_is_reaped_before_acceptance(
    tmp_path: Path,
) -> None:
    frozen = _contract(tmp_path, "descendant", count=1)

    assert certify_frozen_verifiers(frozen) is True
    time.sleep(0.7)
    assert not (tmp_path / "descendant-survived").exists()


def test_negative_controls_must_be_nonempty(tmp_path: Path) -> None:
    binding = VerifierBinding.freeze(
        verifier_id="empty-controls", executable=_verifier(tmp_path)
    )

    with pytest.raises(ValueError, match="negative controls"):
        Invariant.freeze(
            identifier="A",
            statement="A holds",
            verifier=binding,
            positive_control=b"good\n",
            negative_controls=(),
        )


@pytest.mark.parametrize(
    "dimension", ["run", "spec", "generation", "candidate", "invariants", "verifier"]
)
def test_request_digest_binds_each_identity_even_with_fixed_nonce(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dimension: str
) -> None:
    frozen = _contract(tmp_path, "cached", count=1)
    snapshot = frozen._snapshots[0]
    base: dict[str, object] = {
        "run_id": frozen.run_id,
        "frozen_spec_digest": frozen.digest,
        "snapshot": snapshot,
        "invariants": ({"id": "A", "statement": "A holds", "digest": "a" * 64},),
        "candidate_bytes": b"good\n",
        "generation": 1,
    }
    changed = dict(base)
    changes: dict[str, object] = {
        "run": "different-run",
        "spec": "b" * 64,
        "generation": 2,
        "candidate": b"different\n",
        "invariants": ({"id": "B", "statement": "B holds", "digest": "b" * 64},),
        "verifier": replace(snapshot, binding_digest="c" * 64),
    }
    keys = {
        "run": "run_id",
        "spec": "frozen_spec_digest",
        "generation": "generation",
        "candidate": "candidate_bytes",
        "invariants": "invariants",
        "verifier": "snapshot",
    }
    changed[keys[dimension]] = changes[dimension]
    monkeypatch.setattr(verifier_protocol.secrets, "token_hex", lambda _size: "fixed")

    assert verifier_protocol.invoke_snapshot(**base) is not None  # type: ignore[arg-type]
    assert verifier_protocol.invoke_snapshot(**changed) is None  # type: ignore[arg-type]
    requests = [
        json.loads(row) for row in (tmp_path / "requests").read_text().splitlines()
    ]
    assert requests[-2]["request_id"] == requests[-1]["request_id"] == "fixed"
    assert requests[-2]["request_digest"] != requests[-1]["request_digest"]
