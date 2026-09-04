#!/usr/bin/env python3
"""Fresh, resource-disabled Pi subprocess invocation for one bounded role."""

from __future__ import annotations

import hashlib
import json
import math
import os
import pathlib
import re
import shutil
import tempfile
import time
from dataclasses import dataclass
from typing import Mapping

from bounded_subprocess import (
    failure_audit as _failure_audit,
    output_stream,
    run_bounded as _run_bounded,
    stop_process_group,
    stream_bytes as _stream_bytes,
    stream_size as _stream_size,
)
from model_call_receipts import RoleReceipt, call_from_assistant_message


_ROLE_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_BASE_ENV_KEYS = (
    "LANG",
    "LC_ALL",
    "NODE_EXTRA_CA_CERTS",
    "PATH",
    "SSL_CERT_FILE",
    "TMPDIR",
)
_AUTH_ENV_KEYS = frozenset(
    {
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "AZURE_OPENAI_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GROQ_API_KEY",
        "MISTRAL_API_KEY",
        "OPENAI_API_KEY",
        "OPENAI_ORG_ID",
        "OPENAI_PROJECT_ID",
        "XAI_API_KEY",
    }
)
_EVENT_KEYS = {
    "session": {"type", "version", "id", "timestamp", "cwd", "parentSession"},
    "agent_start": {"type"},
    "turn_start": {"type", "turnIndex", "timestamp"},
    "message_start": {"type", "message"},
    "message_update": {"type", "usage", "assistantMessageEvent"},
    "message_end": {"type", "message"},
    "turn_end": {"type", "turnIndex", "message", "toolResults"},
    "agent_end": {"type", "messages", "willRetry"},
    "agent_settled": {"type"},
}
_ASSISTANT_MESSAGE_KEYS = {
    "role",
    "content",
    "api",
    "provider",
    "model",
    "responseModel",
    "responseId",
    "diagnostics",
    "usage",
    "stopReason",
    "deferred",
    "errorMessage",
    "rawStopReason",
    "endTurn",
    "timestamp",
}
_USER_MESSAGE_KEYS = {"role", "content", "timestamp"}


def _stop_process_group(process) -> None:
    """Compatibility seam retained for process-boundary mutation tests."""
    stop_process_group(process)


@dataclass(frozen=True)
class PiRoleRequest:
    role: str
    prompt: str
    provider: str | None = None
    model: str | None = None
    system_prompt: str = "Return only the requested result."
    thinking: str = "off"
    timeout: float = 60.0
    candidate_generation: int | None = None


def _unresolved(
    role: str,
    generation: int | None,
    reason: str,
    *,
    model_calls=(),
    output: str = "",
) -> RoleReceipt:
    return RoleReceipt(
        role=role,
        status="UNRESOLVED",
        candidate_generation=generation,
        reason=reason,
        output=output,
        model_calls=tuple(model_calls),
        topology_status="INELIGIBLE",
    )


def _assistant_text(message: object) -> str | None:
    if not isinstance(message, dict) or message.get("role") != "assistant":
        return None
    content = message.get("content")
    if not isinstance(content, list):
        return None
    pieces: list[str] = []
    for part in content:
        if not isinstance(part, dict) or part.get("type") != "text":
            return None
        value = part.get("text")
        if not isinstance(value, str):
            return None
        pieces.append(value)
    return "".join(pieces)


def _contains_tool_activity(value: object) -> bool:
    if isinstance(value, list):
        return any(_contains_tool_activity(item) for item in value)
    if not isinstance(value, dict):
        return False
    event_type = value.get("type")
    role = value.get("role")
    if isinstance(event_type, str) and event_type.lower().replace("_", "").startswith(
        "tool"
    ):
        return True
    if isinstance(role, str) and role.lower().replace("_", "").startswith("tool"):
        return True
    return any(_contains_tool_activity(item) for item in value.values())


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _event_schema_valid(event: object) -> bool:
    if not isinstance(event, dict) or not isinstance(event.get("type"), str):
        return False
    allowed_keys = _EVENT_KEYS.get(event["type"])
    if allowed_keys is None or not set(event).issubset(allowed_keys):
        return False
    if event["type"] != "message_end":
        return True
    message = event.get("message")
    if not isinstance(message, dict):
        return False
    if message.get("role") == "user":
        return set(message) == _USER_MESSAGE_KEYS
    return message.get("role") == "assistant" and set(message).issubset(
        _ASSISTANT_MESSAGE_KEYS
    )


def parse_pi_result(
    *,
    role: str,
    generation: int | None,
    stdout: str,
    stderr: str,
    returncode: int,
    max_output_bytes: int = 1_000_000,
    requested_provider: str | None = None,
    requested_model: str | None = None,
    duration_ms: float | None = None,
) -> RoleReceipt:
    """Parse Pi JSONL fail closed, requiring one assistant result then settlement."""
    events: list[object] = []
    malformed = False
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            events.append(json.loads(line, object_pairs_hook=_reject_duplicate_keys))
        except (TypeError, ValueError):
            malformed = True
            break
    assistant_messages = [
        event.get("message")
        for event in events
        if isinstance(event, dict)
        and event.get("type") == "message_end"
        and isinstance(event.get("message"), dict)
        and event["message"].get("role") == "assistant"
        and _event_schema_valid(event)
    ]
    calls = tuple(
        call_from_assistant_message(
            message,
            runtime="pi",
            role=role,
            generation=generation,
            requested_provider=requested_provider,
            requested_model=requested_model,
            duration_ms=duration_ms if len(assistant_messages) == 1 else None,
        )
        for message in assistant_messages
    )
    assistant_result = (
        _assistant_text(assistant_messages[0]) if len(assistant_messages) == 1 else None
    )
    observed_output = assistant_result or ""
    if returncode != 0:
        return _unresolved(
            role,
            generation,
            f"pi_exit_{returncode}",
            model_calls=calls,
            output=observed_output,
        )
    if len(stdout.encode("utf-8", errors="surrogateescape")) > max_output_bytes:
        return _unresolved(
            role,
            generation,
            "pi_stdout_too_large",
            model_calls=calls,
            output=observed_output,
        )
    if len(stderr.encode("utf-8", errors="surrogateescape")) > max_output_bytes:
        return _unresolved(
            role,
            generation,
            "pi_stderr_too_large",
            model_calls=calls,
            output=observed_output,
        )
    if malformed:
        return _unresolved(
            role,
            generation,
            "pi_output_malformed",
            model_calls=calls,
            output=observed_output,
        )
    if any(_contains_tool_activity(event) for event in events):
        return _unresolved(
            role,
            generation,
            "pi_tool_activity_forbidden",
            model_calls=calls,
            output=observed_output,
        )
    if not all(_event_schema_valid(event) for event in events):
        return _unresolved(
            role,
            generation,
            "pi_protocol_invalid",
            model_calls=calls,
            output=observed_output,
        )
    if not events or events[-1] != {"type": "agent_settled"}:
        return _unresolved(
            role,
            generation,
            "pi_not_settled",
            model_calls=calls,
            output=observed_output,
        )
    if len(assistant_messages) != 1:
        return _unresolved(role, generation, "pi_result_ambiguous", model_calls=calls)
    message = assistant_messages[0]
    if message.get("stopReason") != "stop" or message.get("errorMessage"):
        return _unresolved(role, generation, "pi_model_not_stopped", model_calls=calls)
    if assistant_result is None:
        return _unresolved(role, generation, "pi_result_malformed", model_calls=calls)
    if not assistant_result.strip():
        return _unresolved(role, generation, "pi_result_empty", model_calls=calls)
    return RoleReceipt(
        role=role,
        status="SETTLED",
        output=assistant_result,
        candidate_generation=generation,
        model_calls=calls,
        topology_status="ELIGIBLE",
        raw_events_digest=hashlib.sha256(stdout.encode("utf-8")).hexdigest(),
        raw_events=stdout,
    )


def restricted_child_env(auth_env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Project only process basics plus explicitly named provider credentials."""
    env = {key: os.environ[key] for key in _BASE_ENV_KEYS if key in os.environ}
    if auth_env:
        if any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in auth_env.items()
        ):
            raise TypeError("auth_env keys and values must be strings")
        unknown = set(auth_env).difference(_AUTH_ENV_KEYS)
        if unknown:
            raise ValueError(f"unsupported auth_env keys: {', '.join(sorted(unknown))}")
        env.update(auth_env)
    return env


def _command(request: PiRoleRequest, pi_runtime: os.PathLike[str] | str) -> list[str]:
    command = [
        str(pi_runtime),
        "--mode",
        "json",
        "--print",
        "--no-session",
        "--no-tools",
        "--no-extensions",
        "--no-skills",
        "--no-prompt-templates",
        "--no-themes",
        "--no-context-files",
        "--no-approve",
        "--thinking",
        request.thinking,
        "--system-prompt",
        request.system_prompt,
    ]
    if request.provider:
        command.extend(("--provider", request.provider))
    if request.model:
        command.extend(("--model", request.model))
    command.append(request.prompt)
    return command


def invoke_pi_role(
    request: PiRoleRequest,
    *,
    pi_runtime: os.PathLike[str] | str,
    config_root: os.PathLike[str] | str,
    cwd: os.PathLike[str] | str,
    auth_env: Mapping[str, str] | None = None,
    max_output_bytes: int = 1_000_000,
    evidence_prefix: os.PathLike[str] | str | None = None,
) -> RoleReceipt:
    """Invoke one fresh, tool-less Pi process with ambient resources disabled."""
    if not _ROLE_PATTERN.fullmatch(request.role):
        raise ValueError("role must be a conservative lowercase identifier")
    if not math.isfinite(request.timeout) or request.timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    if max_output_bytes <= 0:
        raise ValueError("max_output_bytes must be positive")
    env = restricted_child_env(auth_env)
    root = pathlib.Path(config_root)
    root.mkdir(parents=True, exist_ok=True)
    config_dir = pathlib.Path(tempfile.mkdtemp(prefix=f"{request.role}-", dir=root))
    spool_dir = pathlib.Path(tempfile.mkdtemp(prefix="io-", dir=root))
    config_dir.chmod(0o700)
    spool_dir.chmod(0o700)
    command = _command(request, pi_runtime)
    env.update({"PI_CODING_AGENT_DIR": str(config_dir), "PI_OFFLINE": "1"})
    prefix = pathlib.Path(evidence_prefix) if evidence_prefix is not None else None
    try:
        with output_stream(
            pathlib.Path(f"{prefix}.stdout") if prefix else None,
            temporary_dir=spool_dir,
        ) as stdout_file:
            with output_stream(
                pathlib.Path(f"{prefix}.stderr") if prefix else None,
                temporary_dir=spool_dir,
            ) as stderr_file:
                try:
                    started = time.monotonic()
                    returncode, stdout, stderr, failure, stdout_bytes, stderr_bytes = (
                        _run_bounded(
                            command,
                            cwd=cwd,
                            env=env,
                            timeout=request.timeout,
                            max_output_bytes=max_output_bytes,
                            stdout_file=stdout_file,
                            stderr_file=stderr_file,
                        )
                    )
                    duration_ms = (time.monotonic() - started) * 1000
                except OSError as exc:
                    duration_ms = (time.monotonic() - started) * 1000
                    failure = f"pi_process_failure:{type(exc).__name__}"
                    returncode = 1
                    stdout_bytes = _stream_size(stdout_file)
                    stderr_bytes = _stream_size(stderr_file)
                captured_stdout = _stream_bytes(stdout_file)
                captured_stderr = _stream_bytes(stderr_file)
                failure_audit = _failure_audit(captured_stdout, captured_stderr)
                stdout = captured_stdout.decode("utf-8", errors="surrogateescape")
                stderr = captured_stderr.decode("utf-8", errors="surrogateescape")
                parsed = parse_pi_result(
                    role=request.role,
                    generation=request.candidate_generation,
                    stdout=stdout,
                    stderr=stderr,
                    returncode=0 if failure else returncode,
                    max_output_bytes=max_output_bytes,
                    requested_provider=request.provider,
                    requested_model=request.model,
                    duration_ms=duration_ms,
                )
                if failure:
                    parsed = RoleReceipt(
                        role=parsed.role,
                        status="UNRESOLVED",
                        output=parsed.output,
                        candidate_generation=parsed.candidate_generation,
                        reason=failure,
                        model_calls=parsed.model_calls,
                        topology_status="INELIGIBLE",
                    )
                raw_events = parsed.raw_events
                raw_events_digest = parsed.raw_events_digest
                if parsed.status != "SETTLED":
                    raw_events = failure_audit
                    raw_events_digest = hashlib.sha256(
                        failure_audit.encode("utf-8")
                    ).hexdigest()
                return RoleReceipt(
                    role=parsed.role,
                    status=parsed.status,
                    output=parsed.output,
                    candidate_generation=parsed.candidate_generation,
                    reason=parsed.reason,
                    config_dir=str(config_dir),
                    command=tuple(command),
                    stdout_bytes=stdout_bytes,
                    stderr_bytes=stderr_bytes,
                    model_calls=parsed.model_calls,
                    topology_status=parsed.topology_status,
                    runtime_version=parsed.runtime_version,
                    raw_events_digest=raw_events_digest,
                    raw_events=raw_events,
                )
    finally:
        shutil.rmtree(config_dir, ignore_errors=True)
        shutil.rmtree(spool_dir, ignore_errors=True)
