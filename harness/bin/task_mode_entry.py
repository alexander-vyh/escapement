#!/usr/bin/env python3
"""
Claude Code PreToolUse hook — task-mode entry detector.

Watches for bd claim operations. When the agent claims a beads task, writes
session_mode.json to the thread dir so the stop hook can switch to queue-drain
gating for this session.

First-claim-wins: the first bd claim in a session fixes the repo_cwd. Subsequent
claims in the same session do not overwrite the existing record. This ensures the
stop hook always runs bd ready in the original project directory.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
import time
from typing import Optional

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from would_block_stop import thread_dir_for_session, harness_home

HARNESS_ROOT = harness_home()

_CLAIM_PATTERNS = [
    re.compile(r'\bbd\s+update\b.*\s--claim\b'),
    re.compile(r'\bbd\s+update\b.*\s-s\s+in_progress\b'),
    re.compile(r'\bbd\s+update\b.*\s--status\s+in_progress\b'),
    re.compile(r'\bbd\s+ready\b.*\s--claim\b'),
]


def _is_claim_command(command: str) -> bool:
    return any(p.search(command) for p in _CLAIM_PATTERNS)


def _extract_task_id(command: str) -> Optional[str]:
    """Extract the beads task ID from 'bd update <id> --claim'."""
    m = re.search(r'\bbd\s+update\s+(\S+)', command)
    if not m:
        return None
    task_id = m.group(1)
    # Sanity check: beads IDs are alphanumeric + dash (e.g. cake-123, claude-workflow-setup-4ab)
    if re.match(r'^[A-Za-z0-9][A-Za-z0-9-]*[A-Za-z0-9]$', task_id) or re.match(r'^[A-Za-z0-9]$', task_id):
        return task_id
    return None


def _lookup_parent_id(task_id: str) -> Optional[str]:
    """Run bd show <id> --json and extract the parent_id field."""
    try:
        r = subprocess.run(
            ["bd", "show", task_id, "--json"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            return None
        data = json.loads(r.stdout)
        if isinstance(data, list) and data:
            data = data[0]
        if isinstance(data, dict):
            return data.get("parent_id") or data.get("parent") or None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError, json.JSONDecodeError):
        pass
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    if payload.get("tool_name") != "Bash":
        return 0

    tool_input = payload.get("tool_input", {})
    command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
    if not command or not _is_claim_command(command):
        return 0

    session_id = payload.get("session_id") or ""
    thread_dir = thread_dir_for_session(session_id, HARNESS_ROOT)
    thread_dir.mkdir(parents=True, exist_ok=True)
    mode_file = thread_dir / "session_mode.json"

    # First-claim-wins: never overwrite an existing mode record.
    if mode_file.exists():
        return 0

    task_id = _extract_task_id(command)
    parent_id = _lookup_parent_id(task_id) if task_id else None

    try:
        mode_file.write_text(json.dumps({
            "mode": "task",
            "repo_cwd": os.getcwd(),
            "parent_id": parent_id,
            "entered_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "session_id": session_id,
        }))
    except OSError:
        pass  # Silent fail: don't block the tool call

    return 0


if __name__ == "__main__":
    sys.exit(main())
