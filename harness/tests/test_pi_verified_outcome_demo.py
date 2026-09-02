"""Executable walking-skeleton tests for Pi-backed verified outcomes."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from uuid import UUID

import pytest


REPO = Path(__file__).resolve().parents[2]
BIN = REPO / "harness" / "bin"
sys.path.insert(0, str(BIN))

from pi_verified_outcome_demo import (  # noqa: E402
    PiOutcomeConfig,
    _read_bounded_control,
    parse_assessment_output,
    parse_candidate_output,
    run_pi_verified_outcome,
)
from verified_outcome_loop import FrozenSpec, Invariant, VerifierBinding  # noqa: E402


EXPECTED_BYTES = b"beta\nalpha\nbeta\n"
EXPECTED_DIGEST = "f17db5ee35928b2fc583afc76b6fab57588b556bad364fe2f16195a3950d2142"
REQUIRED_FLAGS = {
    "--mode",
    "--print",
    "--no-session",
    "--no-tools",
    "--no-extensions",
    "--no-skills",
    "--no-prompt-templates",
    "--no-themes",
    "--no-context-files",
    "--no-approve",
}


def _write_executable(path: Path, body: str) -> Path:
    path.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _sealed_verifier(tmp_path: Path) -> Path:
    audit = tmp_path / "verifier-audit.jsonl"
    return _write_executable(
        tmp_path / "sealed-verifier",
        """import json
import pathlib
import sys

request = json.load(sys.stdin)
candidate = bytes.fromhex(request["candidate_hex"])
with pathlib.Path(__AUDIT__).open("a", encoding="utf-8") as stream:
    stream.write(request["candidate_hex"] + "\\n")
result = "PASS" if candidate == b"beta\\nalpha\\nbeta\\n" else "FAIL"
response = {
    "request_id": request["request_id"],
    "request_digest": request["request_digest"],
    "verifier_digest": request["verifier"]["digest"],
    "results": [
        {
            "invariant_id": item["id"],
            "verifier_id": request["verifier"]["id"],
            "result": result,
            "detail": "sealed exact-byte comparison",
        }
        for item in request["invariants"]
    ],
}
json.dump(response, sys.stdout, sort_keys=True, separators=(",", ":"))
""".replace("__AUDIT__", repr(str(audit))),
    )


def _fake_pi(tmp_path: Path, *, first_candidate: str = "wrong\n") -> tuple[Path, Path]:
    audit = tmp_path / "pi-audit.jsonl"
    executable = _write_executable(
        tmp_path / "fake-pi",
        f"""import json
import os
import pathlib
import sys

args = sys.argv[1:]
prompt = json.loads(args[-1])
first_candidate = {first_candidate!r}
config_dir = os.environ["PI_CODING_AGENT_DIR"]
role = pathlib.Path(config_dir).name.split("-", 1)[0]
record = {{
    "pid": os.getpid(),
    "role": role,
    "config_dir": config_dir,
    "args": args,
    "prompt": prompt,
    "ambient_secret_present": "ESCAPEMENT_SECRET_CANARY" in os.environ,
}}
with pathlib.Path({str(audit)!r}).open("a", encoding="utf-8") as stream:
    stream.write(json.dumps(record, sort_keys=True) + "\\n")

if role == "generator":
    candidate = first_candidate if prompt["prior_attempt"] is None else "beta\\nalpha\\nbeta\\n"
    result = json.dumps({{"candidate": candidate}}, separators=(",", ":"))
elif role == "assessor":
    result = json.dumps({{
        "assessments": [
            {{
                "invariant_id": item["id"],
                "result": "SATISFIED",
                "detail": "model approves candidate",
            }}
            for item in prompt["frozen_spec"]["invariants"]
        ]
    }}, separators=(",", ":"))
else:
    raise SystemExit(3)

event = {{
    "type": "message_end",
    "message": {{
        "role": "assistant",
        "content": [{{"type": "text", "text": result}}],
        "stopReason": "stop",
    }},
}}
print(json.dumps(event, separators=(",", ":")))
print('{{"type":"agent_settled"}}')
""",
    )
    return executable, audit


def _contract(tmp_path: Path) -> FrozenSpec:
    binding = VerifierBinding.freeze(
        verifier_id="sealed-exact-output",
        executable=_sealed_verifier(tmp_path),
    )
    invariant = Invariant.freeze(
        identifier="exact-order-and-multiplicity",
        statement="candidate is exactly beta, alpha, beta, one per line",
        verifier=binding,
        positive_control=EXPECTED_BYTES,
        negative_controls=(b"alpha\nbeta\n", b"", b"\xff\x00"),
    )
    return FrozenSpec.freeze([invariant])


@pytest.mark.parametrize(
    "raw",
    [
        '{"candidate":"ok"} commentary',
        'prefix ```json\n{"candidate":"ok"}\n```',
        '```json\n{"candidate":"ok"}\n``` suffix',
        '```json\n{"candidate":"first"}\n```\n```json\n{"candidate":"second"}\n```',
        '```JSON\n{"candidate":"ok"}\n```',
        '{"candidate":"ok","rationale":"trust me"}',
        '{"candidate":3}',
        '{"candidate":"first","candidate":"second"}',
    ],
)
def test_candidate_output_is_exact_json_without_extra_fields(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_candidate_output(raw)


@pytest.mark.parametrize(
    "raw",
    [
        '{"assessments":[]} trailing',
        'prefix ```json\n{"assessments":[]}\n```',
        '```json\n{"assessments":[]}\n``` trailing',
        '```json\n{"assessments":[]}\n```\n```json\n{"assessments":[]}\n```',
        '{"assessments":[],"approved":true}',
        '{"assessments":[{"invariant_id":"one","result":"satisfied","detail":""}]}',
    ],
)
def test_assessment_output_is_exact_json_without_commentary(raw: str) -> None:
    with pytest.raises(ValueError):
        parse_assessment_output(raw)


def test_one_exact_lowercase_json_fence_is_an_allowed_transport_envelope() -> None:
    assert parse_candidate_output('```json\n{"candidate":"ok"}\n```') == "ok"
    assert parse_assessment_output(
        '```json\n{"assessments":['
        '{"invariant_id":"one","result":"SATISFIED","detail":"ok"}'
        "]}\n```"
    ) == (
        {
            "invariant_id": "one",
            "result": "SATISFIED",
            "detail": "ok",
        },
    )


def test_fenced_json_may_contain_triple_backticks_as_string_data() -> None:
    assert (
        parse_candidate_output('```json\n{"candidate":"contains ``` safely"}\n```')
        == "contains ``` safely"
    )


def test_callable_rejects_oversized_task_and_controls_before_any_role(
    tmp_path: Path,
) -> None:
    fake_pi, audit = _fake_pi(tmp_path)
    frozen = _contract(tmp_path)
    config = PiOutcomeConfig(
        pi_runtime=fake_pi,
        config_root=tmp_path / "role-homes",
        cwd=tmp_path,
        max_input_bytes=8,
    )

    with pytest.raises(ValueError, match="task exceeds"):
        run_pi_verified_outcome(frozen, task="nine-byte", config=config)
    with pytest.raises(ValueError, match="positive control exceeds"):
        run_pi_verified_outcome(frozen, task="small", config=config)
    assert not audit.exists()


def test_oversized_generated_candidate_fails_closed_before_assessment(
    tmp_path: Path,
) -> None:
    fake_pi, audit = _fake_pi(tmp_path, first_candidate="x" * 33)
    result = run_pi_verified_outcome(
        _contract(tmp_path),
        task="small",
        config=PiOutcomeConfig(
            pi_runtime=fake_pi,
            config_root=tmp_path / "role-homes",
            cwd=tmp_path,
            max_input_bytes=32,
        ),
    )

    assert result.status == "UNRESOLVED"
    assert result.reason == "stage_failure:ValueError"
    assert result.attempts == ()
    records = [json.loads(line) for line in audit.read_text().splitlines()]
    assert [record["role"] for record in records] == ["generator"]


def test_cli_control_reader_rejects_oversized_file_before_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    positive = tmp_path / "positive.txt"
    positive.write_bytes(b"x" * 33)

    def forbidden_fdopen(*args: object, **kwargs: object) -> object:
        raise AssertionError("oversized control must not be read")

    monkeypatch.setattr(os, "fdopen", forbidden_fdopen)

    with pytest.raises(ValueError, match="positive control exceeds"):
        _read_bounded_control(positive, label="positive control", maximum=32)


def test_control_read_stays_bounded_when_stat_underreports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "growing-control"
    path.write_bytes(b"x")
    observed: list[int] = []

    class GrowingStream:
        def __enter__(self) -> GrowingStream:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, size: int) -> bytes:
            observed.append(size)
            return b"x" * size

    real_fstat = os.fstat

    def underreported_fstat(descriptor: int) -> object:
        info = real_fstat(descriptor)
        return type("S", (), {"st_size": 1, "st_mode": info.st_mode})()

    monkeypatch.setattr(os, "fstat", underreported_fstat)
    monkeypatch.setattr(os, "fdopen", lambda descriptor, mode: GrowingStream())

    with pytest.raises(ValueError, match="control exceeds"):
        _read_bounded_control(path, label="control", maximum=32)
    assert observed == [33]


def test_control_reader_accepts_exact_maximum_bytes(tmp_path: Path) -> None:
    path = tmp_path / "exactly-full-control"
    path.write_bytes(b"x" * 32)

    assert _read_bounded_control(path, label="control", maximum=32) == b"x" * 32


@pytest.mark.skipif(os.name != "posix", reason="FIFO and symlink are POSIX controls")
def test_control_must_be_regular_and_not_symlink_without_blocking(
    tmp_path: Path,
) -> None:
    target = tmp_path / "target"
    link = tmp_path / "link"
    fifo = tmp_path / "fifo"
    target.write_bytes(b"small")
    link.symlink_to(target)
    os.mkfifo(fifo)

    for path in (link, fifo):
        with pytest.raises(ValueError, match="regular non-symlink"):
            _read_bounded_control(path, label="control", maximum=32)


def test_real_subprocess_roles_repair_until_sealed_oracle_accepts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_pi, audit = _fake_pi(tmp_path)
    frozen = _contract(tmp_path)
    config_root = tmp_path / "role-homes"
    monkeypatch.setenv("ESCAPEMENT_SECRET_CANARY", "must-not-cross")

    result = run_pi_verified_outcome(
        frozen,
        task="Produce the exact ordered lines required by the invariant.",
        config=PiOutcomeConfig(
            pi_runtime=fake_pi,
            config_root=config_root,
            cwd=tmp_path,
            provider="anthropic",
            model="fake-model",
            timeout=5,
            max_attempts=2,
        ),
    )

    assert result.status == "COMPLETE"
    assert result.reason == "all_invariants_satisfied"
    assert result.completion is not None
    assert result.completion.candidate_generation == 2
    assert result.completion.candidate_digest == EXPECTED_DIGEST
    assert [attempt.verdict for attempt in result.attempts] == ["REJECTED", "ACCEPTED"]
    assert result.attempts[0].assessor.assessments[0].result == "SATISFIED"
    assert result.attempts[0].evidence[0].result == "FAIL"
    assert result.attempts[1].candidate.canonical_bytes == EXPECTED_BYTES

    records = [json.loads(line) for line in audit.read_text().splitlines()]
    assert [record["role"] for record in records] == [
        "generator",
        "assessor",
        "generator",
        "assessor",
    ]
    assert len({record["pid"] for record in records}) == 4
    assert len({record["config_dir"] for record in records}) == 4
    assert all(not Path(record["config_dir"]).exists() for record in records)
    assert all(not record["ambient_secret_present"] for record in records)
    assert all(REQUIRED_FLAGS.issubset(set(record["args"])) for record in records)
    generator_prompts = [
        record["prompt"] for record in records if record["role"] == "generator"
    ]
    assessor_prompts = [
        record["prompt"] for record in records if record["role"] == "assessor"
    ]
    assert all(
        set(prompt) == {"task", "invariants", "prior_attempt"}
        for prompt in generator_prompts
    )
    assert generator_prompts[0]["prior_attempt"] is None
    assert generator_prompts[1]["prior_attempt"]["verdict"] == "REJECTED"
    assert all(
        set(prompt) == {"frozen_spec", "candidate"} for prompt in assessor_prompts
    )
    assert os.listdir(config_root) == []


def test_command_line_runs_the_same_verified_path(tmp_path: Path) -> None:
    fake_pi, _ = _fake_pi(tmp_path)
    verifier = _sealed_verifier(tmp_path)
    positive = tmp_path / "positive.txt"
    negative = tmp_path / "negative.txt"
    empty = tmp_path / "empty.txt"
    malformed = tmp_path / "malformed.bin"
    positive.write_bytes(EXPECTED_BYTES)
    negative.write_bytes(b"wrong\n")
    empty.write_bytes(b"")
    malformed.write_bytes(b"\xff\x00")

    completed = subprocess.run(
        (
            sys.executable,
            str(BIN / "pi_verified_outcome_demo.py"),
            "--task",
            "Produce the ordered lines.",
            "--invariant-id",
            "exact-order-and-multiplicity",
            "--invariant",
            "candidate is exactly beta, alpha, beta, one per line",
            "--verifier-id",
            "sealed-exact-output",
            "--verifier",
            str(verifier),
            "--positive-control",
            str(positive),
            "--negative-control",
            str(negative),
            "--negative-control",
            str(empty),
            "--negative-control",
            str(malformed),
            "--pi-runtime",
            str(fake_pi),
            "--config-root",
            str(tmp_path / "cli-role-homes"),
            "--cwd",
            str(tmp_path),
            "--max-attempts",
            "2",
            "--timeout",
            "5",
        ),
        check=False,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "COMPLETE"
    completion = payload["completion"]
    assert set(completion) == {
        "run_id",
        "frozen_spec_digest",
        "candidate_generation",
        "candidate_digest",
        "invariant_bindings",
    }
    assert str(UUID(completion["run_id"])) == completion["run_id"]
    assert re.fullmatch(r"[0-9a-f]{64}", completion["frozen_spec_digest"])
    assert completion["candidate_generation"] == 2
    assert completion["candidate_digest"] == EXPECTED_DIGEST
    assert len(completion["invariant_bindings"]) == 1
    binding = completion["invariant_bindings"][0]
    assert set(binding) == {
        "invariant_id",
        "invariant_digest",
        "verifier_id",
        "verifier_digest",
    }
    assert binding["invariant_id"] == "exact-order-and-multiplicity"
    assert binding["verifier_id"] == "sealed-exact-output"
    assert re.fullmatch(r"[0-9a-f]{64}", binding["invariant_digest"])
    assert re.fullmatch(r"[0-9a-f]{64}", binding["verifier_digest"])
    assert [attempt["verdict"] for attempt in payload["attempts"]] == [
        "REJECTED",
        "ACCEPTED",
    ]
    assert payload["attempts"][0]["assessment"][0]["result"] == "SATISFIED"
    assert payload["attempts"][0]["evidence"][0]["result"] == "FAIL"
    verifier_inputs = (tmp_path / "verifier-audit.jsonl").read_text().splitlines()
    assert verifier_inputs[:4] == [
        EXPECTED_BYTES.hex(),
        b"wrong\n".hex(),
        b"".hex(),
        b"\xff\x00".hex(),
    ]
