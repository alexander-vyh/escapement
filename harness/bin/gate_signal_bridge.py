"""Bridge a Stop-gate decision to `.beads/.gate-signal.jsonl` (corpus-bridge).

harness/bin is state-only and cannot import claude/hooks/_gate_signal, so this
mirrors its line shape and .beads resolution (BEADS_DIR, else walk up from the
cwd). REQUIRED because the half-life toolchain and the running launchd monitor
read ONLY `.gate-signal.jsonl`; a decision logged only to incidents.jsonl is
invisible to half-life review (the corpus-split gap the 858 panel flagged).
Shared by every host's Stop adapter so their decisions land in one corpus.
Best-effort -- never fails the hook.
"""

from __future__ import annotations

import json
import os
import pathlib
import time


def record_gate_signal(decision: str, reason: str, session_id: str, notes: str = "") -> None:
    try:
        beads = None
        env = os.environ.get("BEADS_DIR")
        if env and pathlib.Path(env).is_dir():
            beads = pathlib.Path(env)
        else:
            cwd = pathlib.Path(os.getcwd()).resolve()
            for parent in [cwd, *cwd.parents]:
                if (parent / ".beads").is_dir():
                    beads = parent / ".beads"
                    break
        if beads is None:
            return
        line = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "gate": "continuation-harness",
            "decision": decision,
            "reason": reason,
            "session_id": session_id,
            "extras": {"notes": notes} if notes else {},
        }
        with (beads / ".gate-signal.jsonl").open("a") as f:
            f.write(json.dumps(line) + "\n")
    except OSError:
        pass
