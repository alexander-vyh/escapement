#!/usr/bin/env python3
"""Which files did this one shell command write? A before/after working-tree diff.

shell_write_gate's PreToolUse half calls `take()` and `save_pending()`; its
after-call half calls `pop_pending()`, `take()` again with the same per-path
method, and `written()`. The halves are paired by the host's tool-call id, so
the comparison is always "just before this command" against "just after it",
never against an earlier call's snapshot, which would hand this call every
foreign write made between calls.

Every git call shares one deadline (`Budget`) well inside the host's 10s hook
timeout. Anything that cannot be known is a blind status, never a clean tree.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,128}")
# Past this size a file is fingerprinted by size and mtime rather than read,
# and past the budget every further file is.
HASH_LIMIT = 1024 * 1024
HASH_BUDGET = 64 * 1024 * 1024
# Past this many dirty paths, or files in one call's commits, nothing is named.
MAX_PATHS = 2000
UNREAD = "?"
# A pending snapshot whose after-call half never came is dropped after this.
_PENDING_TTL = 3600
# The reflog subject of a commit this call made. Anything else moved HEAD for
# someone else's reasons: pull, merge, rebase, reset, checkout.
_COMMIT_SUBJECT = re.compile(r"commit(?: \((?:amend|initial)\))?: ")


class Budget:
    """One deadline for every git call a hook half makes."""

    def __init__(self, seconds: float = 5.0) -> None:
        self.deadline = time.monotonic() + seconds

    def git(self, cwd: str | Path, *args: str) -> subprocess.CompletedProcess | None:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0.05:
            return None
        try:
            return subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                                  text=True, timeout=remaining, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return None


def repo_root(budget: Budget, cwd: str) -> Path | None:
    if not os.path.isdir(cwd):
        return None
    result = budget.git(cwd, "rev-parse", "--show-toplevel")
    if result is None or result.returncode != 0 or not result.stdout.strip():
        return None
    return Path(result.stdout.strip())


def _dirty(budget: Budget, root: Path) -> list[str] | None:
    """Changed, staged and untracked files; None when git could not say."""
    result = budget.git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    if result is None or result.returncode != 0:
        return None
    names: list[str] = []
    entries = iter(result.stdout.split("\0"))
    for entry in entries:
        if len(entry) < 4:
            continue
        names.append(entry[3:])
        if entry[0] in "RC":
            next(entries, None)  # the rename's source path
    return [name for name in names if (root / name).is_file()]


def fingerprint(path: Path, method: str) -> str:
    """The 'hash' or 'stat' fingerprint of `path`; UNREAD when it cannot be read.

    A file past HASH_LIMIT is fingerprinted by stat whatever was asked; a hashed
    file that grew past it gets a stat print that cannot equal its old hash,
    which is right, since it changed.
    """
    try:
        stat = path.stat()
        if method == "stat" or stat.st_size > HASH_LIMIT:
            return f"stat:{stat.st_size}:{stat.st_mtime_ns}"
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return UNREAD


def _method(previous: str) -> str:
    return "stat" if previous.startswith("stat:") else "hash"


def take(budget: Budget, root: Path, before: dict | None = None) -> dict:
    """HEAD plus a fingerprint per dirty path, or {"status": <why blind>}.

    Given the before-snapshot, a path it fingerprinted by stat is fingerprinted
    by stat again and a hashed one is hashed again, so a path cannot look
    changed only because the hash budget ran out at a different place.
    """
    dirty = _dirty(budget, root)
    if dirty is None:
        return {"status": "unknown"}
    if len(dirty) > MAX_PATHS:
        return {"status": "too-many-dirty"}
    head = budget.git(root, "rev-parse", "--verify", "-q", "HEAD")
    old = (before or {}).get("files") or {}
    files: dict[str, str] = {}
    left = HASH_BUDGET
    for name in dirty:
        if name in old:
            method = _method(old[name])
        else:
            try:
                size = (root / name).stat().st_size
            except OSError:
                size = 0
            method = "hash" if size <= min(HASH_LIMIT, left) else "stat"
            left -= size if method == "hash" else 0
        files[name] = fingerprint(root / name, method)
    return {
        "status": "ok",
        "head": head.stdout.strip() if head is not None and head.returncode == 0 else None,
        "files": files,
    }


def commits_during(budget: Budget, root: Path, old: str | None, new: str | None) -> list[str] | None:
    """Files of commits this call made; None when HEAD moved for any other reason."""
    if old == new:
        return []
    if not old or not new:
        return None
    log = budget.git(root, "reflog", "show", "-n", "64", "--format=%H%x1f%gs", "HEAD")
    if log is None or log.returncode != 0:
        return None
    for line in log.stdout.splitlines():
        sha, _, subject = line.partition("\x1f")
        if sha == old:
            break
        if not _COMMIT_SUBJECT.match(subject):
            return None
    else:
        return None  # the call's starting point is not in the recent reflog
    diff = budget.git(root, "diff", "--name-only", "-z", old, new)
    if diff is None or diff.returncode != 0:
        return None
    names = [name for name in diff.stdout.split("\0") if name]
    if len(names) > MAX_PATHS:
        return None
    return [name for name in names if (root / name).is_file()]


def written(root: Path, before: dict, after: dict, committed: list[str]) -> list[str]:
    """Paths the call created or changed, and the files it committed."""
    old, new = before["files"], after["files"]
    names = [name for name, print_ in new.items()
             if UNREAD not in (print_, old.get(name)) and old.get(name) != print_]
    for name in committed:
        if name in new or name in names:
            continue
        if name in old:  # dirty before the call: committed as it was, or changed by it?
            if old[name] == UNREAD or fingerprint(root / name, _method(old[name])) == old[name]:
                continue
        names.append(name)
    return names


# --- this session's own state ------------------------------------------------

def session_dir(session_id: str) -> Path | None:
    if not _ID_RE.fullmatch(session_id) or session_id in (".", ".."):
        return None
    root = os.environ.get("HARNESS_ROOT") or os.path.join(
        os.path.expanduser("~"), ".claude", "harness")
    return Path(root) / "threads" / session_id / "shell_write_gate"


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def write_json(path: Path, value: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp.")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle)
        os.replace(tmp, path)
    except OSError:
        pass


def _pending_path(directory: Path, call_id: str) -> Path | None:
    if not _ID_RE.fullmatch(call_id) or call_id in (".", ".."):
        return None
    return directory / f"pending-{call_id}.json"


def save_pending(directory: Path, call_id: str, root: Path, snap: dict) -> None:
    path = _pending_path(directory, call_id)
    if path is None:
        return
    try:
        now = time.time()
        for stale in directory.glob("pending-*.json"):
            if now - stale.stat().st_mtime > _PENDING_TTL:
                stale.unlink(missing_ok=True)
    except OSError:
        pass
    write_json(path, {"repo": str(root), "snapshot": snap})


def pop_pending(directory: Path, call_id: str) -> tuple[Path, dict] | None:
    """This call's before-snapshot, consumed; None when its before-half left none."""
    path = _pending_path(directory, call_id)
    if path is None:
        return None
    pending = read_json(path)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
    snap, repo = pending.get("snapshot"), pending.get("repo")
    if not isinstance(repo, str) or not usable(snap):
        return None
    return Path(repo), snap


def usable(snap: object) -> bool:
    return isinstance(snap, dict) and snap.get("status") == "ok" and isinstance(snap.get("files"), dict)
