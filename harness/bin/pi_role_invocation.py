#!/usr/bin/env python3
"""Fresh, resource-disabled Pi subprocess invocation for one bounded role."""

from __future__ import annotations

import errno
import json
import math
import os
import pathlib
import re
import resource
import shutil
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from typing import BinaryIO, Mapping


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


@dataclass(frozen=True)
class RoleReceipt:
    role: str
    status: str
    output: str = ""
    candidate_generation: int | None = None
    reason: str = ""
    config_dir: str = ""
    command: tuple[str, ...] = ()
    stdout_bytes: int = 0
    stderr_bytes: int = 0


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


def _unresolved(role: str, generation: int | None, reason: str) -> RoleReceipt:
    return RoleReceipt(
        role=role,
        status="UNRESOLVED",
        candidate_generation=generation,
        reason=reason,
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
) -> RoleReceipt:
    """Parse Pi JSONL fail closed, requiring one assistant result then settlement."""
    if returncode != 0:
        return _unresolved(role, generation, f"pi_exit_{returncode}")
    if len(stdout.encode("utf-8")) > max_output_bytes:
        return _unresolved(role, generation, "pi_stdout_too_large")
    if len(stderr.encode("utf-8")) > max_output_bytes:
        return _unresolved(role, generation, "pi_stderr_too_large")
    try:
        events = [
            json.loads(line, object_pairs_hook=_reject_duplicate_keys)
            for line in stdout.splitlines()
            if line.strip()
        ]
    except (TypeError, ValueError):
        return _unresolved(role, generation, "pi_output_malformed")
    if any(_contains_tool_activity(event) for event in events):
        return _unresolved(role, generation, "pi_tool_activity_forbidden")
    if not all(_event_schema_valid(event) for event in events):
        return _unresolved(role, generation, "pi_protocol_invalid")
    if not events or events[-1] != {"type": "agent_settled"}:
        return _unresolved(role, generation, "pi_not_settled")
    assistant_messages = [
        event.get("message")
        for event in events
        if isinstance(event, dict)
        and event.get("type") == "message_end"
        and isinstance(event.get("message"), dict)
        and event["message"].get("role") == "assistant"
    ]
    if len(assistant_messages) != 1:
        return _unresolved(role, generation, "pi_result_ambiguous")
    message = assistant_messages[0]
    if message.get("stopReason") != "stop" or message.get("errorMessage"):
        return _unresolved(role, generation, "pi_model_not_stopped")
    assistant_result = _assistant_text(message)
    if assistant_result is None:
        return _unresolved(role, generation, "pi_result_malformed")
    if not assistant_result.strip():
        return _unresolved(role, generation, "pi_result_empty")
    return RoleReceipt(
        role=role,
        status="SETTLED",
        output=assistant_result,
        candidate_generation=generation,
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


def _stream_size(stream: BinaryIO) -> int:
    stream.flush()
    return os.fstat(stream.fileno()).st_size


def _set_output_file_limit(limit: int) -> None:
    resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit))


def _reap_process_leader(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    process.wait()


def _is_finished_group_race(exc: OSError) -> bool:
    return exc.errno in {errno.EPERM, errno.ESRCH}


def _stop_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except OSError as exc:
        if not _is_finished_group_race(exc):
            raise
        _reap_process_leader(process)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError as retry_exc:
            if not _is_finished_group_race(retry_exc):
                raise
        return
    _reap_process_leader(process)


def _run_bounded(
    command: list[str],
    *,
    cwd: os.PathLike[str] | str,
    env: Mapping[str, str],
    timeout: float,
    max_output_bytes: int,
    stdout_file: BinaryIO,
    stderr_file: BinaryIO,
) -> tuple[int, str, str, str, int, int]:
    """Run with file-backed streams and terminate as soon as either bound is crossed."""
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=stdout_file,
        stderr=stderr_file,
        start_new_session=True,
        preexec_fn=lambda: _set_output_file_limit(max_output_bytes + 1),
    )
    deadline = time.monotonic() + timeout
    reason = ""
    while process.poll() is None:
        if _stream_size(stdout_file) > max_output_bytes:
            reason = "pi_stdout_too_large"
            break
        if _stream_size(stderr_file) > max_output_bytes:
            reason = "pi_stderr_too_large"
            break
        if time.monotonic() >= deadline:
            reason = "pi_process_failure:TimeoutExpired"
            break
        time.sleep(0.01)
    if reason:
        _stop_process_group(process)
        stdout_size = _stream_size(stdout_file)
        stderr_size = _stream_size(stderr_file)
        return process.returncode, "", "", reason, stdout_size, stderr_size
    returncode = process.wait()
    _stop_process_group(process)
    stdout_size = _stream_size(stdout_file)
    stderr_size = _stream_size(stderr_file)
    if stdout_size > max_output_bytes:
        return returncode, "", "", "pi_stdout_too_large", stdout_size, stderr_size
    if stderr_size > max_output_bytes:
        return returncode, "", "", "pi_stderr_too_large", stdout_size, stderr_size
    stdout_file.seek(0)
    stderr_file.seek(0)
    try:
        stdout = stdout_file.read().decode("utf-8")
        stderr = stderr_file.read().decode("utf-8")
    except UnicodeDecodeError:
        return returncode, "", "", "pi_output_malformed", stdout_size, stderr_size
    return returncode, stdout, stderr, "", stdout_size, stderr_size


def invoke_pi_role(
    request: PiRoleRequest,
    *,
    pi_runtime: os.PathLike[str] | str,
    config_root: os.PathLike[str] | str,
    cwd: os.PathLike[str] | str,
    auth_env: Mapping[str, str] | None = None,
    max_output_bytes: int = 1_000_000,
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
    try:
        with tempfile.TemporaryFile(mode="w+b", dir=spool_dir) as stdout_file:
            with tempfile.TemporaryFile(mode="w+b", dir=spool_dir) as stderr_file:
                try:
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
                except OSError as exc:
                    failure = f"pi_process_failure:{type(exc).__name__}"
                    returncode, stdout, stderr = 1, "", ""
                    stdout_bytes = _stream_size(stdout_file)
                    stderr_bytes = _stream_size(stderr_file)
                if failure:
                    return RoleReceipt(
                        request.role,
                        "UNRESOLVED",
                        candidate_generation=request.candidate_generation,
                        reason=failure,
                        config_dir=str(config_dir),
                        command=tuple(command),
                        stdout_bytes=stdout_bytes,
                        stderr_bytes=stderr_bytes,
                    )
                parsed = parse_pi_result(
                    role=request.role,
                    generation=request.candidate_generation,
                    stdout=stdout,
                    stderr=stderr,
                    returncode=returncode,
                    max_output_bytes=max_output_bytes,
                )
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
                )
    finally:
        shutil.rmtree(config_dir, ignore_errors=True)
        shutil.rmtree(spool_dir, ignore_errors=True)
