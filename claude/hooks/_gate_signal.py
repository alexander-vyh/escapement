"""Shared signal-capture for Claude Code gate hooks.

Per `claude/rules/gate-design.md` Rule 2: every gate must produce
persistent signal. This module is the canonical implementation —
all gates in `claude/hooks/` call `record()` at every decision point
so the corpus of gate-firings is uniform, queryable, and amenable to
the half-life review that Operating Rule 1 of the bureaucracy
principle requires.

## API

    from _gate_signal import record
    record(gate_name="spec_id_enforcement",
           decision="deny",
           reason="placeholder value 'none'",
           command="bd create --type=task ...")

## Storage shape

Each call appends one JSON line to `.beads/.gate-signal.jsonl`:

    {"ts": "2026-05-26T22:42:21Z",
     "gate": "spec_id_enforcement",
     "decision": "deny",
     "reason": "placeholder value 'none'",
     "session_id": "67b9768d-...",
     "extras": {"command": "bd create ..."}}

## Failure behavior

The gate's primary job is enforcement; logging is secondary. If the
`.beads/` directory doesn't exist, or the file isn't writable, or
disk is full, `record()` silently swallows the error. A failed
record never blocks a real gate decision — that would invert
priorities.

## Querying

See `claude/bin/gate_signal_query.py` for the canonical reader.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_SIGNAL_FILENAME = ".gate-signal.jsonl"
_BEADS_DIR_ENV = "BEADS_DIR"


def _resolve_signal_path() -> Path | None:
    """Find the .beads directory and return the signal file path.

    Prefers the BEADS_DIR env var (set in cake-style multi-worktree
    setups); otherwise walks up from CWD looking for .beads/.
    Returns None if no .beads/ is locatable — the gate then silently
    skips logging rather than blocking.
    """
    beads_dir_env = os.environ.get(_BEADS_DIR_ENV)
    if beads_dir_env:
        candidate = Path(beads_dir_env)
        if candidate.is_dir():
            return candidate / _SIGNAL_FILENAME

    cwd = Path(os.getcwd()).resolve()
    for parent in [cwd, *cwd.parents]:
        beads = parent / ".beads"
        if beads.is_dir():
            return beads / _SIGNAL_FILENAME

    return None


def record(
    gate_name: str,
    decision: str,
    reason: str = "",
    **extras: Any,
) -> None:
    """Append one signal record to .beads/.gate-signal.jsonl.

    Args:
        gate_name: stable identifier for the gate (e.g.
            'spec_id_enforcement'). Used by query tools to group
            decisions per gate.
        decision: one of 'allow', 'deny', 'ask', 'allow-with-warning',
            'waiver-accepted', or any other shape the gate uses.
        reason: human-readable rationale. For waivers, the user's
            captured reason text — this is the labeled training data
            future revisions read.
        **extras: any additional fields the specific gate wants to
            preserve (command excerpt, matched-pattern, target file,
            etc.). Stored under the 'extras' key.

    Fails silently on any I/O error. Never raises.
    """
    try:
        signal_path = _resolve_signal_path()
        if signal_path is None:
            return

        entry: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "gate": gate_name,
            "decision": decision,
            "reason": reason,
        }
        session_id = os.environ.get("CLAUDE_CODE_SESSION_ID")
        if session_id:
            entry["session_id"] = session_id
        if extras:
            entry["extras"] = extras

        line = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
        with open(signal_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        return  # signal capture must never block a gate decision
