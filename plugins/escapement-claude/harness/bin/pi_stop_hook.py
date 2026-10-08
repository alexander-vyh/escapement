#!/usr/bin/env python3
"""
Pi Stop adapter over the shared stop-decision core.

The Pi extension runs Stop gates at Pi's `agent_end` with a Claude-shaped Stop
payload and continues the run with a block's reason as a follow-up user
message. This adapter is thin, like codex_stop_hook.py: translate the payload
into thread state, ask `would_block_stop`, add the same double-keyed wind-down
rung Codex uses, and word the way forward for Pi.

What Pi gives that Codex does not: the extension writes the session as a
Claude-shaped JSONL transcript, so code-touch detection (the no_declaration
rung) and the user's own "stop" release come from what the session actually
did, exactly as on Claude.

What stays with Claude's stop_hook.py: scheduled wakeups, task-mode queue
rungs and the local judge -- the continuation harness, which Pi does not have.
So no reason here names ScheduleWakeup or a ~/.claude path; every command it
names is one this Pi package ships.

A delegated worker -- a Pi session whose header names a parent session -- is
held to its delegated scope, not its parent's outcome: the parent owns the
outcome and its verification, which delegation forbids the worker to run. So
for a worker, a block becomes "hand your work back" (end with a message; omp
delivers it to the parent), the parent's IRC "stop" is its user's release, and
a run of identical blocks is capped so a gate bug cannot loop a worker without
bound (escapement-by3e).

Fail-open: any internal error allows the stop AND appends an incident record,
so a gate bug degrades to "no gate", never a stuck session, and is visible.
stdout carries at most the single decision JSON.
"""

from __future__ import annotations

import json
import os
import pathlib
import shlex
import sys
import time

BIN = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(BIN))

# Absence of the vendored core is a packaging failure; it must land on the same
# fail-open-with-a-record path as every other error rather than crash on import.
try:
    from codex_stop_hook import git_work_remains, is_completion_claim
    from gate_signal_bridge import record_gate_signal
    from would_block_stop import harness_home, load_thread_state, thread_dir_for_session, would_block_stop
except ImportError as exc:  # pragma: no cover - exercised via a broken install
    _CORE_IMPORT_ERROR: str | None = str(exc)
else:
    _CORE_IMPORT_ERROR = None

_EXPLANATIONS = {
    "no_declaration": (
        "this session changed code in the repository but never declared what the "
        "change is for, so there is nothing to check it against and no way to tell "
        "whether it worked."
    ),
    "no_completion_or_resumption_proof": (
        "this session declared an outcome, but its verification has not passed "
        "since then (or the declared contract is unreadable)."
    ),
    "verification_suppressed": (
        "the declared verify command exited 0 but neuters itself (`|| true`, a bare "
        "`true`, `--no-verify`, `SKIP=`), so re-running it will not release this gate."
    ),
    "worker_no_handoff": (
        "this delegated worker changed work but ended with no message, so its "
        "parent has nothing to read about what it produced."
    ),
    "winddown_claim_work_remains": (
        "your last message says the work is done, but {cwd} still has git residue "
        "(modified tracked files, unpushed commits, or an upstream-gone branch)."
    ),
}


def resumption(reason: str, session_id: str, cwd: str) -> str:
    """The block text: what is unproven and the commands that prove or release it."""
    env = f"CLAUDE_CODE_SESSION_ID={shlex.quote(session_id)}"
    declare = (
        f"{env} python3 {shlex.quote(str(BIN / 'init_contract.py'))} "
        "--goal \"<what a user can observe>\" --verify \"<command whose exit 0 proves it>\""
    )
    derive = f"{env} python3 {shlex.quote(str(BIN / 'derive_contract.py'))} --bead <id>"
    verify = f"{env} bash {shlex.quote(str(BIN / 'verify'))}"
    explanation = _EXPLANATIONS.get(reason, "this turn ends with unproven work.").format(cwd=cwd or "the cwd")
    if reason == "worker_no_handoff":
        return (
            f"Escapement stop gate ({reason}): {explanation} End your turn with a "
            "message naming what you produced and where it is persisted -- omp "
            "delivers your last message to your parent, which owns verifying the "
            "outcome; or your parent can release you by sending 'stop'."
        )
    if reason == "winddown_claim_work_remains":
        ways = (
            "(1) commit and push the remaining tracked changes, or clean them up "
            f"deliberately; (2) declare and prove the outcome: `{declare}`, then `{verify}`"
        )
    elif reason == "verification_suppressed":
        ways = (
            f"(1) re-declare with a verify command that exits non-zero on failure: "
            f"`{declare}`; (2) then run `{verify}` until it exits 0"
        )
    else:
        ways = (
            f"(1) declare the outcome and its oracle: `{declare}` -- or, if a bead "
            f"covers this work, `{derive}`; (2) run `{verify}` until it exits 0; "
            "(3) if the edits were a mistake, revert them"
        )
    return (
        f"Escapement stop gate ({reason}): {explanation} You are not done: continue "
        f"with the next concrete step instead of ending the turn. Ways forward: {ways}; "
        "or the user can release this session by saying 'stop'."
    )


def last_user_text(transcript_path: object) -> str | None:
    """The newest user-typed text in a Claude-shaped transcript (tool results are
    not the user speaking)."""
    if not isinstance(transcript_path, str) or not transcript_path:
        return None
    try:
        lines = pathlib.Path(transcript_path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        message = row.get("message") if isinstance(row, dict) else None
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content
        texts = [
            block.get("text") for block in content or []
            if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)
        ]
        if texts:
            return "\n".join(texts)
    return None


# A worker held this many times in a row for the same reason is let go: the cap
# turns a gate bug into one recorded livelock signal, not unbounded spend.
WORKER_BACKSTOP_BLOCKS = 3


def worker_scope(decision: str, reason: str, handoff: object) -> tuple[str, str]:
    """A worker's block, judged by its delegated scope: did it hand anything back."""
    if decision != "block":
        return decision, reason
    if isinstance(handoff, str) and handoff.strip():
        return "allow", "worker_handed_off"
    return "block", "worker_no_handoff"


def worker_backstop(thread_dir: pathlib.Path, decision: str, reason: str) -> tuple[str, str]:
    """Count a worker's consecutive identical blocks; past the cap, allow."""
    path = thread_dir / "worker_stop_blocks.json"
    if decision != "block":
        path.unlink(missing_ok=True)
        return decision, reason
    try:
        prior = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        prior = {}
    count = prior.get("count", 0) + 1 if isinstance(prior, dict) and prior.get("reason") == reason else 1
    if count > WORKER_BACKSTOP_BLOCKS:
        path.unlink(missing_ok=True)
        return "allow", "worker_livelock_backstop"
    path.write_text(json.dumps({"reason": reason, "count": count}), encoding="utf-8")
    return decision, reason


def _log_incident(record: dict) -> None:
    """incidents.jsonl for the reconciler, and the same decision in the
    gate-signal corpus half-life review reads (Stop adapters share one)."""
    try:
        root = harness_home() if _CORE_IMPORT_ERROR is None else pathlib.Path(
            os.environ.get("HARNESS_ROOT")
            or os.environ.get("CONTINUATION_HARNESS_HOME")
            or pathlib.Path.home() / ".claude" / "harness"
        )
        root.mkdir(parents=True, exist_ok=True)
        record.setdefault("timestamp", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        record.setdefault("source", "pi_stop_hook")
        with (root / "incidents.jsonl").open("a") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception:  # noqa: BLE001 -- logging must never break the decision
        pass
    if _CORE_IMPORT_ERROR is None:
        record_gate_signal(
            record.get("decision", ""), record.get("reason", ""), record.get("session_id", ""), "pi_stop_hook"
        )


def main() -> int:
    if _CORE_IMPORT_ERROR is not None:
        _log_incident({"decision": "allow", "reason": "core_import_failed", "error": _CORE_IMPORT_ERROR[:200]})
        return 0
    try:
        payload = json.loads(sys.stdin.read())
        if not isinstance(payload, dict):
            raise ValueError("payload is not an object")
    except Exception as exc:  # noqa: BLE001 -- fail-open with signal
        _log_incident({"decision": "allow", "reason": "malformed_payload", "error": str(exc)[:200]})
        return 0

    try:
        # One block per continuation chain: the run this gate already continued
        # may stop, as on Claude and Codex.
        if payload.get("stop_hook_active"):
            return 0
        session_id = payload.get("session_id") or "pi-unknown"
        cwd = payload.get("cwd") if isinstance(payload.get("cwd"), str) else ""
        transcript_path = payload.get("transcript_path")
        thread_dir = thread_dir_for_session(session_id, harness_home())
        thread_dir.mkdir(parents=True, exist_ok=True)
        state = load_thread_state(
            thread_dir,
            recent_user_message=last_user_text(transcript_path),
            transcript_path=transcript_path if isinstance(transcript_path, str) else None,
            cwd=cwd or None,
        )
        decision, reason = would_block_stop(state)
        if decision == "allow" and reason == "conversational":
            if is_completion_claim(payload.get("last_assistant_message")) and git_work_remains(cwd):
                decision, reason = "block", "winddown_claim_work_remains"
        if payload.get("parent_session"):
            decision, reason = worker_scope(decision, reason, payload.get("last_assistant_message"))
            held_for = reason
            decision, reason = worker_backstop(thread_dir, decision, reason)
        record = {
            "decision": decision,
            "reason": reason,
            "session_id": session_id,
            "payload_keys": sorted(payload.keys()),
        }
        if reason == "worker_livelock_backstop":
            record["held_for"] = held_for
        _log_incident(record)
        if decision == "block":
            print(json.dumps({"decision": "block", "reason": resumption(reason, session_id, cwd)}))
        return 0
    except Exception as exc:  # noqa: BLE001 -- fail-open with signal
        _log_incident({"decision": "allow", "reason": "adapter_error", "error": str(exc)[:200]})
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
