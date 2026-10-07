#!/usr/bin/env python3
"""PostToolUse hook on Bash: a file changed through the shell owes what an Edit owes.

tdd-gate and the Test Oracle Brief gate match Write, Edit and apply_patch, so a
change made with a heredoc, `sed -i`, `cat >` or a script met neither. In a
25-run replay, 3 of 5 Escapement runs wrote every change that way and got zero
gate blocks; the real authoring session made 213 shell writes to 13 Edits.

This hook reads state, not the command: after each Bash call it lists the
working tree's modified, staged and untracked files and classifies them with
the two gates' own predicates, so what tdd-gate exempts or counts as a test is
what this hook exempts or counts as a test. A file that owes a test, or a
brief, is reported once per file per session -- the tdd_gate memory is shared
with tdd-gate itself, so a file it already asked about is not asked again --
and the memory is forgotten when the debt is paid, so a relapse speaks again.

The write has already happened, so nothing can be asked before it. The report
goes to the model the way each host takes a PostToolUse answer: Claude feeds a
`decision: block` reason back to the model, Codex passes `additionalContext`
(captured on 0.156.1), and the Pi extension appends either to the tool result.
The escape is the same as on the edit path: the report is not repeated for the
same file, so carrying on without the test is the override.

Known gap: Codex does not put a shell tool's working directory in the payload,
and a `cd` into another repository is not followed; the payload's cwd is the
repository this hook reads.

Exit codes:
  0 -- always; the report is the JSON on stdout
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _host_output  # noqa: E402
from _advisory_dedupe import already_reported_any, clear  # noqa: E402
from _agent_dispatch import host as _host  # noqa: E402
from test_oracle_brief_gate import block_message, record_decision_signal  # noqa: E402
from test_oracle_brief_policy import brief_status, find_git_root, is_relevant_file  # noqa: E402

try:
    from _gate_signal import record as _record_signal
except ImportError:  # pragma: no cover
    def _record_signal(*_args, **_kwargs) -> bool:
        return False

# tdd-gate's file name has a hyphen, so it is loaded by path.
_spec = importlib.util.spec_from_file_location(
    "tdd_gate", Path(__file__).resolve().with_name("tdd-gate.py")
)
tdd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tdd)

# The memory tdd-gate keeps per session; sharing it means one nudge per file
# whichever tool wrote it.
_TDD_MEMORY = "tdd_gate"
# The edit-path brief gate asks on every edit and keeps no memory.
_BRIEF_MEMORY = "test_oracle_brief_shell"
_ONCE = "This is reported once per file per session"


def changed_files(repo_root: Path) -> list[str]:
    """Repo-relative files the working tree has changed, created, or staged."""
    listed = dict.fromkeys(tdd.get_modified_files(str(repo_root)))
    return [name for name in listed if (repo_root / name).is_file()]


def tdd_debt(repo_root: Path, changed: list[str], session_id: str) -> list[str]:
    """Implementation files changed with no test change beside them, not yet reported."""
    if any(tdd.is_test_file(name) for name in changed):
        clear(_TDD_MEMORY, session_id)
        return []
    if not (tdd.has_tests_directory(str(repo_root)) or tdd.has_project_manifest(str(repo_root))):
        return []
    return [
        name for name in changed
        if not tdd.is_exempt_file(name)
        and not already_reported_any(_TDD_MEMORY, session_id, name)
    ]


def brief_debt(
    repo_root: Path, changed: list[str], session_id: str
) -> tuple[str, str, list[str]] | None:
    """(reason, category, files) when behaviour files changed without a valid brief."""
    relevant = [name for name in changed if is_relevant_file(name)]
    if not relevant:
        return None
    ok, reason, category = brief_status(repo_root, stage="edit")
    if ok:
        clear(_BRIEF_MEMORY, session_id)
        return None
    unreported = [name for name in relevant
                  if not already_reported_any(_BRIEF_MEMORY, session_id, name)]
    if not unreported:
        return None
    return reason or "Test Oracle Brief is missing required explanatory content.", category, unreported


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    if not isinstance(data, dict):
        return 0
    hook_event = data.get("hook_event_name", "") or data.get("hookEventName", "")
    if hook_event != "PostToolUse" or data.get("tool_name") != "Bash":
        return 0
    cwd = data.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        return 0
    repo_root = find_git_root(cwd)
    if repo_root is None:
        return 0
    changed = changed_files(repo_root)
    if not changed:
        return 0
    session_id = str(data.get("session_id") or data.get("sessionId") or "")

    reports: list[str] = []
    untested = tdd_debt(repo_root, changed, session_id)
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
    unbriefed = brief_debt(repo_root, changed, session_id)
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
            block_message(reason, repo_root, files, ask_decision=False)
            + f"\n\n{_ONCE}; the files above were changed through the shell."
        )
    if not reports:
        return 0

    message = "\n\n".join(reports)
    if _host(data) == "claude":
        print(json.dumps({"decision": "block", "reason": message}))
    else:
        print(json.dumps(_host_output.advisory(message, "PostToolUse")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
