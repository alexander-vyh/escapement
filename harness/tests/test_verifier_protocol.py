from __future__ import annotations

import errno
import stat
import sys
import time
from pathlib import Path

import pytest

BIN = Path(__file__).resolve().parents[1] / "bin"
sys.path.insert(0, str(BIN))

import verifier_protocol  # noqa: E402
from verified_outcome_loop import (  # noqa: E402
    FrozenSpec,
    Invariant,
    VerifierBinding,
    certify_frozen_verifiers,
)


def _script(path: Path, source: str) -> Path:
    path.write_text("#!/usr/bin/env python3\n" + source)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def _frozen(executable: Path, dependencies: tuple[Path, ...] = ()) -> FrozenSpec:
    binding = VerifierBinding.freeze(
        verifier_id="bounded",
        executable=executable,
        dependencies=dependencies,
        timeout=2,
    )
    invariant = Invariant.freeze(
        identifier="bounded-output",
        statement="verifier terminates within declared resource bounds",
        verifier=binding,
        positive_control=b"good\n",
        negative_controls=(b"bad\n", b"", b"malformed\x00bytes"),
    )
    return FrozenSpec.freeze([invariant])


def test_concurrent_stdout_stderr_flood_is_killed_and_spool_is_cleaned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executable = _script(
        tmp_path / "flood",
        """import os
import time
chunk = b"x" * 65536
while True:
    os.write(1, chunk)
    os.write(2, chunk)
    time.sleep(0.01)
""",
    )
    spool = tmp_path / "spool"
    spool.mkdir()
    streams: list[Path] = []

    def tracked_file():
        path = tmp_path / f"stream-{len(streams)}"
        streams.append(path)
        return path.open("w+b")

    monkeypatch.setattr(verifier_protocol.tempfile, "tempdir", str(spool))
    monkeypatch.setattr(verifier_protocol.tempfile, "TemporaryFile", tracked_file)
    monkeypatch.setattr(verifier_protocol, "MAX_OUTPUT_BYTES", 131_072)
    frozen = _frozen(executable)

    started = time.monotonic()
    assert certify_frozen_verifiers(frozen) is False

    assert time.monotonic() - started < 1
    assert list(spool.iterdir()) == []
    assert all(path.stat().st_size <= 131_073 for path in streams[1:])


def test_undeclared_verifier_owned_import_fails_closed(tmp_path: Path) -> None:
    _script(tmp_path / "oracle_helper.py", 'EXPECTED = "676f6f640a"\n')
    executable = _script(
        tmp_path / "needs-helper",
        "from oracle_helper import EXPECTED\nraise SystemExit(0 if EXPECTED else 1)\n",
    )
    frozen = _frozen(executable)

    assert certify_frozen_verifiers(frozen) is False


def test_manifest_contract_names_host_runtime_outside_frozen_boundary() -> None:
    contract = VerifierBinding.__doc__ or ""

    assert "verifier-owned artifacts" in contract
    assert "shebang interpreter" in contract
    assert "trusted host runtime" in contract


@pytest.mark.parametrize("timeout", [float("nan"), float("inf")])
def test_non_finite_verifier_timeout_is_rejected(
    tmp_path: Path, timeout: float
) -> None:
    executable = _script(tmp_path / "finite", "raise SystemExit(0)\n")

    with pytest.raises(ValueError, match="finite positive timeout"):
        VerifierBinding.freeze(
            verifier_id="finite", executable=executable, timeout=timeout
        )


@pytest.mark.parametrize("duplicate", ["request_digest", "result"])
def test_duplicate_json_keys_fail_closed_at_every_object_level(
    tmp_path: Path, duplicate: str
) -> None:
    executable = _script(
        tmp_path / f"duplicate-{duplicate}",
        f"""import json
import sys
r = json.load(sys.stdin)
row = '{{"invariant_id":' + json.dumps(r["invariants"][0]["id"]) + ',"verifier_id":' + json.dumps(r["verifier"]["id"]) + ',"result":"PASS","detail":"x"}}'
if {duplicate!r} == "result":
    row = row[:-1] + ',"result":"FAIL"}}'
body = '{{"request_id":' + json.dumps(r["request_id"]) + ',"request_digest":' + json.dumps(r["request_digest"]) + ',"verifier_digest":' + json.dumps(r["verifier"]["digest"]) + ',"results":[' + row + ']}}'
if {duplicate!r} == "request_digest":
    body = body[:-1] + ',"request_digest":"stale"}}'
sys.stdout.write(body)
""",
    )

    assert certify_frozen_verifiers(_frozen(executable)) is False


def test_one_process_group_permission_race_retries_and_reaps_descendant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sentinel = tmp_path / "permission-survivor"
    executable = _script(
        tmp_path / "valid",
        """import json
import subprocess
import sys
r = json.load(sys.stdin)
subprocess.Popen([sys.executable, "-c", "import pathlib,time;time.sleep(.4);pathlib.Path(__SENTINEL__).write_text('bad')"])
result = "PASS" if r["candidate_hex"] == "676f6f640a" else "FAIL"
json.dump({
    "request_id": r["request_id"],
    "request_digest": r["request_digest"],
    "verifier_digest": r["verifier"]["digest"],
    "results": [{
        "invariant_id": item["id"],
        "verifier_id": r["verifier"]["id"],
        "result": result,
        "detail": "valid",
    } for item in r["invariants"]],
}, sys.stdout)
""".replace("__SENTINEL__", repr(str(sentinel))),
    )
    real_killpg = verifier_protocol.os.killpg
    calls = 0

    def one_eperm_then_real(pgid: int, sig: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise PermissionError(errno.EPERM, "simulated cleanup race")
        real_killpg(pgid, sig)

    monkeypatch.setattr(verifier_protocol.os, "killpg", one_eperm_then_real)

    assert certify_frozen_verifiers(_frozen(executable)) is True
    time.sleep(0.6)
    assert calls >= 5
    assert not sentinel.exists()
