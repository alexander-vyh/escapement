"""Adversarial tests for isolated, fail-closed Pi role invocation."""

from __future__ import annotations

import errno
import json
import pathlib
import sys
import time

import pytest


REPO = pathlib.Path(__file__).resolve().parents[2]
BIN = REPO / "harness" / "bin"
sys.path.insert(0, str(BIN))

import pi_role_invocation  # noqa: E402
from pi_role_invocation import (  # noqa: E402
    PiRoleRequest,
    invoke_pi_role,
    parse_pi_result,
    restricted_child_env,
)


def _jsonl(*events: object) -> str:
    return "\n".join(json.dumps(event) for event in events) + "\n"


def _assistant(text="answer", *, stop_reason="stop", content=None):
    return {
        "type": "message_end",
        "message": {
            "role": "assistant",
            "content": content
            if content is not None
            else [{"type": "text", "text": text}],
            "stopReason": stop_reason,
        },
    }


def _parse(stdout: str, *, returncode: int = 0) -> object:
    return parse_pi_result(
        role="assessor",
        generation=3,
        stdout=stdout,
        stderr="",
        returncode=returncode,
    )


def _write_executable(path: pathlib.Path, body: str) -> pathlib.Path:
    path.write_text("#!/usr/bin/env python3\n" + body, encoding="utf-8")
    path.chmod(0o700)
    return path


def _request(*, role: str = "assessor", timeout: float = 5) -> PiRoleRequest:
    return PiRoleRequest(
        role=role,
        prompt="Assess the candidate.",
        provider="anthropic",
        model="test-model",
        timeout=timeout,
        candidate_generation=2,
    )


def _invoke(tmp_path, runtime, *, request=None, **options):
    return invoke_pi_role(
        request or _request(),
        pi_runtime=runtime,
        config_root=tmp_path / "configs",
        cwd=tmp_path,
        **options,
    )


def _id(receipt):
    return receipt.status, receipt.reason, receipt.candidate_generation


def test_parser_accepts_one_complete_assistant_result() -> None:
    receipt = _parse(_jsonl(_assistant("accepted"), {"type": "agent_settled"}))

    assert receipt.status == "SETTLED"
    assert receipt.output == "accepted"
    assert receipt.candidate_generation == 3


@pytest.mark.parametrize("stop_reason", ["length", "toolUse", "error", "cancelled", ""])
def test_parser_rejects_every_non_stop_assistant_termination(stop_reason: str) -> None:
    receipt = _parse(
        _jsonl(
            _assistant("plausible output", stop_reason=stop_reason),
            {"type": "agent_settled"},
        )
    )

    assert _id(receipt) == ("UNRESOLVED", "pi_model_not_stopped", 3)


@pytest.mark.parametrize(
    "content",
    [
        [{"type": "text", "text": "answer"}, {"type": "reasoning", "text": "hidden"}],
        [{"type": "image", "data": "..."}],
        [{"type": "text", "text": 42}],
        ["answer"],
    ],
)
def test_parser_rejects_any_non_text_content_part(content: list[object]) -> None:
    receipt = _parse(_jsonl(_assistant(content=content), {"type": "agent_settled"}))

    assert _id(receipt) == ("UNRESOLVED", "pi_result_malformed", 3)


@pytest.mark.parametrize(
    "tool_event",
    [
        {"type": "tool_execution_start", "toolCallId": "call-1"},
        {"type": "tool_execution_end", "result": "done"},
        {
            "type": "message_end",
            "message": {
                "role": "toolResult",
                "content": [{"type": "text", "text": "hidden execution"}],
            },
        },
    ],
)
def test_parser_rejects_tool_activity(tool_event: dict[str, object]) -> None:
    receipt = _parse(
        _jsonl(tool_event, _assistant("apparently valid"), {"type": "agent_settled"})
    )

    assert _id(receipt) == ("UNRESOLVED", "pi_tool_activity_forbidden", 3)


@pytest.mark.parametrize(
    "stdout, reason",
    [
        (_jsonl(_assistant(""), {"type": "agent_settled"}), "pi_result_empty"),
        (
            _jsonl(_assistant("one"), _assistant("two"), {"type": "agent_settled"}),
            "pi_result_ambiguous",
        ),
        (_jsonl(_assistant("answer")), "pi_not_settled"),
        (_jsonl(_assistant("answer"), {"type": "other"}), "pi_protocol_invalid"),
        ("not-json\n", "pi_output_malformed"),
        (
            '{"type":"message_end","message":{"role":"assistant",'
            '"content":[],"stopReason":"length","stopReason":"stop"}}\n',
            "pi_output_malformed",
        ),
    ],
)
def test_parser_rejects_invalid_results(stdout: str, reason: str) -> None:
    receipt = _parse(stdout)

    assert _id(receipt) == ("UNRESOLVED", reason, 3)


def test_parser_early_rejections_preserve_generation() -> None:
    receipts = [
        parse_pi_result(
            role="assessor",
            generation=47,
            stdout=stdout,
            stderr=stderr,
            returncode=returncode,
            max_output_bytes=limit,
        )
        for stdout, stderr, returncode, limit in [
            ("", "", 7, 1_000_000),
            ("oversized", "", 0, 1),
            ("", "oversized", 0, 1),
        ]
    ]
    assert all(receipt.status == "UNRESOLVED" for receipt in receipts)
    assert all(receipt.candidate_generation == 47 for receipt in receipts)


@pytest.mark.parametrize(
    "bad_event",
    [
        {"type": "error", "message": "failed before result"},
        {"type": "fatal", "detail": "runtime corrupt"},
        {"type": "future_unknown_event"},
        {"type": "agent_start", "error": "hidden failure"},
    ],
)
def test_parser_rejects_error_and_unknown_events(bad_event: dict[str, object]) -> None:
    receipt = _parse(
        _jsonl(bad_event, _assistant("apparently valid"), {"type": "agent_settled"})
    )
    assert _id(receipt) == ("UNRESOLVED", "pi_protocol_invalid", 3)


@pytest.mark.parametrize("unknown_at", ["event", "message"])
def test_parser_rejects_unknown_message_end_fields(unknown_at: str) -> None:
    event = _assistant("apparently valid")
    target = event if unknown_at == "event" else event["message"]
    target["surprise"] = True  # type: ignore[index]
    receipt = _parse(_jsonl(event, {"type": "agent_settled"}))
    assert receipt.status == "UNRESOLVED"
    assert receipt.reason == "pi_protocol_invalid"


def test_parser_allows_known_pi_0842_event_types() -> None:
    known = "session agent_start turn_start message_start message_update turn_end agent_end".split()
    user = {"type": "message_end", "message": {"role": "user", "content": [{"type": "text", "text": "prompt"}], "timestamp": 1}}  # fmt: skip
    receipt = _parse(
        _jsonl(
            *({"type": item} for item in known),
            user,
            _assistant(),
            {"type": "agent_settled"},
        )
    )
    assert receipt.status == "SETTLED"


def test_restricted_environment_projects_only_base_and_auth(monkeypatch) -> None:
    for key in ("LC_ALL", "NODE_EXTRA_CA_CERTS", "SSL_CERT_FILE", "TMPDIR"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("PATH", "/safe/bin")
    monkeypatch.setenv("LANG", "C.UTF-8")
    monkeypatch.setenv("HOME", "/ambient/home")
    monkeypatch.setenv("HTTPS_PROXY", "https://secret@proxy")
    monkeypatch.setenv("ESCAPEMENT_SECRET_CANARY", "must-not-cross")

    env = restricted_child_env(
        {"ANTHROPIC_AUTH_TOKEN": "token", "OPENAI_API_KEY": "openai-token"}
    )

    assert env == {
        "ANTHROPIC_AUTH_TOKEN": "token",
        "LANG": "C.UTF-8",
        "OPENAI_API_KEY": "openai-token",
        "PATH": "/safe/bin",
    }


@pytest.mark.parametrize(
    "auth_env",
    [
        {"ESCAPEMENT_SECRET_CANARY": "secret"},
        {"HOME": "/escape"},
        {"ANTHROPIC_AUTH_TOKEN": 123},
    ],
)
def test_restricted_environment_rejects_bad_auth(auth_env: dict[str, object]) -> None:
    with pytest.raises((TypeError, ValueError)):
        restricted_child_env(auth_env)  # type: ignore[arg-type]


@pytest.mark.parametrize("role", ["../escaped", "a/b", ".", "", "UPPER", "white space"])
def test_invalid_role_creates_no_paths(tmp_path: pathlib.Path, role: str) -> None:
    config_root = tmp_path / "must-not-exist"

    with pytest.raises(ValueError, match="role"):
        invoke_pi_role(
            _request(role=role),
            pi_runtime=tmp_path / "unused",
            config_root=config_root,
            cwd=tmp_path,
        )

    assert not config_root.exists()


@pytest.mark.parametrize("timeout", [float("nan"), float("inf")])
def test_nonfinite_timeout_is_rejected(tmp_path: pathlib.Path, timeout: float) -> None:
    with pytest.raises(ValueError, match="timeout"):
        _invoke(tmp_path, tmp_path / "unused", request=_request(timeout=timeout))
    assert not (tmp_path / "configs").exists()


def test_fresh_config_and_scrubbed_env(tmp_path: pathlib.Path, monkeypatch) -> None:
    probe = _write_executable(
        tmp_path / "fake-pi",
        """
import json, os
from pathlib import Path

config_dir = Path(os.environ["PI_CODING_AGENT_DIR"])
record = {
    "pid": os.getpid(),
    "config_dir": str(config_dir),
    "initial_entries": sorted(item.name for item in config_dir.iterdir()),
    "env_keys": sorted(os.environ),
    "auth": os.environ.get("ANTHROPIC_AUTH_TOKEN"),
}
with (Path.cwd() / "probe.jsonl").open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(record) + "\\n")
(config_dir / "runtime-secret.json").write_text("ephemeral", encoding="utf-8")
print(json.dumps({"type": "message_end", "message": {
    "role": "assistant", "content": [{"type": "text", "text": "ok"}],
    "stopReason": "stop"
}}))
print(json.dumps({"type": "agent_settled"}))
""",
    )
    monkeypatch.setenv("ESCAPEMENT_SECRET_CANARY", "must-not-cross")
    config_root = tmp_path / "configs"

    receipts = [
        invoke_pi_role(
            _request(),
            pi_runtime=probe,
            config_root=config_root,
            cwd=tmp_path,
            auth_env={"ANTHROPIC_AUTH_TOKEN": "scoped-token"},
        )
        for _ in range(2)
    ]

    records = [
        json.loads(line) for line in (tmp_path / "probe.jsonl").read_text().splitlines()
    ]
    assert [receipt.status for receipt in receipts] == ["SETTLED", "SETTLED"]
    assert [receipt.candidate_generation for receipt in receipts] == [2, 2]
    assert len({record["pid"] for record in records}) == 2
    assert len({record["config_dir"] for record in records}) == 2
    assert all(record["initial_entries"] == [] for record in records)
    assert all(record["auth"] == "scoped-token" for record in records)
    assert all(
        "ESCAPEMENT_SECRET_CANARY" not in record["env_keys"] for record in records
    )
    assert all("HOME" not in record["env_keys"] for record in records)
    assert all("HTTPS_PROXY" not in record["env_keys"] for record in records)
    assert all(not pathlib.Path(receipt.config_dir).exists() for receipt in receipts)
    assert list(config_root.iterdir()) == []


@pytest.mark.parametrize(
    "stream, expected_reason",
    [("stdout", "pi_stdout_too_large"), ("stderr", "pi_stderr_too_large")],
)
def test_oversized_stream_fails_closed(tmp_path, stream, expected_reason) -> None:
    write = "sys.stdout.write" if stream == "stdout" else "sys.stderr.write"
    probe = _write_executable(
        tmp_path / f"large-{stream}",
        f"import sys\n{write}('x' * 257)\n",
    )

    receipt = _invoke(tmp_path, probe, max_output_bytes=256)

    assert _id(receipt) == ("UNRESOLVED", expected_reason, 2)
    assert list((tmp_path / "configs").iterdir()) == []


def test_repeated_overflow_tolerates_eperm(tmp_path, monkeypatch) -> None:
    probe = _write_executable(
        tmp_path / "unbounded-pi",
        """
import os
while True:
    os.write(1, b"o" * 4096)
    os.write(2, b"e" * 4096)
""",
    )

    real_killpg = pi_role_invocation.os.killpg
    calls = 0

    def one_eperm_then_real(pgid: int, sig: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise PermissionError(errno.EPERM, "simulated macOS cleanup race")
        real_killpg(pgid, sig)

    monkeypatch.setattr(pi_role_invocation.os, "killpg", one_eperm_then_real)
    request = _request(timeout=5)
    started = time.monotonic()
    receipts = [
        _invoke(tmp_path, probe, request=request, max_output_bytes=1024)
        for _ in range(6)
    ]

    assert all(receipt.status == "UNRESOLVED" for receipt in receipts)
    assert all("too_large" in receipt.reason for receipt in receipts)
    assert all(receipt.candidate_generation == 2 for receipt in receipts)
    assert time.monotonic() - started < request.timeout
    assert all(receipt.stdout_bytes <= 1025 for receipt in receipts)
    assert all(receipt.stderr_bytes <= 1025 for receipt in receipts)
    assert all(
        max(receipt.stdout_bytes, receipt.stderr_bytes) == 1025 for receipt in receipts
    )
    assert calls >= 7
    assert list((tmp_path / "configs").iterdir()) == []


@pytest.mark.parametrize("failure_mode", ["timeout", "overflow"])
def test_failures_kill_process_group(tmp_path, failure_mode) -> None:
    sentinel = tmp_path / f"survivor-{failure_mode}"
    parent_action = (
        "import time; time.sleep(5)"
        if failure_mode == "timeout"
        else "import os; [(os.write(1, b'x' * 4096), os.write(2, b'y' * 4096)) for _ in iter(int, 1)]"
    )
    probe = _write_executable(
        tmp_path / f"group-{failure_mode}",
        f"""
import subprocess, sys
subprocess.Popen([
    sys.executable,
    "-c",
    "import pathlib,time; time.sleep(0.3); pathlib.Path({str(sentinel)!r}).write_text('survived')",
])
{parent_action}
""",
    )

    receipt = _invoke(
        tmp_path,
        probe,
        request=_request(timeout=0.05 if failure_mode == "timeout" else 5),
        max_output_bytes=1024,
    )
    time.sleep(0.5)

    assert receipt.status == "UNRESOLVED"
    assert not sentinel.exists()
    assert list((tmp_path / "configs").iterdir()) == []


def test_success_kills_auth_inheriting_child(tmp_path: pathlib.Path) -> None:
    sentinel = tmp_path / "success-survivor"
    probe = _write_executable(
        tmp_path / "successful-parent",
        f"""
import json, os, subprocess, sys
subprocess.Popen([
    sys.executable,
    "-c",
    "import os,pathlib,time; time.sleep(0.3); pathlib.Path({str(sentinel)!r}).write_text(os.environ.get('ANTHROPIC_AUTH_TOKEN', 'missing'))",
])
print(json.dumps({{"type": "message_end", "message": {{
    "role": "assistant", "content": [{{"type": "text", "text": "ok"}}],
    "stopReason": "stop"
}}}}))
print(json.dumps({{"type": "agent_settled"}}))
""",
    )

    receipt = _invoke(
        tmp_path,
        probe,
        auth_env={"ANTHROPIC_AUTH_TOKEN": "must-die-with-process-group"},
    )
    time.sleep(0.5)

    assert receipt.status == "SETTLED"
    assert not sentinel.exists()
    assert list((tmp_path / "configs").iterdir()) == []


@pytest.mark.parametrize(
    "body, expected_reason",
    [
        ("print('not-json')\n", "pi_output_malformed"),
        ("raise SystemExit(7)\n", "pi_exit_7"),
    ],
)
def test_failure_cleanup(tmp_path, body, expected_reason) -> None:
    probe = _write_executable(tmp_path / "failing-pi", body)
    config_root = tmp_path / "configs"

    receipt = _invoke(tmp_path, probe)

    assert _id(receipt) == ("UNRESOLVED", expected_reason, 2)
    assert list(config_root.iterdir()) == []


def test_timeout_is_clean_and_closed(tmp_path: pathlib.Path) -> None:
    probe = _write_executable(
        tmp_path / "slow-pi",
        "import time\ntime.sleep(2)\n",
    )

    receipt = _invoke(tmp_path, probe, request=_request(timeout=0.05))

    assert _id(receipt) == ("UNRESOLVED", "pi_process_failure:TimeoutExpired", 2)
    assert list((tmp_path / "configs").iterdir()) == []


def test_process_error_is_clean_and_closed(tmp_path: pathlib.Path) -> None:
    receipt = _invoke(tmp_path, tmp_path / "does-not-exist")

    assert _id(receipt) == ("UNRESOLVED", "pi_process_failure:FileNotFoundError", 2)
    assert list((tmp_path / "configs").iterdir()) == []
