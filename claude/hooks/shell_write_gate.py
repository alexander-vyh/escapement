#!/usr/bin/env python3
"""Bash hook: report, after the fact, files this session changed through the shell.

tdd-gate and the Test Oracle Brief gate match Write, Edit and apply_patch, so a
change made with a heredoc, `sed -i`, `cat >` or a script met neither. In a
25-run replay, 3 of 5 Escapement runs wrote every change that way and got zero
gate blocks; the real authoring session made 213 shell writes to 13 Edits.

This is not the edit-path gate and not a hold equal to its deny. The write has
already happened when this hook runs, so it can only tell the model what the
shell write owes -- a failing test first, a valid Test Oracle Brief -- using
the two gates' own predicates, so what tdd-gate exempts or counts as a test is
what this report exempts or counts as a test. Claude feeds the report back to
the model (a `decision: block` reason after PostToolUse, `additionalContext`
after PostToolUseFailure), Codex passes `additionalContext` (captured on
0.156.1), and the Pi extension appends it to the tool result. Carrying on
without the test is the override: a file is reported once per session, and
that memory is forgotten when the debt is paid, so a relapse speaks again.

Attribution. Many sessions share one checkout, so a dirty file is not proof
that this session wrote it. Before each Bash call (PreToolUse) the hook records
HEAD and every dirty path with a hash of its content in this session's own
state file; after the call (PostToolUse, or PostToolUseFailure when the command
exited non-zero) it names only the paths that are new or whose hash changed,
plus the files of commits made during the call. Dirt from before the session,
another session's writes between this session's calls, and this session's own
Edit-tool writes sit in the snapshot and are not named. Both halves follow a
leading `cd` the same way, so they read the same repository.

Failing open. Any doubt is silence and a fresh baseline, never blame: a git
status that fails or times out records the snapshot as unknown, a tree with
more than 2,000 dirty paths is not hashed, a file that cannot be read is
skipped, and a HEAD that moved anywhere but forward (reset, checkout) skips the
call. A host that delivers only the after-call half takes its first look as
the baseline.

Known gaps, not built: another session writing during this session's command
is inside the window and is named; a write left running in the background
after the call returns lands in a later call; `git stash pop` re-dirties files
with new hashes and names them; subagents that share the parent's session id
share its snapshot; a `cd` that is not the leading command is not followed.

Exit codes:
  0 -- always; the report is the JSON on stdout
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _host_output  # noqa: E402
from _agent_dispatch import host as _host  # noqa: E402
from test_oracle_brief_gate import block_message, record_decision_signal  # noqa: E402
from test_oracle_brief_policy import brief_status, find_git_root, is_relevant_file  # noqa: E402

try:
    from _effective_cwd import normalized as _effective_cwd
except ImportError:  # pragma: no cover
    def _effective_cwd(payload: dict) -> dict:
        return payload

try:
    from _gate_signal import record as _record_signal
except ImportError:  # pragma: no cover
    def _record_signal(*_args, **_kwargs) -> bool:
        return False


def _load_tdd_gate():
    """tdd-gate, loaded by path (its name has a hyphen); None once it is retired.

    With no TDD gate there is no TDD requirement to hold a shell write to, so
    the brief check carries on alone.
    """
    path = Path(__file__).resolve().with_name("tdd-gate.py")
    spec = importlib.util.spec_from_file_location("tdd_gate", path)
    if not path.is_file() or spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_ONCE = "This is reported once per file per session"
_SESSION_RE = re.compile(r"[A-Za-z0-9._-]{1,128}")
_EVENTS = ("PreToolUse", "PostToolUse", "PostToolUseFailure")
# Past this size a file is fingerprinted by size and mtime rather than read,
# and past the budget every further file is; a snapshot must fit the 10s hook.
_HASH_LIMIT = 1024 * 1024
_HASH_BUDGET = 64 * 1024 * 1024
# Past this many dirty paths, or files in one call's commits, nothing is named.
_MAX_PATHS = 2000
_SHOWN = 8
_UNREAD = "?"


def _state_path(session_id: str) -> Path | None:
    """This session's own state file; None for an id unsafe as a path part."""
    if not _SESSION_RE.fullmatch(session_id) or session_id in (".", ".."):
        return None
    root = os.environ.get("HARNESS_ROOT") or os.path.join(
        os.path.expanduser("~"), ".claude", "harness")
    return Path(root) / "threads" / session_id / "shell_write_gate.json"


def _load_state(path: Path) -> dict:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return state if isinstance(state, dict) else {}


def _save_state(path: Path, state: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".shell_write_gate.")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle)
        os.replace(tmp, path)
    except OSError:
        pass


def _git(repo_root: Path, *args: str, timeout: float = 2) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(["git", *args], cwd=str(repo_root), capture_output=True,
                              text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None


def changed_files(repo_root: Path) -> list[str] | None:
    """Repo-relative files the working tree has changed, created, or staged;
    None when git could not say (which is not the same as a clean tree)."""
    result = _git(repo_root, "status", "--porcelain=v1", "-z", "--untracked-files=all", timeout=4)
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
    return [name for name in names if (repo_root / name).is_file()]


def fingerprint(path: Path, budget: int = _HASH_LIMIT) -> tuple[str, int]:
    """(content hash, or size and mtime past the limits, or _UNREAD; budget left)."""
    try:
        stat = path.stat()
        if stat.st_size > min(_HASH_LIMIT, budget):
            return f"stat:{stat.st_size}:{stat.st_mtime_ns}", budget
        return hashlib.sha256(path.read_bytes()).hexdigest(), budget - stat.st_size
    except OSError:
        return _UNREAD, budget


def take_snapshot(repo_root: Path) -> dict:
    """HEAD and a fingerprint per dirty path, or a status saying why there is none."""
    changed = changed_files(repo_root)
    if changed is None:
        return {"status": "unknown"}
    if len(changed) > _MAX_PATHS:
        return {"status": "too-many-dirty"}
    head = _git(repo_root, "rev-parse", "--verify", "-q", "HEAD")
    files: dict[str, str] = {}
    budget = _HASH_BUDGET
    for name in changed:
        files[name], budget = fingerprint(repo_root / name, budget)
    return {
        "status": "ok",
        "time": time.time(),
        "head": head.stdout.strip() if head is not None and head.returncode == 0 else None,
        "files": files,
    }


def _usable(snap: object) -> bool:
    return isinstance(snap, dict) and snap.get("status") == "ok" and isinstance(snap.get("files"), dict)


def committed_files(repo_root: Path, before: dict, now: dict) -> list[str] | None:
    """Files of commits made during the call; None when HEAD moved anywhere but forward."""
    old, new = before.get("head"), now.get("head")
    if old == new or not old or not new:
        return []
    ancestor = _git(repo_root, "merge-base", "--is-ancestor", old, new)
    if ancestor is None or ancestor.returncode != 0:
        return None  # reset, checkout, or unknown: not this call's writes to name
    since = int(float(before.get("time") or 0)) - 2  # a pulled commit is older than the call
    log = _git(repo_root, "log", "--no-merges", f"--since=@{since}", "--format=",
               "--name-only", "-z", f"{old}..{new}")
    if log is None or log.returncode != 0:
        return []
    names = list(dict.fromkeys(name.strip("\n") for name in log.stdout.split("\0") if name.strip("\n")))
    if len(names) > _MAX_PATHS:
        return []
    return [name for name in names if (repo_root / name).is_file()]


def _unreported(memory: dict, key: str, names: list[str]) -> list[str]:
    """`names` not yet reported under `key`; they are remembered as reported."""
    seen = memory.get(key)
    seen = list(seen) if isinstance(seen, list) else []
    known = set(seen)
    fresh = [name for name in dict.fromkeys(names) if name not in known]
    memory[key] = seen + fresh
    return fresh


def tdd_debt(repo_root: Path, changed: list[str], written: list[str], memory: dict) -> list[str]:
    """Implementation files this command wrote with no test change in the tree, not yet reported."""
    tdd = _load_tdd_gate()
    if tdd is None:
        return []
    if any(tdd.is_test_file(name) for name in changed):
        memory.pop("tdd", None)
        return []
    if not (tdd.has_tests_directory(str(repo_root)) or tdd.has_project_manifest(str(repo_root))):
        return []
    return _unreported(memory, "tdd", [name for name in written if not tdd.is_exempt_file(name)])


def brief_debt(
    repo_root: Path, written: list[str], memory: dict
) -> tuple[str, str, list[str]] | None:
    """(reason, category, files) when this command wrote behaviour files without a valid brief."""
    relevant = [name for name in written if is_relevant_file(name)]
    if not relevant:
        return None
    ok, reason, category = brief_status(repo_root, stage="edit")
    if ok:
        memory.pop("brief", None)
        return None
    unreported = _unreported(memory, "brief", relevant)
    if not unreported:
        return None
    return reason or "Test Oracle Brief is missing required explanatory content.", category, unreported


def _brief_message(reason: str, repo_root: Path, files: list[str]) -> str:
    try:
        return block_message(reason, repo_root, files, ask_decision=False)
    except TypeError:  # PR #250 drops the ask_decision keyword
        return block_message(reason, repo_root, files)


def _shown(names: list[str]) -> str:
    text = "', '".join(names[:_SHOWN])
    more = f" and {len(names) - _SHOWN} more" if len(names) > _SHOWN else ""
    return f"'{text}'{more}"


def run(data: dict) -> str | None:
    """The report for this Bash call, or None. Updates the session's snapshot."""
    hook_event = data.get("hook_event_name", "") or data.get("hookEventName", "")
    if hook_event not in _EVENTS or data.get("tool_name") != "Bash":
        return None
    # The PreToolUse dispatcher reads a leading `cd`; this half must read the same repo.
    data = _effective_cwd(data)
    cwd = data.get("cwd")
    session_id = str(data.get("session_id") or data.get("sessionId") or "")
    state_path = _state_path(session_id)
    if not isinstance(cwd, str) or not cwd or state_path is None:
        return None
    repo_root = find_git_root(cwd)
    if repo_root is None:
        return None
    now = take_snapshot(repo_root)
    state = _load_state(state_path)
    repo_state = state.get(str(repo_root))
    repo_state = repo_state if isinstance(repo_state, dict) else {}
    state[str(repo_root)] = repo_state
    before = repo_state.get("snapshot")
    repo_state["snapshot"] = now
    committed = (committed_files(repo_root, before, now)
                 if hook_event != "PreToolUse" and _usable(before) and _usable(now) else None)
    if committed is None:
        _save_state(state_path, state)  # a baseline, or a call nothing can be said about
        return None
    files, old = now["files"], before["files"]
    written = [name for name, print_ in files.items()
               if print_ != _UNREAD and old.get(name) != _UNREAD and old.get(name) != print_]
    # A committed file already dirty before the call, with the same content, was not written by it.
    written += [name for name in committed if name not in files
                and (name not in old or fingerprint(repo_root / name)[0] != old[name])]
    changed = list(files) + committed
    memory = repo_state.get("reported")
    memory = memory if isinstance(memory, dict) else {}
    repo_state["reported"] = memory

    reports: list[str] = []
    untested = tdd_debt(repo_root, changed, written, memory) if written else []
    if untested:
        _record_signal(
            gate_name="tdd_gate",
            decision="allow-with-warning",
            reason="impl file changed through the shell with no test changes in working tree",
            file=untested[0] if len(untested) == 1 else untested,
            surface="shell-write",
        )
        reports.append(
            f"TDD: {_shown(untested)} changed through the shell but no test files have been "
            f"modified yet. Write the failing test first. {_ONCE}; to go ahead "
            "without a test, carry on."
        )
    unbriefed = brief_debt(repo_root, written, memory) if written else None
    if unbriefed:
        reason, category, names = unbriefed
        record_decision_signal(
            data,
            decision="allow-with-warning",
            reason=reason,
            category=category,
            target=names[0],
            surface="shell-write",
            file_count=len(names),
        )
        reports.append(
            _brief_message(reason, repo_root, names)
            + f"\n\n{_ONCE}; the files above were changed through the shell."
        )
    _save_state(state_path, state)
    return "\n\n".join(reports) or None


def main() -> int:
    try:
        data = json.load(sys.stdin)
        message = run(data) if isinstance(data, dict) else None
    except Exception:  # noqa: BLE001 - a gate that crashes must not cost the call
        return 0
    if message is None:
        return 0
    event = data.get("hook_event_name", "") or data.get("hookEventName", "")
    if _host(data) == "claude" and event == "PostToolUse":
        print(json.dumps({"decision": "block", "reason": message}))
    else:  # Claude reads PostToolUseFailure only through additionalContext
        print(json.dumps(_host_output.advisory(message, event)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
