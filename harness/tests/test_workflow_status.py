#!/usr/bin/env python3
"""Tests for workflow_status.py — bead claude-workflow-setup-etp.

Business invariant
------------------
A background Workflow run that dies at the host's ~13-min task timeout leaves NO
completion signal; previously the orchestrator only discovered the death via
manual `ps` + file-activity inspection. This helper makes the run's state
*mechanically* classifiable from on-disk artifacts so a parent agent — re-invoked
by a ScheduleWakeup fallback (see bead 0wg) — can decide to resume, instead of
being silently stranded.

Independent source of truth (observed 2026-05-30 against real runs)
-------------------------------------------------------------------
* completion -> `wf_<runId>.json` exists with `status == "completed"`.
* liveness   -> `.../subagents/workflows/<runId>/agent-*.jsonl` mtimes advance
  while the run is alive; they go stale when it dies.

Fragile implementation these tests REJECT
------------------------------------------
"no completion journal => still running" — that default never detects death and
reproduces the exact silent-stranding the bug reports. The stale-activity case
must classify NOT-running.

Run: python3 -m pytest harness/tests/test_workflow_status.py -q
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
HARNESS_BIN = REPO / "harness" / "bin"
sys.path.insert(0, str(HARNESS_BIN))

import workflow_status as ws  # noqa: E402

STALE_AFTER = 180.0  # seconds of no agent-file activity => not alive
NOW = 1_000_000.0


# --- pure classification (the oracle) -----------------------------------------

def test_completed_journal_is_completed():
    v, _ = ws.classify({"status": "completed"}, agent_mtimes=[NOW - 5], now=NOW, stale_after=STALE_AFTER)
    assert v == "completed"


def test_completed_journal_overrides_stale_activity():
    # A finished run whose agent files are old must NOT be called dead.
    v, _ = ws.classify({"status": "completed"}, agent_mtimes=[NOW - 9999], now=NOW, stale_after=STALE_AFTER)
    assert v == "completed", "a completed run must never be classified as dead (no spurious resume)"


def test_journal_present_but_not_completed_is_ended_incomplete():
    for status in ("failed", "aborted", "error", None):
        v, _ = ws.classify({"status": status}, agent_mtimes=[NOW - 10], now=NOW, stale_after=STALE_AFTER)
        assert v == "ended_incomplete", f"status={status!r} should be ended_incomplete"


def test_no_journal_recent_activity_is_running():
    v, _ = ws.classify(None, agent_mtimes=[NOW - 30, NOW - 200], now=NOW, stale_after=STALE_AFTER)
    assert v == "running", "recent agent-file activity => the run is alive"


def test_no_journal_stale_activity_is_dead_not_running():
    # THE negative control: no completion + stale activity must be flagged dead,
    # never 'running' (the default that would reproduce silent stranding).
    v, _ = ws.classify(None, agent_mtimes=[NOW - 1000, NOW - 5000], now=NOW, stale_after=STALE_AFTER)
    assert v == "no_signal", "stale activity with no completion journal => silently died"


def test_no_journal_no_agents_is_no_signal():
    v, _ = ws.classify(None, agent_mtimes=[], now=NOW, stale_after=STALE_AFTER)
    assert v == "no_signal"


# --- exit-code contract (so a parent script can branch) -----------------------

def test_verdict_exit_codes_distinct_and_stable():
    codes = {v: ws.VERDICT_EXIT[v] for v in ("completed", "running", "ended_incomplete", "no_signal")}
    assert codes["completed"] == 0
    assert len(set(codes.values())) == 4, "each verdict needs a distinct exit code for branching"
    # 'completed' is the only success; everything else is non-zero so `verify`-style
    # callers treat not-completed as actionable.
    assert all(c != 0 for v, c in codes.items() if v != "completed")


# --- filesystem location + CLI end-to-end -------------------------------------

def _make_run(tmp_path, run_id, *, status=None, agent_age=None, now=NOW):
    """Build a fake ~/.claude/projects/<slug>/<session>/ tree for one run."""
    proj = tmp_path / "projects" / "-some-project"
    session = proj / "sess1"
    (session / "workflows").mkdir(parents=True)
    (session / "subagents" / "workflows" / run_id).mkdir(parents=True)
    if status is not None:
        (session / "workflows" / f"{run_id}.json").write_text(
            json.dumps({"runId": run_id, "status": status})
        )
    if agent_age is not None:
        import os
        f = session / "subagents" / "workflows" / run_id / "agent-abc.jsonl"
        f.write_text("{}")
        os.utime(f, (now - agent_age, now - agent_age))
    return tmp_path


def test_locate_and_classify_completed(tmp_path):
    root = _make_run(tmp_path, "wf_done", status="completed", agent_age=9999)
    v, detail = ws.classify_run("wf_done", projects_root=root / "projects", now=NOW, stale_after=STALE_AFTER)
    assert v == "completed"


def test_locate_and_classify_silent_death(tmp_path):
    # no completion journal, last agent activity 20 min ago => silent death
    root = _make_run(tmp_path, "wf_dead", status=None, agent_age=1200)
    v, detail = ws.classify_run("wf_dead", projects_root=root / "projects", now=NOW, stale_after=STALE_AFTER)
    assert v == "no_signal", f"a timed-out run with no journal must be flagged dead; got {v} ({detail})"


def test_cli_exit_code_reflects_verdict(tmp_path):
    import subprocess, os
    root = _make_run(tmp_path, "wf_cli", status="completed", agent_age=10)
    env = dict(os.environ)
    r = subprocess.run(
        ["python3", str(HARNESS_BIN / "workflow_status.py"),
         "--run", "wf_cli", "--projects-root", str(root / "projects")],
        capture_output=True, text=True, env=env, timeout=15,
    )
    assert r.returncode == 0, f"completed run must exit 0; stdout={r.stdout} stderr={r.stderr}"
    assert "completed" in r.stdout


def test_cli_dead_run_nonzero_and_named(tmp_path):
    import subprocess, os
    root = _make_run(tmp_path, "wf_x", status=None, agent_age=99999)
    r = subprocess.run(
        ["python3", str(HARNESS_BIN / "workflow_status.py"),
         "--run", "wf_x", "--projects-root", str(root / "projects"), "--stale-after", "180"],
        capture_output=True, text=True, env=dict(os.environ), timeout=15,
    )
    assert r.returncode != 0, "a dead/stranded run must exit non-zero so the parent acts"
    assert "no_signal" in r.stdout


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
