#!/usr/bin/env python3
"""File-backed, bounded subprocess execution with auditable failure streams."""

from __future__ import annotations

import base64
import errno
import json
import os
import resource
import signal
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Mapping


def stream_size(stream: BinaryIO) -> int:
    stream.flush()
    return os.fstat(stream.fileno()).st_size


def stream_bytes(stream: BinaryIO) -> bytes:
    stream.flush()
    stream.seek(0)
    captured = stream.read()
    stream.seek(0, os.SEEK_END)
    return captured


def failure_audit(stdout: bytes, stderr: bytes) -> str:
    """Encode exact subprocess streams in a stable, binary-safe envelope."""
    return json.dumps(
        {
            "format": "escapement.subprocess-audit.v1",
            "stderr_base64": base64.b64encode(stderr).decode("ascii"),
            "stdout_base64": base64.b64encode(stdout).decode("ascii"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


@contextmanager
def output_stream(path: Path | None, *, temporary_dir: Path):
    """Open a private persistent spool, or a temporary one outside experiments."""
    if path is None:
        with tempfile.TemporaryFile(mode="w+b", dir=temporary_dir) as stream:
            yield stream
        return
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    with os.fdopen(descriptor, "w+b") as stream:
        yield stream


def _set_output_file_limit(limit: int) -> None:
    resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit))


def _reap_process_leader(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    process.wait()


def stop_process_group(process: subprocess.Popen[bytes]) -> None:
    """Kill and reap a process group; EPERM is never disappearance evidence."""
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            _reap_process_leader(process)
            return
        if exc.errno != errno.EPERM:
            raise
        _reap_process_leader(process)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError as retry_exc:
            if retry_exc.errno == errno.ESRCH:
                return
            raise
        return
    _reap_process_leader(process)


def run_bounded(
    command: list[str],
    *,
    cwd: os.PathLike[str] | str,
    env: Mapping[str, str],
    timeout: float,
    max_output_bytes: int,
    stdout_file: BinaryIO,
    stderr_file: BinaryIO,
    stdin_file: BinaryIO | None = None,
) -> tuple[int, str, str, str, int, int]:
    """Run with bounded file streams and retain captured bytes on every exit."""
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdin=stdin_file,
        stdout=stdout_file,
        stderr=stderr_file,
        start_new_session=True,
        preexec_fn=lambda: _set_output_file_limit(max_output_bytes + 1),
    )
    deadline = time.monotonic() + timeout
    reason = ""
    while process.poll() is None:
        if stream_size(stdout_file) > max_output_bytes:
            reason = "pi_stdout_too_large"
            break
        if stream_size(stderr_file) > max_output_bytes:
            reason = "pi_stderr_too_large"
            break
        if time.monotonic() >= deadline:
            reason = "pi_process_failure:TimeoutExpired"
            break
        time.sleep(0.01)
    if reason:
        stop_process_group(process)
    else:
        process.wait()
        stop_process_group(process)

    stdout_bytes = stream_bytes(stdout_file)
    stderr_bytes = stream_bytes(stderr_file)
    stdout_size = len(stdout_bytes)
    stderr_size = len(stderr_bytes)
    if not reason and stdout_size > max_output_bytes:
        reason = "pi_stdout_too_large"
    if not reason and stderr_size > max_output_bytes:
        reason = "pi_stderr_too_large"

    stdout = stdout_bytes.decode("utf-8", errors="surrogateescape")
    stderr = stderr_bytes.decode("utf-8", errors="surrogateescape")
    if not reason and process.returncode == 0:
        try:
            stdout_bytes.decode("utf-8")
            stderr_bytes.decode("utf-8")
        except UnicodeDecodeError:
            reason = "pi_output_malformed"
    return process.returncode, stdout, stderr, reason, stdout_size, stderr_size
