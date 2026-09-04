"""Process-boundary tests for one-shot OMP SDK roles."""

from __future__ import annotations

import base64
import hashlib
import json
import shutil
import stat
import sys
import threading
import time
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[2]
BIN = REPO / "harness" / "bin"
sys.path.insert(0, str(BIN))

import omp_role_invocation  # noqa: E402
from omp_role_invocation import OmpRoleRequest, invoke_omp_role  # noqa: E402


@pytest.fixture(autouse=True)
def _accept_test_adapter(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        omp_role_invocation,
        "validate_omp_adapter_source",
        lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest(),
    )

    def distinct_snapshot(path, _):
        snapshot = tmp_path / f"snapshot-{Path(path).name}"
        shutil.copyfile(path, snapshot)
        return snapshot

    monkeypatch.setattr(omp_role_invocation, "_snapshot_adapter", distinct_snapshot)


def _write_executable(path: Path, body: str) -> Path:
    path.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _fake_runtime(tmp_path: Path) -> tuple[Path, Path]:
    audit = tmp_path / "audit.json"
    runtime = _write_executable(
        tmp_path / "fake-bun",
        f"""import json
import os
import pathlib
import sys

request = json.load(sys.stdin)
pathlib.Path({str(audit)!r}).write_text(json.dumps({{
    "argv": sys.argv[1:],
    "request": {{key: value for key, value in request.items() if key != "auth_token"}},
    "auth_token_received": request.get("auth_token") == "private-token",
    "ambient_secret_present": "ESCAPEMENT_SECRET_CANARY" in os.environ,
}}, sort_keys=True))
usage = {{
    "input": 13,
    "output": 5,
    "cacheRead": 2,
    "cacheWrite": 1,
    "totalTokens": 21,
    "cost": {{"input": 0.001, "output": 0.002, "cacheRead": 0.0, "cacheWrite": 0.0, "total": 0.003}},
}}
events = [
    {{"elapsed_ms": 1.0, "event": {{"type": "message_start", "message": {{"role": "assistant"}}}}}},
    {{"elapsed_ms": 4.0, "event": {{"type": "message_end", "message": {{
        "role": "assistant",
        "content": [{{"type": "text", "text": "answer"}}],
        "provider": request["provider"],
        "model": request["model"],
        "responseId": "response-1",
        "usage": usage,
        "stopReason": "stop",
    }}}}}},
    {{"elapsed_ms": 5.0, "event": {{"type": "agent_end", "isTerminal": True}}}},
]
print(json.dumps({{"record_type": "header", "protocol_version": 2, "runtime_version": "18.1.4"}}))
for sequence, record in enumerate(events):
    print(json.dumps({{"record_type": "event", "sequence": sequence, **record}}))
print(json.dumps({{"record_type": "terminal", "sequence": len(events), "wall_time_ms": 5.0}}))
""",
    )
    return runtime, audit


def _request(**changes: object) -> OmpRoleRequest:
    values: dict[str, object] = {
        "role": "generator",
        "prompt": "produce the candidate",
        "provider": "anthropic",
        "model": "claude-haiku-4-5",
        "auth_token": "private-token",
        "system_prompt": "return exact JSON",
        "timeout": 5.0,
        "candidate_generation": 2,
    }
    values.update(changes)
    return OmpRoleRequest(**values)  # type: ignore[arg-type]


def test_invoke_uses_fresh_empty_dirs_and_only_lends_token_over_stdin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime, audit_path = _fake_runtime(tmp_path)
    monkeypatch.setenv("ESCAPEMENT_SECRET_CANARY", "must-not-cross")
    adapter = tmp_path / "adapter.ts"
    adapter.write_text("// fake adapter marker", encoding="utf-8")

    evidence_prefix = tmp_path / "experiment-arm-generator-g2"
    receipt = invoke_omp_role(
        _request(),
        bun_runtime=runtime,
        adapter=adapter,
        config_root=tmp_path / "configs",
        evidence_prefix=evidence_prefix,
    )

    assert receipt.status == "SETTLED"
    assert receipt.output == "answer"
    assert receipt.candidate_generation == 2
    assert receipt.model_calls[0].total_tokens == 21
    assert receipt.model_calls[0].cost_usd == 0.003
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert audit["argv"] != [str(adapter)]
    assert audit["argv"][0].endswith("snapshot-adapter.ts")
    assert audit["auth_token_received"] is True
    assert audit["ambient_secret_present"] is False
    assert audit["request"]["cwd"] != str(REPO)
    assert not Path(audit["request"]["cwd"]).exists()
    assert not Path(audit["request"]["agent_dir"]).exists()
    assert receipt.command[0] == str(runtime)
    assert receipt.command[1] != str(adapter)
    assert "private-token" not in " ".join(receipt.command)
    assert "private-token" not in receipt.raw_events
    assert (
        Path(f"{evidence_prefix}.stdout")
        .read_text(encoding="utf-8")
        .startswith('{"record_type": "header"')
    )
    assert Path(f"{evidence_prefix}.stderr").read_bytes() == b""


@pytest.mark.parametrize("role", ["", "UPPER", "bad role", "../escape"])
def test_invalid_role_never_starts_runtime(tmp_path: Path, role: str) -> None:
    runtime, audit = _fake_runtime(tmp_path)

    with pytest.raises(ValueError):
        invoke_omp_role(
            _request(role=role),
            bun_runtime=runtime,
            adapter=tmp_path / "adapter.ts",
            config_root=tmp_path / "configs",
        )

    assert not audit.exists()


def test_empty_token_is_rejected_before_runtime(tmp_path: Path) -> None:
    runtime, audit = _fake_runtime(tmp_path)

    with pytest.raises(ValueError):
        invoke_omp_role(
            _request(auth_token=""),
            bun_runtime=runtime,
            adapter=tmp_path / "adapter.ts",
            config_root=tmp_path / "configs",
        )

    assert not audit.exists()


@pytest.mark.parametrize(
    ("ending", "timeout", "expected_reason"),
    [
        (
            "import time; time.sleep(5)",
            1.0,
            "omp_process_failure:TimeoutExpired",
        ),
        ("raise SystemExit(7)", 2.0, "omp_exit_7"),
    ],
)
def test_finalized_call_survives_abnormal_process_end(
    tmp_path: Path, ending: str, timeout: float, expected_reason: str
) -> None:
    runtime = _write_executable(
        tmp_path / "fake-bun",
        f"""import json
import sys

request = json.load(sys.stdin)
usage = {{
    "input": 13,
    "output": 5,
    "cacheRead": 2,
    "cacheWrite": 1,
    "totalTokens": 21,
    "cost": {{"input": 0.001, "output": 0.002, "cacheRead": 0.0, "cacheWrite": 0.0, "total": 0.003}},
}}
records = [
    {{"record_type": "header", "protocol_version": 2, "runtime_version": "18.1.4"}},
    {{"record_type": "event", "sequence": 0, "elapsed_ms": 1.0, "event": {{"type": "message_start", "message": {{"role": "assistant"}}}}}},
    {{"record_type": "event", "sequence": 1, "elapsed_ms": 4.0, "event": {{"type": "message_end", "message": {{
        "role": "assistant",
        "content": [{{"type": "text", "text": "partial answer"}}],
        "provider": request["provider"],
        "model": request["model"],
        "responseId": "response-partial",
        "usage": usage,
        "stopReason": "stop",
    }}}}}},
]
for record in records:
    print(json.dumps(record), flush=True)
print("diagnostic before failure", file=sys.stderr, flush=True)
{ending}
""",
    )
    adapter = tmp_path / "adapter.ts"
    adapter.write_text("// fake adapter marker", encoding="utf-8")

    receipt = invoke_omp_role(
        _request(timeout=timeout),
        bun_runtime=runtime,
        adapter=adapter,
        config_root=tmp_path / "configs",
    )

    assert receipt.status == "UNRESOLVED"
    assert receipt.reason == expected_reason
    assert receipt.topology_status == "INELIGIBLE"
    assert receipt.output == "partial answer"
    assert len(receipt.model_calls) == 1
    assert receipt.model_calls[0].total_tokens == 21
    assert receipt.model_calls[0].response_id == "response-partial"
    assert receipt.stderr_bytes == len("diagnostic before failure\n".encode())
    audit = json.loads(receipt.raw_events)
    assert audit["format"] == "escapement.subprocess-audit.v1"
    assert b'"record_type": "event"' in base64.b64decode(audit["stdout_base64"])
    assert base64.b64decode(audit["stderr_base64"]) == b"diagnostic before failure\n"


def test_complete_terminal_transcript_never_promotes_a_timed_out_process(
    tmp_path: Path,
) -> None:
    runtime = _write_executable(
        tmp_path / "fake-bun",
        """import json
import sys
import time

request = json.load(sys.stdin)
usage = {
    "input": 13,
    "output": 5,
    "cacheRead": 2,
    "cacheWrite": 1,
    "totalTokens": 21,
    "cost": {"total": 0.003},
}
records = [
    {"record_type": "header", "protocol_version": 2, "runtime_version": "18.1.4"},
    {"record_type": "event", "sequence": 0, "elapsed_ms": 4.0, "event": {
        "type": "message_end",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "terminal answer"}],
            "provider": request["provider"],
            "model": request["model"],
            "responseId": "terminal-before-timeout",
            "usage": usage,
            "stopReason": "stop",
        },
    }},
    {"record_type": "event", "sequence": 1, "elapsed_ms": 5.0, "event": {
        "type": "agent_end", "isTerminal": True,
    }},
    {"record_type": "terminal", "sequence": 2, "wall_time_ms": 6.0},
]
for record in records:
    print(json.dumps(record), flush=True)
time.sleep(5)
""",
    )
    adapter = tmp_path / "adapter.ts"
    adapter.write_text("// fake adapter marker", encoding="utf-8")

    receipt = invoke_omp_role(
        _request(timeout=0.5),
        bun_runtime=runtime,
        adapter=adapter,
        config_root=tmp_path / "configs",
    )

    assert receipt.status == "UNRESOLVED"
    assert receipt.reason == "omp_process_failure:TimeoutExpired"
    assert receipt.topology_status == "INELIGIBLE"
    assert receipt.output == "terminal answer"
    assert len(receipt.model_calls) == 1
    assert receipt.model_calls[0].total_tokens == 21
    assert receipt.model_calls[0].response_id == "terminal-before-timeout"


def test_omp_invocation_exposes_finalized_event_before_process_finishes(
    tmp_path: Path,
) -> None:
    sentinel = tmp_path / "provider-event-written"
    runtime = _write_executable(
        tmp_path / "slow-bun",
        f"""import json, pathlib, sys, time
request = json.load(sys.stdin)
print(json.dumps({{"record_type":"header","protocol_version":2,"runtime_version":"18.1.4"}}), flush=True)
message = {{"role":"assistant","content":[{{"type":"text","text":"captured"}}],"provider":request["provider"],"model":request["model"],"responseId":"live-omp-response","usage":{{"input":1,"output":1,"cacheRead":0,"cacheWrite":0,"totalTokens":2,"cost":{{"total":0.001}}}},"stopReason":"stop"}}
print(json.dumps({{"record_type":"event","sequence":0,"elapsed_ms":1.0,"event":{{"type":"message_end","message":message}}}}), flush=True)
pathlib.Path({str(sentinel)!r}).write_text("ready")
time.sleep(5)
""",
    )
    adapter = tmp_path / "adapter.ts"
    adapter.write_text("// marker", encoding="utf-8")
    prefix = tmp_path / "live-omp-arm-generator-g1"
    result = {}

    def invoke() -> None:
        result["receipt"] = invoke_omp_role(
            _request(timeout=2.0),
            bun_runtime=runtime,
            adapter=adapter,
            config_root=tmp_path / "configs-live",
            evidence_prefix=prefix,
        )

    thread = threading.Thread(target=invoke)
    thread.start()
    deadline = time.monotonic() + 1.5
    while not sentinel.exists() and time.monotonic() < deadline:
        time.sleep(0.01)

    assert sentinel.exists()
    assert thread.is_alive()
    assert b"live-omp-response" in Path(f"{prefix}.stdout").read_bytes()
    thread.join(timeout=4)
    assert not thread.is_alive()
    assert result["receipt"].model_calls[0].total_tokens == 2
