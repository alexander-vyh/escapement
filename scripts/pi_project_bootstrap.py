#!/usr/bin/env python3
"""Pi SessionStart gate: run project-bootstrap.sh for the Pi host.

The Pi extension runs gates through the in-process Python dispatcher
(claude/hooks/codex_pretool_dispatch.py), which executes Python files and never
spawns a child per gate. project-bootstrap.sh stays the one implementation of
the bootstrap for every host; this gate hands it the SessionStart payload on
stdin with ESCAPEMENT_HOST=pi, the same contract the Claude and Codex plugin
commands use, and passes its hook output through.

Once per session, one bash: the dispatcher's no-child invariant is about the
per-gate interpreter storm on every tool call, and the script itself shells out
to git, openspec and bd on every host. If the dispatcher's gate timeout fires
mid-run, subprocess.run kills the script before the timeout propagates.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "project-bootstrap.sh"


def main() -> int:
    completed = subprocess.run(
        ["bash", str(SCRIPT)],
        input=sys.stdin.read(),
        capture_output=True,
        text=True,
        env={**os.environ, "ESCAPEMENT_HOST": "pi"},
        check=False,
    )
    sys.stdout.write(completed.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
