"""Bounded child processes and the time budget for shadow_verifier.

Each guarantee here was a reproduced failure:
  time    the child runs in its own process group, killed in a `finally`
          on timeout, on exit and on any exception (Terminated included);
  pipe    the wait is on the process, not the pipe: an escaped (setsid)
          descendant or a background child can hold stdout open forever,
          so output is drained for at most DRAIN_SECONDS;
  memory  only a rolling TAIL_BYTES of output is kept (a flooding oracle
          reached 522MB RSS in 4s when it was buffered whole);
  budget  a non-finite budget would disable every bound, so it falls back.
"""

from __future__ import annotations

import fcntl
import hashlib
import math
import os
import signal
import subprocess
import sys
import threading
from pathlib import Path

BUDGET_ENV = "SHADOW_VERIFIER_BUDGET_SECONDS"
# The runner's whole budget: checkout, every lookup and every oracle.
DEFAULT_BUDGET_SECONDS = 40.0
# Everything the hook does before returning control to the agent. A loaded
# machine may be given more, never more than the cap.
SYNC_ENV = "SHADOW_VERIFIER_SYNC_SECONDS"
DEFAULT_SYNC_SECONDS = 2.0
MAX_SYNC_SECONDS = 10.0
DRAIN_SECONDS = 2.0
TAIL_BYTES = 4096


def budget() -> float:
    try:
        value = float(os.environ.get(BUDGET_ENV, DEFAULT_BUDGET_SECONDS))
    except ValueError:
        return DEFAULT_BUDGET_SECONDS
    if not math.isfinite(value):
        return DEFAULT_BUDGET_SECONDS
    return min(max(value, 0.0), DEFAULT_BUDGET_SECONDS)


def sync_seconds() -> float:
    try:
        value = float(os.environ.get(SYNC_ENV, DEFAULT_SYNC_SECONDS))
    except ValueError:
        return DEFAULT_SYNC_SECONDS
    if not math.isfinite(value) or value <= 0:
        return DEFAULT_SYNC_SECONDS
    return min(value, MAX_SYNC_SECONDS)


def run_bounded(argv, *, timeout: float, shell: bool = False, cwd=None, merge_stderr: bool = True):
    """Run in its own process group; (returncode, output tail), or None on timeout."""
    proc = subprocess.Popen(argv, shell=shell, cwd=cwd, stdin=subprocess.DEVNULL,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT if merge_stderr else subprocess.DEVNULL,
                            start_new_session=True)
    tail = bytearray()

    def drain() -> None:
        for chunk in iter(lambda: proc.stdout.read1(65536), b""):
            tail.extend(chunk)
            del tail[:-TAIL_BYTES]

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    returncode = None
    try:
        returncode = proc.wait(timeout=max(timeout, 0.0))
    except subprocess.TimeoutExpired:
        pass
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            pass
    if returncode is None:
        proc.wait()
    reader.join(DRAIN_SECONDS)
    if returncode is None:
        return None
    return returncode, bytes(tail).decode("utf-8", "replace")


def lookup(argv, cwd, timeout: float) -> str | None:
    """stdout of a short read-only command, or None when it failed or ran out."""
    if timeout <= 0.05:
        return None
    try:
        result = run_bounded(argv, timeout=timeout, cwd=cwd, merge_stderr=False)
    except OSError:
        return None
    if result is None or result[0] != 0:
        return None
    return result[1]


def add_harness_bin_to_path() -> None:
    """harness/bin sits beside claude/ in the repo and beside hooks/ in the
    Claude plugin tree; try both so this file is byte-identical in each."""
    here = Path(__file__).resolve().parent
    for candidate in (here.parent / "harness" / "bin", here.parent.parent / "harness" / "bin"):
        if (candidate / "derive_contract.py").exists():
            if str(candidate) not in sys.path:
                sys.path.insert(0, str(candidate))
            return


def acquire_slot(common_dir: Path, slots: int) -> int | None:
    """Hold one of `slots` lock slots for the runner's lifetime.
    The lock dies with the process, so a killed runner frees its slot."""
    directory = common_dir / "shadow-verifier"
    directory.mkdir(exist_ok=True)
    for index in range(slots):
        fd = os.open(directory / f"slot-{index}.lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return fd
        except BlockingIOError:
            os.close(fd)
    return None


def first_verdict(common_dir: Path, key: str, landing_id: str) -> str | None:
    """The landing_id that already judged `key`, or None after claiming it, so a
    repeated close or merge of the same landing is not counted twice."""
    landed = common_dir / "shadow-verifier" / "landed"
    landed.mkdir(parents=True, exist_ok=True)
    marker = landed / hashlib.sha256(key.encode()).hexdigest()[:32]
    try:
        fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        try:
            return marker.read_text().strip() or "unknown"
        except OSError:
            return "unknown"
    with os.fdopen(fd, "w") as out:
        out.write(landing_id)
    return None
