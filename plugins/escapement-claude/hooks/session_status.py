#!/usr/bin/env python3
"""SessionStart hook: emit one-line project status based on bd queue state.

Pattern table (first match wins):
  1.  No .beads/                                  → silence
  2.  Active molecule                              → "Molecule: [name] — [phase]"
  3.  1 in-progress, 0 ready, 0 blocked           → "▶ [title] ([id])"
  4.  1 in-progress, N ready, 0 blocked           → "▶ [title] ([id]) · N ready"
  5.  1 in-progress, 0 ready, N blocked           → "▶ [title] ([id])"
  6.  1 in-progress, N ready, N blocked           → "▶ [title] ([id]) · N ready"
  7.  N>1 in-progress                             → "N tasks in progress"
  8.  0 in-progress, N ready, 0 blocked           → "N tasks ready"
  9.  0 in-progress, N ready, N blocked           → "N tasks ready"
 10.  0 in-progress, 0 ready, N blocked           → "N tasks blocked — bd blocked for details"
 11.  0 in-progress, 0 ready, 0 blocked           → "Queue empty"

Always exits 0 — never blocks a session.

Input (via stdin): JSON with optional cwd field
Output (via stdout): {"systemMessage": "..."} or nothing
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

_TIMEOUT = 10
_MOL_STATUS_SCRIPT = Path.home() / ".beads" / "mol-status.sh"


def _read_cwd() -> Optional[str]:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
        cwd = payload.get("cwd") or ""
    except Exception:
        cwd = ""
    if not cwd:
        try:
            cwd = os.getcwd()
        except OSError:
            return None
    return cwd


def _run_bd(args: list[str], cwd: str) -> Optional[list]:
    """Run bd with --json; return parsed list or None on any failure."""
    try:
        r = subprocess.run(
            ["bd"] + args + ["--json"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
        result = json.loads(r.stdout)
        return result if isinstance(result, list) else None
    except Exception:
        return None


def _molecule_status(cwd: str) -> Optional[str]:
    """Return a one-line molecule status or None if no active molecule."""
    if not _MOL_STATUS_SCRIPT.is_file():
        return None
    try:
        r = subprocess.run(
            [str(_MOL_STATUS_SCRIPT)],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
            cwd=cwd,
        )
        output = r.stdout.strip()
        if not output:
            return None
    except Exception:
        return None

    # Extract name and phase from mol-status.sh output.
    # Output format varies; scan for common patterns.
    name: Optional[str] = None
    phase: Optional[str] = None

    for line in output.splitlines():
        line = line.strip().lstrip("#").strip()
        if not line:
            continue
        # "Active Molecule: dark-mode (mol-abc)" or "Molecule: dark-mode"
        m = re.search(r'[Mm]olecule[:\s]+([^\s(–—]+)', line)
        if m and not name:
            name = m.group(1).strip(":")
        # "Phase: Build" or "**Phase:** Validate"
        m = re.search(r'[Pp]hase[:\s*]+(\w+)', line)
        if m and not phase:
            phase = m.group(1)

    if name and phase:
        return f"Molecule: {name} — {phase}"
    if name:
        return f"Molecule: {name}"
    # Active molecule exists but couldn't parse details
    return "Molecule active"


def _task_line(task: dict) -> str:
    title = (task.get("title") or "").strip() or "untitled"
    task_id = task.get("id") or task.get("task_id") or ""
    return f"▶ {title} ({task_id})" if task_id else f"▶ {title}"


def _format_status(
    in_progress: list,
    ready: list,
    open_all: list,
) -> str:
    # Blocked = open tasks that are not in ready list
    ready_ids = {t.get("id") or t.get("task_id") for t in ready} - {None}
    blocked = [
        t for t in open_all
        if (t.get("id") or t.get("task_id")) not in ready_ids
    ]

    n_ip = len(in_progress)
    n_ready = len(ready)
    n_blocked = len(blocked)

    if n_ip > 1:
        return f"{n_ip} tasks in progress"  # pattern 7

    if n_ip == 1:
        base = _task_line(in_progress[0])
        if n_ready > 0:
            return f"{base} · {n_ready} ready"  # patterns 4, 6
        return base  # patterns 3, 5

    if n_ready > 0:
        return f"{n_ready} task{'s' if n_ready != 1 else ''} ready"  # patterns 8, 9

    if n_blocked > 0:
        return (
            f"{n_blocked} task{'s' if n_blocked != 1 else ''} blocked"
            " — bd blocked for details"
        )  # pattern 10

    return "Queue empty"  # pattern 11


def main() -> int:
    cwd = _read_cwd()
    if not cwd:
        return 0

    # Pattern 1: no beads
    if not (Path(cwd) / ".beads").is_dir():
        return 0

    # Pattern 2: active molecule (mol_status_check.py handles the detail;
    # we emit just the one-liner here)
    mol = _molecule_status(cwd)
    if mol:
        print(json.dumps({"systemMessage": mol}))
        return 0

    # Patterns 3–11: bd queue state
    in_progress = _run_bd(["list", "--status=in_progress"], cwd) or []
    ready = _run_bd(["ready"], cwd) or []
    open_all = _run_bd(["list"], cwd) or []

    # If all bd calls failed (bd not installed or error), degrade silently
    if not in_progress and not ready and not open_all:
        # Distinguish "all empty" from "all failed" via a quick check
        try:
            subprocess.run(["bd", "--version"], capture_output=True, timeout=5)
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return 0  # bd not available, degrade silently

    status = _format_status(in_progress, ready, open_all)
    print(json.dumps({"systemMessage": status}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
