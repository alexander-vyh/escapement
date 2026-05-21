#!/usr/bin/env python3
"""
Claude Code Stop-hook adapter for continuation-harness.

Reads the Anthropic hook protocol JSON from stdin, calls would_block_stop
against the active thread directory, logs the decision to incidents.jsonl,
and emits a block decision (with constructive resumption prompt) when warranted.

v0: single active thread at harness/threads/current/. The session_id from the
hook payload is included in the incidents log for later correlation.

Coexists with ~/.claude/hooks/validate_no_shirking.py — both run on Stop;
both can block. Additive coverage.
"""

from __future__ import annotations

import json
import pathlib
import sys
import time

# Self-locate for the sibling import — works whether this script lives in the
# repo source tree or is installed to ~/.claude/harness/bin. No hardcoded path.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from would_block_stop import (  # noqa: E402
    would_block_stop,
    load_thread_state,
    thread_dir_for_session,
    harness_home,
)

# State root is the standard per-user location (env-overridable), NOT relative
# to where this code is installed — so dev-copy and installed-copy share state
# and nothing is written into a repo working tree.
HARNESS_ROOT = harness_home()
INCIDENTS_LOG = HARNESS_ROOT / "incidents.jsonl"

RESUMPTION_PROMPT = (
    "continuation-harness: {reason}. "
    "To allow Stop next turn, do one of: "
    "(1) run `~/.claude/harness/bin/verify` and have it exit 0 "
    "(declare a contract via init_contract.py first if you haven't); "
    "(2) call the ScheduleWakeup tool to register a future check-in; "
    "(3) ask the user to release with 'stop' or 'end here'. "
    "Per the outcome-bias rule, don't keep doing things — finish the outcome or schedule resumption."
)


def _read_payload() -> dict:
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return {}


def _log_incident(record: dict) -> None:
    try:
        INCIDENTS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with INCIDENTS_LOG.open("a") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        pass  # Don't fail the hook on logging error.


def main() -> int:
    payload = _read_payload()

    # Anthropic's stop_hook_active flag prevents infinite block loops.
    if payload.get("stop_hook_active"):
        return 0

    session_id = payload.get("session_id") or "unknown"

    thread_dir = thread_dir_for_session(session_id, HARNESS_ROOT)
    thread_dir.mkdir(parents=True, exist_ok=True)
    state = load_thread_state(thread_dir, recent_user_message=None)
    decision, reason = would_block_stop(state)

    _log_incident({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "session_id": session_id,
        "decision": decision,
        "reason": reason,
        "was_correct": None,
        "notes": "",
    })

    if decision == "block":
        out = {
            "decision": "block",
            "reason": RESUMPTION_PROMPT.format(reason=reason),
        }
        print(json.dumps(out))
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
