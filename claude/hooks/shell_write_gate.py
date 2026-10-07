#!/usr/bin/env python3
"""PostToolUse hook on Bash: a file changed through the shell owes what an Edit owes.

tdd-gate and the Test Oracle Brief gate match Write, Edit and apply_patch, so a
change made with a heredoc, `sed -i`, `cat >` or a script met neither. In a
25-run replay, 3 of 5 Escapement runs wrote every change that way and got zero
gate blocks; the real authoring session made 213 shell writes to 13 Edits.

This hook reads state, not the command: it lists the working tree's modified,
staged and untracked files and classifies them with the two gates' own
predicates, so what tdd-gate exempts or counts as a test is what this hook
exempts or counts as a test.

Many sessions share one checkout, so a dirty file is not proof that this
session wrote it. Before each Bash call (PreToolUse) the hook snapshots every
dirty path with a hash of its content into this session's own state file, and
after the call (PostToolUse) it holds only the paths that are new or whose hash
changed since that snapshot: dirt from before the session, another session's
writes, and this session's own Edit-tool writes (which met the edit-path gates)
all sit in the snapshot and are not blamed. The PostToolUse run snapshots again,
so a host that delivers only PostToolUse still works: its first observation is
the baseline and every later change is held. A file that owes a test, or a
brief, is reported once per file per session, and that memory is forgotten
when the debt is paid, so a relapse speaks again. Any error is silence.

The write has already happened, so nothing can be asked before it. The report
goes to the model the way each host takes a PostToolUse answer: Claude feeds a
`decision: block` reason back to the model, Codex passes `additionalContext`
(captured on 0.156.1), and the Pi extension appends either to the tool result.
The escape is the same as on the edit path: the report is not repeated for the
same file, so carrying on without the test is the override.

Known gaps: Codex does not put a shell tool's working directory in the payload,
and a `cd` into another repository is not followed; the payload's cwd is the
repository this hook reads. Another session writing during this session's
command is inside the window and is blamed on it.

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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _host_output  # noqa: E402
from _agent_dispatch import host as _host  # noqa: E402
from test_oracle_brief_gate import block_message, record_decision_signal  # noqa: E402
from test_oracle_brief_policy import brief_status, find_git_root, is_relevant_file  # noqa: E402

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
# Past this size a file is fingerprinted by size and mtime rather than read.
_HASH_LIMIT = 4 * 1024 * 1024


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


def fingerprint(path: Path) -> str | None:
    """A content hash of the file, or None when it cannot be read."""
    try:
        stat = path.stat()
        if stat.st_size > _HASH_LIMIT:
            return f"stat:{stat.st_size}:{stat.st_mtime_ns}"
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def snapshot(repo_root: Path, changed: list[str]) -> dict[str, str]:
    prints = {name: fingerprint(repo_root / name) for name in changed}
    return {name: value for name, value in prints.items() if value is not None}


def changed_files(repo_root: Path) -> list[str]:
    """Repo-relative files the working tree has changed, created, or staged."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"],
            cwd=str(repo_root), capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    names: list[str] = []
    entries = iter(result.stdout.split("\0"))
    for entry in entries:
        if len(entry) < 4:
            continue
        names.append(entry[3:])
        if entry[0] in "RC":
            next(entries, None)  # the rename's source path
    return [name for name in names if (repo_root / name).is_file()]


def _unreported(memory: dict, key: str, names: list[str]) -> list[str]:
    """`names` not yet reported under `key`; they are remembered as reported."""
    seen = memory.get(key)
    seen = list(seen) if isinstance(seen, list) else []
    fresh = [name for name in names if name not in seen]
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


def run(data: dict) -> str | None:
    """The report for this Bash call, or None. Updates the session's snapshot."""
    hook_event = data.get("hook_event_name", "") or data.get("hookEventName", "")
    if hook_event not in ("PreToolUse", "PostToolUse") or data.get("tool_name") != "Bash":
        return None
    cwd = data.get("cwd")
    session_id = str(data.get("session_id") or data.get("sessionId") or "")
    state_path = _state_path(session_id)
    if not isinstance(cwd, str) or not cwd or state_path is None:
        return None
    repo_root = find_git_root(cwd)
    if repo_root is None:
        return None
    changed = changed_files(repo_root)
    current = snapshot(repo_root, changed)
    state = _load_state(state_path)
    repo_state = state.get(str(repo_root))
    repo_state = repo_state if isinstance(repo_state, dict) else {}
    state[str(repo_root)] = repo_state
    before = repo_state.get("snapshot")
    repo_state["snapshot"] = current
    if hook_event == "PreToolUse" or not isinstance(before, dict):
        _save_state(state_path, state)  # the first look at a repo is its baseline
        return None
    written = [name for name in changed if name in current and current[name] != before.get(name)]
    memory = repo_state.get("reported")
    memory = memory if isinstance(memory, dict) else {}
    repo_state["reported"] = memory

    reports: list[str] = []
    untested = tdd_debt(repo_root, changed, written, memory) if written else []
    if untested:
        shown = "', '".join(untested)
        _record_signal(
            gate_name="tdd_gate",
            decision="allow-with-warning",
            reason="impl file changed through the shell with no test changes in working tree",
            file=untested[0] if len(untested) == 1 else untested,
            surface="shell-write",
        )
        reports.append(
            f"TDD: '{shown}' changed through the shell but no test files have been "
            f"modified yet. Write the failing test first. {_ONCE}; to go ahead "
            "without a test, carry on."
        )
    unbriefed = brief_debt(repo_root, written, memory)
    if unbriefed:
        reason, category, files = unbriefed
        record_decision_signal(
            data,
            decision="allow-with-warning",
            reason=reason,
            category=category,
            target=files[0],
            surface="shell-write",
            file_count=len(files),
        )
        reports.append(
            _brief_message(reason, repo_root, files)
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
    if _host(data) == "claude":
        print(json.dumps({"decision": "block", "reason": message}))
    else:
        print(json.dumps(_host_output.advisory(message, "PostToolUse")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
