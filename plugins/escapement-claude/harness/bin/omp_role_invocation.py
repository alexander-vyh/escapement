#!/usr/bin/env python3
"""Fresh, tool-less Oh My Pi SDK invocation for one bounded role."""

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

from bounded_subprocess import failure_audit, output_stream, stream_bytes
from model_call_receipts import RoleReceipt
from pi_omp_comparison import parse_omp_adapter_output
from pi_role_invocation import _run_bounded, _stream_size, restricted_child_env


_ROLE_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_PINNED_ADAPTER_DIGEST = (
    "262ef20bcdf6356c29fcb109af03d3b150fad2c674633c4d41c1986473d0757b"
)


def validate_omp_adapter_source(adapter: str | pathlib.Path) -> str:
    """Allow only the exact adapter bytes accepted by adversarial review."""
    digest = hashlib.sha256(pathlib.Path(adapter).read_bytes()).hexdigest()
    if digest != _PINNED_ADAPTER_DIGEST:
        raise ValueError("OMP adapter bytes do not match the reviewed program")
    return digest


def _snapshot_adapter(adapter: pathlib.Path, expected_digest: str) -> pathlib.Path:
    """Execute a private copy of the exact bytes that passed validation."""
    source = adapter.read_bytes()
    if hashlib.sha256(source).hexdigest() != expected_digest:
        raise ValueError("OMP adapter changed after validation")
    repo_root = next(
        (parent for parent in adapter.parents if (parent / "node_modules").is_dir()),
        None,
    )
    if repo_root is None:
        raise ValueError("OMP adapter has no pinned node_modules ancestor")
    snapshot_dir = repo_root / "node_modules" / ".escapement-runtime"
    snapshot_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    snapshot_dir.chmod(0o700)
    with tempfile.NamedTemporaryFile(
        mode="wb", prefix="omp-role-", suffix=".ts", dir=snapshot_dir, delete=False
    ) as stream:
        stream.write(source)
        stream.flush()
        os.fsync(stream.fileno())
        snapshot = pathlib.Path(stream.name)
    snapshot.chmod(0o400)
    if hashlib.sha256(snapshot.read_bytes()).hexdigest() != expected_digest:
        snapshot.unlink(missing_ok=True)
        raise ValueError("OMP adapter snapshot digest mismatch")
    return snapshot


@dataclass(frozen=True)
class OmpRoleRequest:
    role: str
    prompt: str
    provider: str
    model: str
    auth_token: str
    system_prompt: str = "Return only the requested result."
    timeout: float = 60.0
    candidate_generation: int | None = None


def invoke_omp_role(
    request: OmpRoleRequest,
    *,
    bun_runtime: str | pathlib.Path,
    adapter: str | pathlib.Path,
    config_root: str | pathlib.Path,
    max_output_bytes: int = 1_000_000,
    evidence_prefix: str | pathlib.Path | None = None,
) -> RoleReceipt:
    """Run one OMP SDK process with fresh empty config, cwd, and session state."""
    if not _ROLE_PATTERN.fullmatch(request.role):
        raise ValueError("role must be a conservative lowercase identifier")
    if not request.prompt or not request.system_prompt:
        raise ValueError("prompt and system_prompt must be non-empty")
    if not request.provider or not request.model or not request.auth_token:
        raise ValueError("provider, model, and auth_token must be non-empty")
    if not math.isfinite(request.timeout) or request.timeout <= 0:
        raise ValueError("timeout must be finite and positive")
    if max_output_bytes <= 0:
        raise ValueError("max_output_bytes must be positive")
    adapter_path = pathlib.Path(adapter).resolve()
    adapter_digest = validate_omp_adapter_source(adapter_path)
    adapter_snapshot = _snapshot_adapter(adapter_path, adapter_digest)

    root = pathlib.Path(config_root)
    root.mkdir(parents=True, exist_ok=True)
    role_root = pathlib.Path(tempfile.mkdtemp(prefix=f"omp-{request.role}-", dir=root))
    cwd = role_root / "cwd"
    agent_dir = role_root / "agent"
    spool_dir = role_root / "io"
    for directory in (cwd, agent_dir, spool_dir):
        directory.mkdir(mode=0o700)
    command = (str(bun_runtime), str(adapter_snapshot))
    request_bytes = json.dumps(
        {
            "protocol_version": 1,
            "role": request.role,
            "prompt": request.prompt,
            "system_prompt": request.system_prompt,
            "provider": request.provider,
            "model": request.model,
            "auth_token": request.auth_token,
            "cwd": str(cwd),
            "agent_dir": str(agent_dir),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    prefix = pathlib.Path(evidence_prefix) if evidence_prefix is not None else None
    try:
        with tempfile.TemporaryFile(mode="w+b", dir=spool_dir) as stdin_file:
            with output_stream(
                pathlib.Path(f"{prefix}.stdout") if prefix else None,
                temporary_dir=spool_dir,
            ) as stdout_file:
                with output_stream(
                    pathlib.Path(f"{prefix}.stderr") if prefix else None,
                    temporary_dir=spool_dir,
                ) as stderr_file:
                    stdin_file.write(request_bytes)
                    stdin_file.seek(0)
                    try:
                        started = time.monotonic()
                        result = _run_bounded(
                            list(command),
                            cwd=cwd,
                            env=restricted_child_env(),
                            timeout=request.timeout,
                            max_output_bytes=max_output_bytes,
                            stdin_file=stdin_file,
                            stdout_file=stdout_file,
                            stderr_file=stderr_file,
                        )
                        process_duration_ms = (time.monotonic() - started) * 1000
                        returncode, stdout, stderr, failure, out_bytes, err_bytes = (
                            result
                        )
                    except OSError as exc:
                        process_duration_ms = (time.monotonic() - started) * 1000
                        failure = f"omp_process_failure:{type(exc).__name__}"
                        returncode = 1
                        out_bytes = _stream_size(stdout_file)
                        err_bytes = _stream_size(stderr_file)
                    captured_stdout = stream_bytes(stdout_file)
                    captured_stderr = stream_bytes(stderr_file)
                    stdout = captured_stdout.decode("utf-8", errors="surrogateescape")
                    stderr = captured_stderr.decode("utf-8", errors="surrogateescape")
                    parsed = parse_omp_adapter_output(
                        role=request.role,
                        generation=request.candidate_generation,
                        requested_provider=request.provider,
                        requested_model=request.model,
                        stdout=stdout,
                        stderr=stderr,
                        # Parse complete JSONL records even when the process failed so
                        # finalized provider calls remain observable. Process status
                        # still wins below and can never become completion authority.
                        returncode=0 if failure or returncode != 0 else returncode,
                        process_duration_ms=process_duration_ms,
                    )
                    process_reason = (
                        failure.replace("pi_", "omp_", 1)
                        if failure
                        else f"omp_exit_{returncode}"
                        if returncode != 0
                        else ""
                    )
                    audit = failure_audit(captured_stdout, captured_stderr)
                    raw_events = parsed.raw_events
                    raw_events_digest = parsed.raw_events_digest
                    if process_reason or parsed.reason in {
                        "omp_protocol_invalid",
                        "omp_output_malformed",
                    }:
                        raw_events = audit
                        raw_events_digest = hashlib.sha256(
                            audit.encode("utf-8")
                        ).hexdigest()
                    return RoleReceipt(
                        role=parsed.role,
                        status="UNRESOLVED" if process_reason else parsed.status,
                        output=parsed.output,
                        candidate_generation=parsed.candidate_generation,
                        reason=process_reason or parsed.reason,
                        config_dir=str(role_root),
                        command=command,
                        stdout_bytes=out_bytes,
                        stderr_bytes=err_bytes,
                        model_calls=parsed.model_calls,
                        topology_status=(
                            "INELIGIBLE" if process_reason else parsed.topology_status
                        ),
                        runtime_version=parsed.runtime_version,
                        raw_events_digest=raw_events_digest,
                        raw_events=raw_events,
                    )
    finally:
        shutil.rmtree(role_root, ignore_errors=True)
        adapter_snapshot.unlink(missing_ok=True)
