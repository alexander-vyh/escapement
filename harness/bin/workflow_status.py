#!/usr/bin/env python3
"""Mechanical death-detection for background Workflow runs.

Bead: escapement-etp.

The problem
-----------
A background Workflow process is killed at the host's ~13-min task timeout with
NO completion notification. The orchestrator only learned of the death via manual
`ps` + file-activity inspection, then resumed via resumeFromRunId. This tool turns
that manual forensics into one deterministic command, so a parent agent re-invoked
by a ScheduleWakeup fallback (bead escapement-0wg) can decide — without
guessing — whether to resume.

What it reads (Claude Code on-disk artifacts, observed 2026-05-30)
------------------------------------------------------------------
For runId ``wf_<id>`` under ``~/.claude/projects/<project-slug>/<session>/``:
  * ``workflows/wf_<id>.json``                  -> final journal; ``status`` field.
  * ``subagents/workflows/wf_<id>/agent-*.jsonl`` -> written while the run is alive;
    mtimes go stale when it dies.

Verdicts
--------
  completed         journal status == "completed"            (exit 0)
  running           no completion journal, agent activity within --stale-after  (exit 3)
  ended_incomplete  journal present, status != "completed"   (exit 4)
  no_signal         no completion journal AND activity is stale / absent
                    (i.e. silently died, or never started)   (exit 5)

Only "completed" is success (exit 0). Every other verdict is actionable and exits
non-zero, so a caller can branch (resume / investigate).

Usage
-----
  workflow_status.py --run wf_847dcdad-5cc [--projects-root DIR] [--stale-after SEC]

The Claude Code runtime task timeout itself is NOT repo-configurable; this tool
makes its consequence observable rather than silent (see the bead for the
documented residual + the watchdog protocol in continuation-harness.md).
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from typing import Optional, Tuple

# How long without any agent-*.jsonl write before a journal-less run is presumed
# dead rather than alive. The host timeout is ~13 min; a few minutes of total
# silence is well past normal inter-write gaps.
DEFAULT_STALE_AFTER = 180.0

VERDICT_EXIT = {
    "completed": 0,
    "running": 3,
    "ended_incomplete": 4,
    "no_signal": 5,
}


def classify(
    journal: Optional[dict],
    agent_mtimes: list,
    now: float,
    stale_after: float,
) -> Tuple[str, str]:
    """Pure classification from a (maybe-None) journal dict + agent file mtimes.

    Precedence: a completion journal is authoritative (a finished run is never
    'dead', even if its agent files are old). Only when there is NO completion
    journal do we fall back to liveness from agent-file activity — and absence of
    recent activity means DIED, never 'running' (the default that reproduces the
    silent-stranding bug).
    """
    if isinstance(journal, dict):
        status = journal.get("status")
        if status == "completed":
            return "completed", "completion journal present (status=completed)"
        return "ended_incomplete", f"journal present but status={status!r}"

    # No completion journal — infer from agent-file activity.
    if not agent_mtimes:
        return "no_signal", "no completion journal and no agent activity files"
    newest = max(agent_mtimes)
    age = now - newest
    if age <= stale_after:
        return "running", f"agent activity {age:.0f}s ago (<= {stale_after:.0f}s)"
    return "no_signal", (
        f"no completion journal; last agent activity {age:.0f}s ago "
        f"(> {stale_after:.0f}s) — run presumed dead (host task timeout)"
    )


def _default_projects_root() -> str:
    return os.path.expanduser("~/.claude/projects")


def _find_run_paths(run_id: str, projects_root: str) -> Tuple[Optional[str], list]:
    """Locate (journal_path, [agent_jsonl_paths]) for run_id under projects_root.

    Searches every project/session because a runId is globally unique and the
    caller may not know which project/session spawned it.
    """
    journal_matches = glob.glob(
        os.path.join(projects_root, "*", "*", "workflows", f"{run_id}.json")
    )
    journal_path = journal_matches[0] if journal_matches else None
    agent_files = glob.glob(
        os.path.join(projects_root, "*", "*", "subagents", "workflows", run_id, "agent-*.jsonl")
    )
    return journal_path, agent_files


def classify_run(
    run_id: str,
    *,
    projects_root: Optional[str] = None,
    now: Optional[float] = None,
    stale_after: float = DEFAULT_STALE_AFTER,
) -> Tuple[str, str]:
    """Locate run_id's artifacts on disk and classify. Pure-ish wrapper for tests."""
    projects_root = str(projects_root or _default_projects_root())
    now = time.time() if now is None else now
    journal_path, agent_files = _find_run_paths(run_id, projects_root)
    journal = None
    if journal_path:
        try:
            journal = json.loads(open(journal_path).read())
        except (OSError, json.JSONDecodeError):
            journal = None
    mtimes = []
    for f in agent_files:
        try:
            mtimes.append(os.path.getmtime(f))
        except OSError:
            continue
    return classify(journal, mtimes, now, stale_after)


def main(argv: Optional[list] = None) -> int:
    p = argparse.ArgumentParser(description="Classify a background Workflow run's liveness.")
    p.add_argument("--run", required=True, help="Workflow runId (e.g. wf_847dcdad-5cc).")
    p.add_argument("--projects-root", default=None, help="Override ~/.claude/projects.")
    p.add_argument("--stale-after", type=float, default=DEFAULT_STALE_AFTER,
                   help="Seconds of no agent activity before a journal-less run is presumed dead.")
    args = p.parse_args(argv)

    verdict, detail = classify_run(
        args.run, projects_root=args.projects_root, stale_after=args.stale_after
    )
    print(json.dumps({"runId": args.run, "verdict": verdict, "detail": detail}))
    return VERDICT_EXIT.get(verdict, 1)


if __name__ == "__main__":
    sys.exit(main())
