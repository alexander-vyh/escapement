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
that this session wrote it. Just before each Bash call (PreToolUse) the hook
records HEAD and a fingerprint of every dirty path, filed under the host's
tool-call id; just after it (PostToolUse, or PostToolUseFailure when the
command exited non-zero) it consumes that same snapshot and names only the
paths that are new or changed, plus the files of commits the call made (reflog
`commit`, `commit (amend)` or `commit (initial)` entries only). The after-call
half uses the repository the before-half resolved; it never resolves a `cd`
itself. The before-half resolves a leading `cd` only on Claude; on Codex and
Pi the dispatcher already has, and doing it twice would land in the wrong
directory. Any tool-call id the host gives is accepted (it is hashed into a
file name). See _shell_snapshot.

The window runs from the START of the before-half (a write landing while it
runs is not in its snapshot) to the start of the after-half. PreToolUse runs
before the host's permission prompt, so on Claude, whose after-call payload
carries the command's own `duration_ms`, a window more than 2s longer than the
command ran names nothing: foreign writes made while a prompt waited are not
this call's. A Claude payload without `duration_ms` names nothing either.

Failing open. With no before-snapshot for this call -- a host that sends only
the after-call half, no tool-call id or session id, a before-half killed at
the host timeout, no repository found -- the call names nothing; it is never
compared with an older snapshot. A git status or HEAD lookup that fails or
times out, more than 2,000 dirty paths, a HEAD moved by anything but this
call's commits (pull, merge, rebase, reset, checkout), a prompt wait, or a
missing duration on Claude also
names nothing, and records a `blind` gate signal so the blindness shows in
telemetry. Git calls and every file hash, including re-hashing a committed
file, share a 4s budget per half; a file left unhashed when it runs out is
never named, and a file left unchecked -- unhashed after the call, or a
committed file there was no time to re-hash -- records an `out-of-time` blind
signal. A dirty file that cannot be read (permission denied) is never named
and records `unreadable`, once per call. A file past 1MB is fingerprinted by size and mtime, so a new mtime
with the same size is not proof of a write: it is not named, and records a
`stat-only` blind signal.

Known gaps, not built: Codex's `workdir` parameter is not in its payload, so a
command run in another directory that way -- another worktree, say, which is
common -- is invisible: its writes are not seen. Codex sends no duration, so on
Codex (and Pi) a write another session makes while a permission prompt waits
is named. Another session writing during this session's command is inside the
window and is named. A write left running in the background after the call
returns is not seen. `git stash pop` re-dirties files with new fingerprints and
names them. Subagents that share the parent's session id share its state, and
two calls finishing at once can each rewrite the reported-once memory
(reported.json), so a file may be reported twice. A `cd` that is not the
leading command is not followed. A write into another working tree is seen
only when a path in the command points into it (a gitignored .worktrees/<name>
checkout, an absolute path in another clone); a script that writes there
without naming the path is not, nor is a path built at run time (`$VAR`,
`${PWD}/..`, `$HOME`, `os.path.join`). Past 64 path tokens (`token-cap`) or 6
repositories (`repo-cap`) the rest are not watched, and a named repository
that cannot be snapshotted records its own blind. In a tree past
_shell_snapshot.LARGE_INDEX, files inside untracked directories are not seen
(`untracked-dirs`). An after-half whose snapshot is gone -- never taken, or
swept as an hour-old orphan -- records `no-pending`.

Exit codes:
  0 -- always; the report is the JSON on stdout
"""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _host_output  # noqa: E402
import _shell_snapshot as snap  # noqa: E402
from _agent_dispatch import host as _host  # noqa: E402

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
_CONCURRENT = ("These files changed while this command ran; another session writing "
               "at the same time may have changed some of them.")
_EVENTS = ("PreToolUse", "PostToolUse", "PostToolUseFailure")
_SHOWN = 8
# How much longer than the command's own run time the before/after window may be.
_PROMPT_SLACK = 2.0


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
    from test_oracle_brief_policy import brief_status, is_relevant_file

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
    from test_oracle_brief_gate import block_message

    try:
        return block_message(reason, repo_root, files, ask_decision=False)
    except TypeError:  # PR #250 drops the ask_decision keyword
        return block_message(reason, repo_root, files)


def _shown(names: list[str]) -> str:
    text = "', '".join(names[:_SHOWN])
    more = f" and {len(names) - _SHOWN} more" if len(names) > _SHOWN else ""
    return f"'{text}'{more}"


def _blind(why: str) -> None:
    """The hook could not tell what this call wrote; say so where it is counted."""
    _record_signal(gate_name="shell_write_gate", decision="blind", reason=why,
                   surface="shell-write")


def run(data: dict) -> str | None:
    """The report for this Bash call, or None."""
    hook_event = data.get("hook_event_name", "") or data.get("hookEventName", "")
    if hook_event not in _EVENTS or data.get("tool_name") != "Bash":
        return None
    started = time.time()
    session_dir = snap.session_dir(str(data.get("session_id") or data.get("sessionId") or ""))
    call_id = data.get("tool_use_id")
    if session_dir is None or not isinstance(call_id, str) or not call_id:
        if hook_event == "PreToolUse":
            _blind("no-session-id" if session_dir is None else "no-call-id")
        return None  # nothing pairs the two halves: say nothing
    budget = snap.Budget()
    if hook_event == "PreToolUse":
        _before_half(data, budget, session_dir, call_id, started)
        return None

    pending = snap.pop_pending(session_dir, call_id)
    if pending is None:
        _blind("no-pending")  # the before-half never ran here, or its snapshot was swept
        return None
    befores, taken_at = pending
    if not befores:
        return None  # the before-half ran and had nothing it could watch
    duration_ms = data.get("duration_ms")
    if not isinstance(duration_ms, (int, float)) or isinstance(duration_ms, bool):
        if _host(data) == "claude":  # Claude always sends it; without it the window is unknown
            _blind("no-duration")
            return None
    elif taken_at is None or started - taken_at > duration_ms / 1000 + _PROMPT_SLACK:
        _blind("prompt-wait")  # the window held a permission prompt, not just the command
        return None
    memory_path = session_dir / "reported.json"
    reported = snap.read_json(memory_path)
    primary = next(iter(befores))
    reports: list[str] = []
    for root, before in befores.items():
        report = _after_half(data, budget, root, before, primary, reported)
        if report:
            reports.append(report)
    snap.write_json(memory_path, reported)
    if not reports:
        return None
    return "\n\n".join(reports) + f"\n\n{_CONCURRENT}"


def _before_half(data: dict, budget, session_dir: Path, call_id: str, started: float) -> None:
    """Snapshot the cwd's repository and every one a path in the command names."""
    if _host(data) == "claude":  # Codex and Pi run this half behind the dispatcher,
        data = _effective_cwd(data)  # which has already followed a leading `cd`
    cwd = data.get("cwd")
    root = snap.repo_root(budget, cwd) if isinstance(cwd, str) and cwd else None
    tool_input = data.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    roots = [root] if root is not None else []
    if isinstance(command, str) and isinstance(cwd, str) and cwd:
        named_repos, token_cap = snap.named_repos(command, cwd)
        if token_cap:
            _blind("token-cap")  # paths past the token cap were not looked at
        for named in named_repos:
            # git, not the .git found on disk, says where the tree is: the same
            # answer, in the same spelling, the cwd's repository got.
            found = snap.repo_root(budget, str(named))
            if found is not None and found not in roots:
                roots.append(found)
    if len(roots) > snap.MAX_REPOS:
        _blind("repo-cap")  # repositories past the cap are not watched
    snaps: dict[str, dict] = {}
    for repo in roots[:snap.MAX_REPOS]:
        before = snap.take(budget, repo)
        if snap.usable(before):
            snaps[str(repo)] = before
        else:
            _blind(before.get("status", "unknown"))
    # Filed even when empty: it replaces any older snapshot under this id, and
    # tells the after-half this call had nothing to watch rather than no snapshot.
    snap.save_pending(session_dir, call_id, snaps, started)


def _label(root: Path, primary: Path, names: list[str]) -> list[str]:
    """How a path is shown: as written from the cwd's repository, else absolute."""
    if root == primary:
        return names
    try:
        base = root.relative_to(primary).as_posix() + "/"
    except ValueError:
        base = f"{root}/"
    return [base + name for name in names]


def _after_half(data: dict, budget, root: Path, before: dict, primary: Path,
                reported: dict) -> str:
    """The report for what this call wrote in one repository, or ""."""
    after = snap.take(budget, root, before)
    if not snap.usable(after):
        _blind(after.get("status", "unknown"))
        return ""
    committed = snap.commits_during(budget, root, before.get("head"), after.get("head"))
    if committed is None:
        _blind("head-moved")
        return ""
    written, unproven, out_of_time, unreadable = snap.written(budget, root, before, after, committed)
    if unproven:
        _blind("stat-only")  # a large file's mtime moved, its size did not: no proof
    if out_of_time:
        _blind("out-of-time")  # a file the budget left no time to check
    if unreadable:
        _blind("unreadable")  # a dirty file that cannot be read, before or after
    if after.get("untracked_dirs"):
        _blind("untracked-dirs")  # a large tree: files in untracked directories are not listed
    if not written:
        return ""
    changed = list(after["files"]) + committed
    memory = reported.get(str(root))
    memory = memory if isinstance(memory, dict) else {}
    reported[str(root)] = memory

    reports: list[str] = []
    untested = tdd_debt(root, changed, written, memory)
    if untested:
        _record_signal(
            gate_name="tdd_gate",
            decision="allow-with-warning",
            reason="impl file changed through the shell with no test changes in working tree",
            file=untested[0] if len(untested) == 1 else untested,
            surface="shell-write",
        )
        reports.append(
            f"TDD: {_shown(_label(root, primary, untested))} changed through the shell but no test files have been "
            f"modified yet. Write the failing test first. {_ONCE}; to go ahead "
            "without a test, carry on."
        )
    unbriefed = brief_debt(root, written, memory)
    if unbriefed:
        from test_oracle_brief_gate import record_decision_signal

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
            _brief_message(reason, root, _label(root, primary, names))
            + f"\n\n{_ONCE}; the files above were changed through the shell."
        )
    return "\n\n".join(reports)


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
