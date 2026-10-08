#!/usr/bin/env python3
"""Which files did this one shell command write? A before/after working-tree diff.

shell_write_gate's PreToolUse half calls `take()` and `save_pending()`; its
after-call half calls `pop_pending()`, `take()` again with the same per-path
method, and `written()`. The halves are paired by the host's tool-call id, so
the comparison is always "just before this command" against "just after it",
never against an earlier call's snapshot, which would hand this call every
foreign write made between calls.

Every git call and every file hash shares one deadline (`Budget`) well inside
the host's 10s hook timeout. Git runs with `--no-optional-locks`, so the hook's
`git status` never takes .git/index.lock from under another session's `git add`.
Anything that cannot be known is a blind status, never a clean tree.

A pending snapshot whose after-call half never came (a killed command, a host
that dropped the event) is swept after an hour by the next before-half in any
session (the cross-session sweep runs at most once an hour).

Which repositories: the cwd's, plus any repository a path in the command
points into (`named_repos`) -- a gitignored .worktrees/<name> checkout, or an
absolute path in another clone. The command only nominates where to look; what
was written is still read from each tree's before/after state.

Big trees: past LARGE_INDEX bytes of index, `git status` runs with the default
`--untracked-files=normal` instead of `all`, so a new untracked directory is one
entry and the files in it are not seen (recorded as `untracked-dirs`). Git's own
untrackedCache and fsmonitor settings apply either way; nothing here turns
them off.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
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
# A path that could not be read (dangling, permission-denied), and a path
# left unhashed because the budget ran out: neither is ever named.
UNREAD = "?"
UNHASHED = "?unhashed"
# A pending snapshot whose after-call half never came is dropped after this.
_PENDING_TTL = 3600
# Past this index size (about 100k tracked files), untracked files are not
# listed one by one: `-uall` costs seconds per half at 200k files.
LARGE_INDEX = 8 * 1024 * 1024
# At most this many repositories are snapshotted for one call, found from at
# most this many path tokens; past either cap the gate records a blind signal.
MAX_REPOS = 6
MAX_TOKENS = 64
# Only this much of a command is scanned for path tokens (the token regex is
# not linear on a long run of slashes); past it the gate records token-cap.
MAX_SCAN = 16 * 1024
# Shell words are runs between these; a path token is one with a `/` and at
# least one other character (a bare `/` names nothing). A split, not a
# lookahead regex: the scan stays linear on a long run of slashes.
_WORD_BREAK = re.compile(r"[\s'\"`<>|;&()=]+")


def path_tokens(text: str) -> list[str]:
    return [word for word in _WORD_BREAK.split(text) if "/" in word and word.strip("/")]
# The reflog subject of a commit this call made. Anything else moved HEAD for
# someone else's reasons: pull, merge, rebase, reset, checkout.
_COMMIT_SUBJECT = re.compile(r"commit(?: \((?:amend|initial)\))?: ")


class Budget:
    """One deadline for every git call a hook half makes."""

    def __init__(self, seconds: float = 4.0) -> None:
        self.deadline = time.monotonic() + seconds

    def left(self) -> float:
        return self.deadline - time.monotonic()

    def git(self, cwd: str | Path, *args: str) -> subprocess.CompletedProcess | None:
        remaining = self.left()
        if remaining <= 0.05:
            return None
        try:
            return subprocess.run(["git", "--no-optional-locks", *args], cwd=str(cwd),
                                  capture_output=True, text=True, timeout=remaining, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return None


def repo_root(budget: Budget, cwd: str) -> Path | None:
    if not os.path.isdir(cwd):
        return None
    result = budget.git(cwd, "rev-parse", "--show-toplevel")
    if result is None or result.returncode != 0 or not result.stdout.strip():
        return None
    return Path(result.stdout.strip())


def named_repos(command: str, cwd: str) -> tuple[list[Path], bool]:
    """(working trees a path in `command` points into, found on disk without
    git; whether path tokens past MAX_TOKENS went unread)."""
    found: dict[str, Path] = {}
    scanned = command[:MAX_SCAN]
    tokens = list(dict.fromkeys(path_tokens(scanned) + _quoted_paths(scanned)))
    for token in tokens[:MAX_TOKENS]:
        try:
            path = Path(os.path.expanduser(token))
            path = path if path.is_absolute() else Path(cwd) / path
            path = path.resolve(strict=False)
        except (OSError, RuntimeError, ValueError):
            continue
        directory = disk_repo(path)
        if directory is not None:
            found.setdefault(str(directory), directory)
    return list(found.values()), len(tokens) > MAX_TOKENS or len(command) > MAX_SCAN


def disk_repo(path: Path) -> Path | None:
    """The nearest directory at or above `path` holding a `.git`, without git."""
    for directory in (path, *path.parents):
        try:
            # Python 3.9 raises PermissionError under an unsearchable directory;
            # the walk goes on to the directories above it.
            if (directory / ".git").exists():
                return directory
        except OSError:
            continue
    return None


def _quoted_paths(command: str) -> list[str]:
    """Path words as the shell would split them, so a quoted path with spaces
    stays one path; nothing when the command does not parse."""
    try:
        words = shlex.split(command, posix=True)
    except ValueError:
        return []
    return [word for word in words if "/" in word and word.strip("/") and any(c.isspace() for c in word)]


def _large(root: Path) -> bool:
    limit = os.environ.get("ESCAPEMENT_SHELL_WRITE_LARGE_INDEX", "")
    limit = int(limit) if limit.isdigit() else LARGE_INDEX
    git = root / ".git"
    try:
        if git.is_file():  # a linked worktree: "gitdir: <its own git dir>"
            text = git.read_text(encoding="utf-8").strip()
            git = (root / text.partition("gitdir:")[2].strip()).resolve()
        return (git / "index").stat().st_size > limit
    except (OSError, ValueError):
        return False


def _dirty(budget: Budget, root: Path) -> tuple[list[str], list[str]] | None:
    """(changed, staged and untracked files; untracked directories not listed
    file by file in a large tree), or None when git could not say."""
    untracked = "normal" if _large(root) else "all"
    result = budget.git(root, "status", "--porcelain=v1", "-z", f"--untracked-files={untracked}")
    if result is None or result.returncode != 0:
        return None
    names: list[str] = []
    entries = iter(result.stdout.split("\0"))
    for entry in entries:
        if len(entry) < 4:
            continue
        names.append(entry[3:])
        if entry[0] in "RC" or entry[1] in "RC":
            next(entries, None)  # the rename's source path (staged, or an intent-to-add rename)
    dirs = [name for name in names if name.endswith("/")]
    return [name for name in names if (root / name).is_file()], dirs


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
    listed = _dirty(budget, root)
    if listed is None:
        return {"status": "unknown"}
    dirty, untracked_dirs = listed
    if len(dirty) > MAX_PATHS:
        return {"status": "too-many-dirty"}
    head = budget.git(root, "rev-parse", "--verify", "-q", "HEAD")
    if head is None:
        return {"status": "unknown"}  # timed out: not the same as an unborn HEAD
    old = (before or {}).get("files") or {}
    files: dict[str, str] = {}
    left = HASH_BUDGET
    for name in dirty:
        out_of_time = budget.left() <= 0.05
        if name in old:
            method = _method(old[name])
            if method == "hash" and out_of_time:
                files[name] = UNHASHED  # cannot compare it now; never named
                continue
        else:
            try:
                size = (root / name).stat().st_size
            except OSError:
                size = 0
            method = "hash" if not out_of_time and size <= min(HASH_LIMIT, left) else "stat"
            left -= size if method == "hash" else 0
        files[name] = fingerprint(root / name, method)
    taken = {
        "status": "ok",
        "head": head.stdout.strip() if head.returncode == 0 else None,
        "files": files,
    }
    if untracked_dirs:
        taken["untracked_dirs"] = untracked_dirs
    return taken


def commits_during(budget: Budget, root: Path, old: str | None, new: str | None) -> list[str] | None:
    """Files of commits this call made; None when HEAD moved for any other reason."""
    if old == new:
        return []
    if not new:
        return None
    log = budget.git(root, "reflog", "show", "-n", "64", "--format=%H%x1f%gs", "HEAD")
    if log is None or log.returncode != 0:
        return None
    subject = ""
    for line in log.stdout.splitlines():
        sha, _, subject = line.partition("\x1f")
        if sha == old:
            break
        if not _COMMIT_SUBJECT.match(subject):
            return None
    else:
        # Reached the reflog's end: only a repository born in this call starts there.
        if old or not subject.startswith("commit (initial): ") or len(log.stdout.splitlines()) >= 64:
            return None
    if old:
        diff = budget.git(root, "diff", "--name-only", "-z", old, new)
    else:
        diff = budget.git(root, "ls-tree", "-r", "--name-only", "-z", new)
    if diff is None or diff.returncode != 0:
        return None
    names = [name for name in diff.stdout.split("\0") if name]
    if len(names) > MAX_PATHS:
        return None
    return [name for name in names if (root / name).is_file()]


def _stat_size(print_: str) -> str:
    return print_.split(":")[1] if print_.startswith("stat:") else ""


def written(budget: Budget, root: Path, before: dict, after: dict,
            committed: list[str]) -> tuple[list[str], list[str], list[str], list[str]]:
    """(named: paths the call created, changed or committed; unproven: paths that
    only might have; out of time: paths the budget left unchecked; unreadable).

    A file fingerprinted by stat whose size is unchanged but whose mtime moved
    might have been rewritten with the same length, or only touched: that is not
    proof, so it is unproven. A path left UNHASHED after the call, or a
    committed file there is no time left to re-hash (charged to `budget`), is
    out of time. A path UNREAD on either side is unreadable. None of those is
    named.
    """
    old, new = before["files"], after["files"]
    names: list[str] = []
    unproven: list[str] = []
    out_of_time: list[str] = []
    unreadable: list[str] = []
    for name, print_ in new.items():
        was = old.get(name)
        if print_ == UNHASHED:
            out_of_time.append(name)
            continue
        if UNREAD in (print_, was):
            unreadable.append(name)
            continue
        if was == print_:
            continue
        if was is not None and _stat_size(was) and _stat_size(was) == _stat_size(print_):
            unproven.append(name)
            continue
        names.append(name)
    for name in committed:
        if name in new or name in names:
            continue
        if name in old:  # dirty before the call: committed as it was, or changed by it?
            if old[name] == UNREAD:
                unreadable.append(name)
                continue
            if budget.left() <= 0.05:
                out_of_time.append(name)
                continue
            if fingerprint(root / name, _method(old[name])) == old[name]:
                continue
        names.append(name)
    return names, unproven, out_of_time, unreadable


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


def _pending_path(directory: Path, call_id: str) -> Path:
    """Any non-empty id the host gives (OpenAI Responses ids carry a `|`)."""
    digest = hashlib.sha256(call_id.encode("utf-8", "surrogatepass")).hexdigest()[:40]
    return directory / f"pending-{digest}.json"


def _sweep(directory: Path) -> None:
    """Drop pending snapshots past their TTL: this session's every time, every
    session's at most once an hour (a session's last orphans have no next call)."""
    now = time.time()
    globs = [directory.glob("pending-*.json")]
    marker = directory.parent.parent / ".shell_write_gate.swept"
    try:
        if not marker.exists() or now - marker.stat().st_mtime > _PENDING_TTL:
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.touch()
            globs.append(directory.parent.parent.glob("*/shell_write_gate/pending-*.json"))
    except OSError:
        pass
    for found in globs:
        try:
            for stale in found:
                if now - stale.stat().st_mtime > _PENDING_TTL:
                    stale.unlink(missing_ok=True)
        except OSError:
            continue


def save_pending(directory: Path, call_id: str, snaps: dict[str, dict], started: float) -> None:
    """File the before-snapshots (repository -> snapshot), stamped with when the
    before-half STARTED: a write landing while it ran is not in the snapshot,
    so it counts as window."""
    _sweep(directory)
    write_json(_pending_path(directory, call_id), {"repos": snaps, "at": started})


def pop_pending(directory: Path, call_id: str) -> tuple[dict[Path, dict], float | None] | None:
    """({repo: before-snapshot}, when they were taken), consumed; None when the
    before-half left nothing at all. A before-half that ran but had nothing to
    watch files an empty one, so ({}, at) is "nothing to compare", and None is
    "the before-half never ran, or its snapshot was lost"."""
    path = _pending_path(directory, call_id)
    pending = read_json(path)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
    repos = pending.get("repos")
    at = pending.get("at")
    if not isinstance(repos, dict):
        return None
    snaps = {Path(repo): snap for repo, snap in repos.items() if usable(snap)}
    return snaps, at if isinstance(at, (int, float)) else None


def usable(snap: object) -> bool:
    return isinstance(snap, dict) and snap.get("status") == "ok" and isinstance(snap.get("files"), dict)
