"""Frozen verifier-owned artifacts and execution; contains no completion policy.

The manifest closes over declared verifier-owned artifacts only. The operating
system loader, a script's shebang interpreter, and its standard runtime remain
outside the snapshot as trusted host runtime. Verifier-owned imports and data
must therefore be declared as dependencies; missing ones fail closed.
"""

from __future__ import annotations

import errno
import hashlib
import json
import math
import os
import resource
import secrets
import signal
import stat
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

MAX_OUTPUT_BYTES = 1_000_000


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_json(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return digest_bytes(encoded)


def _read_regular(path: Path) -> bytes:
    if path.is_symlink():
        raise ValueError(f"verifier artifact cannot be a symlink: {path}")
    try:
        info = path.stat()
        content = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"cannot read verifier artifact: {path}") from exc
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"verifier artifact must be a regular file: {path}")
    return content


@dataclass(frozen=True)
class VerifierBinding:
    """Frozen verifier-owned artifacts; host runtime is outside this boundary.

    A shebang interpreter and standard runtime are trusted host runtime. Any
    verifier-owned helper, import, or data file must be declared explicitly.
    """

    verifier_id: str
    executable: str
    executable_digest: str
    artifact_digests: tuple[tuple[str, str], ...]
    digest: str
    timeout: float = 10.0

    @classmethod
    def freeze(
        cls,
        *,
        verifier_id: str,
        executable: str | Path,
        dependencies: Iterable[str | Path] = (),
        timeout: float = 10.0,
    ) -> VerifierBinding:
        identifier = verifier_id.strip()
        paths = (Path(executable), *(Path(item) for item in dependencies))
        if not identifier or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("verifier requires an id and finite positive timeout")
        if any(not item.is_absolute() for item in paths):
            raise ValueError(
                "verifier requires an id, positive timeout, and absolute artifacts"
            )
        if len({item.name for item in paths}) != len(paths):
            raise ValueError("verifier artifact basenames must be unique")
        manifest = tuple(
            (str(path), digest_bytes(_read_regular(path))) for path in paths
        )
        digest = digest_json({"verifier_id": identifier, "artifacts": manifest})
        return cls(identifier, str(paths[0]), manifest[0][1], manifest, digest, timeout)


@dataclass(frozen=True)
class FrozenArtifact:
    name: str
    digest: str
    content: bytes = field(repr=False)
    executable: bool = False


@dataclass(frozen=True)
class VerifierSnapshot:
    binding_digest: str
    verifier_id: str
    executable_name: str
    timeout: float
    artifacts: tuple[FrozenArtifact, ...]


def snapshot_binding(binding: VerifierBinding) -> VerifierSnapshot:
    artifacts: list[FrozenArtifact] = []
    for index, (raw_path, expected_digest) in enumerate(binding.artifact_digests):
        path = Path(raw_path)
        content = _read_regular(path)
        if digest_bytes(content) != expected_digest:
            raise ValueError(f"verifier artifact changed before snapshot: {path}")
        artifacts.append(
            FrozenArtifact(path.name, expected_digest, content, index == 0)
        )
    return VerifierSnapshot(
        binding.digest,
        binding.verifier_id,
        Path(binding.executable).name,
        binding.timeout,
        tuple(artifacts),
    )


def _child_env() -> dict[str, str]:
    allowed = (
        "PATH",
        "LANG",
        "LC_ALL",
        "TMPDIR",
        "SSL_CERT_FILE",
        "NODE_EXTRA_CA_CERTS",
    )
    return {key: os.environ[key] for key in allowed if key in os.environ}


def _set_output_file_limit() -> None:
    resource.setrlimit(
        resource.RLIMIT_FSIZE, (MAX_OUTPUT_BYTES + 1, MAX_OUTPUT_BYTES + 1)
    )


def invoke_snapshot(
    *,
    run_id: str,
    frozen_spec_digest: str,
    snapshot: VerifierSnapshot,
    invariants: Sequence[dict[str, str]],
    candidate_bytes: bytes,
    generation: int,
) -> tuple[dict[str, str], ...] | None:
    """Execute a snapshot with one schema for both controls and live candidates."""
    request_id = secrets.token_hex(32)
    candidate_digest = digest_bytes(candidate_bytes)
    request: dict[str, object] = {
        "request_id": request_id,
        "run_id": run_id,
        "frozen_spec_digest": frozen_spec_digest,
        "candidate_generation": generation,
        "candidate_digest": candidate_digest,
        "candidate_hex": candidate_bytes.hex(),
        "invariants": list(invariants),
        "verifier": {
            "id": snapshot.verifier_id,
            "digest": snapshot.binding_digest,
            "artifacts": [(item.name, item.digest) for item in snapshot.artifacts],
        },
    }
    request_digest = digest_json(request)
    request["request_digest"] = request_digest
    try:
        payload = _run_snapshot(
            snapshot,
            json.dumps(request, sort_keys=True, separators=(",", ":")).encode(),
        )
    except (
        OSError,
        subprocess.TimeoutExpired,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ):
        return None
    expected_keys = {"request_id", "request_digest", "verifier_digest", "results"}
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        return None
    if (
        payload["request_id"] != request_id
        or payload["request_digest"] != request_digest
        or payload["verifier_digest"] != snapshot.binding_digest
        or not isinstance(payload["results"], list)
    ):
        return None
    return tuple(payload["results"])


def _run_snapshot(snapshot: VerifierSnapshot, encoded: bytes) -> object:
    with tempfile.TemporaryDirectory(prefix="escapement-verifier-") as root:
        directory = Path(root) / snapshot.binding_digest
        directory.mkdir(mode=0o700)
        for artifact in snapshot.artifacts:
            target = directory / artifact.name
            target.write_bytes(artifact.content)
            target.chmod(0o700 if artifact.executable else 0o600)
        executable = directory / snapshot.executable_name
        with (
            tempfile.TemporaryFile() as stdin,
            tempfile.TemporaryFile() as stdout,
            tempfile.TemporaryFile() as stderr,
        ):
            stdin.write(encoded)
            stdin.seek(0)
            process = subprocess.Popen(
                (str(executable),),
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
                env=_child_env(),
                cwd=directory,
                start_new_session=True,
                preexec_fn=_set_output_file_limit,
            )
            deadline = time.monotonic() + snapshot.timeout
            while process.poll() is None:
                stdout_size = os.fstat(stdout.fileno()).st_size
                stderr_size = os.fstat(stderr.fileno()).st_size
                if stdout_size > MAX_OUTPUT_BYTES or stderr_size > MAX_OUTPUT_BYTES:
                    _kill_process_group(process)
                    raise ValueError("verifier exceeded output limit")
                if time.monotonic() >= deadline:
                    _kill_process_group(process)
                    raise ValueError("verifier timed out")
                time.sleep(0.01)
            returncode = process.returncode
            _kill_process_group(process)
            if returncode != 0:
                raise ValueError("verifier process failed")
            if (
                os.fstat(stdout.fileno()).st_size > MAX_OUTPUT_BYTES
                or os.fstat(stderr.fileno()).st_size > MAX_OUTPUT_BYTES
            ):
                raise ValueError("verifier exceeded output limit")
            stdout.seek(0)
            return json.loads(stdout.read(), object_pairs_hook=_unique_object)


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except OSError as exc:
        if exc.errno not in {errno.EPERM, errno.ESRCH}:
            raise
        _reap_process_leader(process)
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError as retry_exc:
            if retry_exc.errno not in {errno.EPERM, errno.ESRCH}:
                raise
        return
    _reap_process_leader(process)


def _reap_process_leader(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        pass


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result
