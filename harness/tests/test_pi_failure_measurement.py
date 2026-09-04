"""Failure-path controls for Pi call accounting."""

from __future__ import annotations

import json
import stat
import sys
import threading
import time
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
BIN = REPO / "harness" / "bin"
sys.path.insert(0, str(BIN))

from pi_role_invocation import (  # noqa: E402
    PiRoleRequest,
    invoke_pi_role,
    parse_pi_result,
)
from bounded_subprocess import output_stream  # noqa: E402


def _assistant_event(text: str) -> dict[str, object]:
    return {
        "type": "message_end",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": text}],
            "provider": "anthropic",
            "model": "claude-haiku-4-5",
            "responseId": "response-before-failure",
            "usage": {
                "input": 13,
                "output": 5,
                "cacheRead": 2,
                "cacheWrite": 1,
                "totalTokens": 21,
                "cost": {"total": 0.003},
            },
            "stopReason": "stop",
        },
    }


def _jsonl(*events: object) -> str:
    return "\n".join(json.dumps(event) for event in events) + "\n"


def test_nonzero_exit_retains_finalized_call_from_complete_prefix() -> None:
    receipt = parse_pi_result(
        role="generator",
        generation=2,
        stdout=_jsonl(_assistant_event("partial answer"), {"truncated": True}),
        stderr="provider connection failed",
        returncode=7,
        requested_provider="anthropic",
        requested_model="claude-haiku-4-5",
        duration_ms=12.0,
    )

    assert receipt.status == "UNRESOLVED"
    assert receipt.reason == "pi_exit_7"
    assert receipt.model_calls[0].response_id == "response-before-failure"
    assert receipt.model_calls[0].total_tokens == 21


def test_timeout_after_finalized_call_retains_measurement(tmp_path: Path) -> None:
    runtime = tmp_path / "fake-pi"
    runtime.write_text(
        "#!/usr/bin/env python3\n"
        "import json, time\n"
        f"print(json.dumps({_assistant_event('partial answer')!r}), flush=True)\n"
        "time.sleep(5)\n",
        encoding="utf-8",
    )
    runtime.chmod(runtime.stat().st_mode | stat.S_IXUSR)
    evidence_prefix = tmp_path / "experiment-arm-generator-g2"
    receipt = invoke_pi_role(
        PiRoleRequest(
            role="generator",
            prompt="generate",
            provider="anthropic",
            model="claude-haiku-4-5",
            system_prompt="return JSON",
            timeout=1.0,
            candidate_generation=2,
        ),
        pi_runtime=runtime,
        config_root=tmp_path / "configs",
        cwd=tmp_path,
        evidence_prefix=evidence_prefix,
    )

    assert receipt.status == "UNRESOLVED"
    assert receipt.reason == "pi_process_failure:TimeoutExpired"
    assert receipt.output == "partial answer"
    assert receipt.model_calls[0].response_id == "response-before-failure"
    assert receipt.model_calls[0].total_tokens == 21
    assert Path(f"{evidence_prefix}.stdout").read_bytes().startswith(b'{"type"')
    assert Path(f"{evidence_prefix}.stderr").read_bytes() == b""


def test_persistent_spool_is_private_and_visible_before_process_finishes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "arm-run-generator-g1.stdout"

    with output_stream(path, temporary_dir=tmp_path) as stream:
        stream.write(b"finalized provider event\n")
        stream.flush()
        assert path.read_bytes() == b"finalized provider event\n"

    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_pi_invocation_exposes_finalized_event_before_process_finishes(
    tmp_path: Path,
) -> None:
    sentinel = tmp_path / "provider-event-written"
    runtime = tmp_path / "slow-pi"
    runtime.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, time\n"
        f"print(json.dumps({_assistant_event('captured before crash')!r}), flush=True)\n"
        f"pathlib.Path({str(sentinel)!r}).write_text('ready')\n"
        "time.sleep(5)\n",
        encoding="utf-8",
    )
    runtime.chmod(runtime.stat().st_mode | stat.S_IXUSR)
    prefix = tmp_path / "live-pi-arm-generator-g1"
    result = {}

    def invoke() -> None:
        result["receipt"] = invoke_pi_role(
            PiRoleRequest(role="generator", prompt="x", timeout=2.0),
            pi_runtime=runtime,
            config_root=tmp_path / "configs-live",
            cwd=tmp_path,
            evidence_prefix=prefix,
        )

    thread = threading.Thread(target=invoke)
    thread.start()
    deadline = time.monotonic() + 1.5
    while not sentinel.exists() and time.monotonic() < deadline:
        time.sleep(0.01)

    assert sentinel.exists()
    assert thread.is_alive()
    assert b"response-before-failure" in Path(f"{prefix}.stdout").read_bytes()
    thread.join(timeout=4)
    assert not thread.is_alive()
    assert result["receipt"].model_calls[0].total_tokens == 21
