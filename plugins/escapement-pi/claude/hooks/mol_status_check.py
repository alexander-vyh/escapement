#!/usr/bin/env python3
"""Claude Code hook: inject active molecule state on session start.

Runs on the SessionStart event. If the current working directory is a beads
project (.beads/ exists), runs ~/.beads/mol-status.sh and emits its output as
a systemMessage so Claude sees the current molecule phase and next step.

Always exits 0 — molecule status failures must never block a session.

Input (via stdin):
  JSON with session_id, cwd (optional)
Output (via stdout):
  JSON {"systemMessage": "..."} when active molecules exist, nothing otherwise.
Exit codes:
  0 — always
"""

import json
import os
import subprocess
import sys
from pathlib import Path

_MOL_STATUS_SCRIPT = Path.home() / ".beads" / "mol-status.sh"
_TIMEOUT_SECONDS = 5


def main() -> int:
    # Consume stdin per hook protocol
    payload_raw = ""
    try:
        payload_raw = sys.stdin.read()
    except Exception:
        pass

    # Determine working directory: prefer cwd from payload, fall back to os.getcwd()
    cwd = None
    if payload_raw:
        try:
            payload = json.loads(payload_raw)
            cwd = payload.get("cwd")
        except (json.JSONDecodeError, TypeError):
            pass
    if not cwd:
        try:
            cwd = os.getcwd()
        except OSError:
            return 0

    # Check if this is a beads project
    beads_dir = Path(cwd) / ".beads"
    if not beads_dir.is_dir():
        return 0

    # Check if mol-status.sh exists
    if not _MOL_STATUS_SCRIPT.is_file():
        return 0

    # Run mol-status.sh from the project directory
    try:
        result = subprocess.run(
            [str(_MOL_STATUS_SCRIPT)],
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            cwd=cwd,
        )
    except (subprocess.TimeoutExpired, OSError):
        return 0

    # Only emit if there's meaningful output
    output = result.stdout.strip()
    if not output:
        return 0

    # Emit as systemMessage so Claude sees the molecule state
    print(json.dumps({"systemMessage": output}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
