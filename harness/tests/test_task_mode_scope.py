#!/usr/bin/env python3
"""Task-mode gate must not block on whole-repo backlog for an UNSCOPED session
(bead claude-workflow-setup-e9v.11).

WHY THIS EXISTS
---------------
A session enters task mode when task_mode_entry.py sees a bd claim. But a claim
like `bd ready --claim` has no `bd update <id>` to parse, so `_extract_task_id`
returns None and the writer stamped session_mode.json with
`task_id: null, parent_id: null`. `_check_task_mode_queue` then runs `bd ready`
with NO `--parent` scope = the ENTIRE repo backlog, so a session whose own work
is complete can never Stop — it blocks on unrelated beads forever (observed: a
finished session stuck behind tasks_remain_in_queue for whole-repo backlog).
This contradicts continuation-harness.md's own rule ("if bd ready shows tasks
outside the current session's scope, ignore them — they belong to a different
session").

TEST ORACLE BRIEF (rapid form — narrow scoping fix)
---------------------------------------------------
1. Business invariant: task-mode queue-drain gating applies ONLY to a session
   with a real scope (a claimed task_id or its molecule parent_id). A scopeless
   task-mode record must NOT gate Stop on whole-repo backlog — it falls through
   to the normal contract gate (which still blocks a red contract: teeth kept).
2. Negative control (the bug): mode==task but task_id AND parent_id both null
   -> task-mode gating must NOT be in effect.
3. Positive controls: a scoped session (parent_id OR task_id set) -> task-mode
   gating IS in effect (the queue-drain feature is preserved); a non-claim
   `bd ready --claim` writes NO scopeless record at the source.
4. Fragile impl rejected: "unscoped -> allow" inside _check_task_mode_queue
   (would bypass the contract gate and let a red session stop). The fix instead
   makes main() treat scopeless as non-task-mode -> contract gate still runs.

Run: python3 -m pytest harness/tests/test_task_mode_scope.py -q
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "harness" / "bin"))

import stop_hook  # noqa: E402


# ---------------------------------------------------------------------------
# _task_mode_in_effect — the scoping rule (pure)
# ---------------------------------------------------------------------------
def test_unscoped_task_mode_not_in_effect() -> None:
    """NEGATIVE CONTROL / the bug: both ids null -> task-mode gating off."""
    sm = {"mode": "task", "repo_cwd": "/r", "task_id": None, "parent_id": None}
    assert stop_hook._task_mode_in_effect(sm) is False


def test_parent_scoped_task_mode_in_effect() -> None:
    """POSITIVE CONTROL: a molecule-scoped session keeps queue-drain gating."""
    sm = {"mode": "task", "repo_cwd": "/r", "task_id": "x.1", "parent_id": "x"}
    assert stop_hook._task_mode_in_effect(sm) is True


def test_leaf_task_scoped_task_mode_in_effect() -> None:
    """POSITIVE CONTROL: a standalone leaf task (task_id only) is still scoped."""
    sm = {"mode": "task", "repo_cwd": "/r", "task_id": "x.1", "parent_id": None}
    assert stop_hook._task_mode_in_effect(sm) is True


def test_non_task_mode_not_in_effect() -> None:
    assert stop_hook._task_mode_in_effect({"mode": "task"}) is False  # no scope
    assert stop_hook._task_mode_in_effect({"mode": "conversational"}) is False
    assert stop_hook._task_mode_in_effect(None) is False
    assert stop_hook._task_mode_in_effect("garbage") is False


# ---------------------------------------------------------------------------
# task_mode_entry.py — root cause: do not stamp a scopeless record
# ---------------------------------------------------------------------------
def _run_entry(command: str, thread_dir: pathlib.Path):
    payload = json.dumps({
        "tool_name": "Bash", "session_id": "S",
        "tool_input": {"command": command},
    })
    env = dict(os.environ)
    env["HARNESS_THREAD_DIR"] = str(thread_dir)
    return subprocess.run(
        ["python3", str(REPO / "harness" / "bin" / "task_mode_entry.py")],
        input=payload, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )


def test_entry_skips_unscopeable_ready_claim(tmp_path) -> None:
    """ROOT CAUSE: `bd ready --claim` has no parseable task id, so no scope can be
    determined -> the writer must NOT create a scopeless task-mode record."""
    td = tmp_path / "thread"
    _run_entry("bd ready --claim", td)
    assert not (td / "session_mode.json").exists(), (
        "an unscopeable claim must not create a task-mode record (root cause of e9v.11)"
    )


def test_entry_skips_when_no_extractable_id(tmp_path) -> None:
    """A claim whose id cannot be extracted must also not create a scopeless record."""
    td = tmp_path / "thread"
    _run_entry("bd update --claim", td)  # no id token
    assert not (td / "session_mode.json").exists()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
