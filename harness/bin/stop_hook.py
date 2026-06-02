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
import os
import pathlib
import subprocess
import sys
import time
from typing import Optional, Tuple

_TRANSCRIPT_WINDOW = 25_000  # bytes — same tail size as validate_no_shirking.py

# Self-locate for the sibling import — works whether this script lives in the
# repo source tree or is installed to ~/.claude/harness/bin. No hardcoded path.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from would_block_stop import (  # noqa: E402
    would_block_stop,
    load_thread_state,
    thread_dir_for_session,
    harness_home,
    resolve_watermark,
    _load_json,
    _parse_iso,
)
import datetime as _dt2

# State root is the standard per-user location (env-overridable), NOT relative
# to where this code is installed — so dev-copy and installed-copy share state
# and nothing is written into a repo working tree.
HARNESS_ROOT = harness_home()
INCIDENTS_LOG = HARNESS_ROOT / "incidents.jsonl"

RESUMPTION_PROMPT = (
    "continuation-harness: {reason}. You are NOT done and you are NOT stopping. "
    "Do NOT end your turn to summarize what's left or to ask the user what to do next — "
    "that wind-down is the exact failure this gate exists to prevent. Continue now with the "
    "next concrete in-scope action. The only ways to actually finish this turn: "
    "(1) run `~/.claude/harness/bin/verify` and have it exit 0 "
    "(declare a contract via init_contract.py first if you haven't); "
    "(2) call the ScheduleWakeup tool because you are blocked on an external event. "
    "The user can release you by saying 'stop' — but do not solicit that by halting."
)

# Task-mode-specific display text, keyed by reason code.
# Reason codes are short log-friendly strings; display text carries the guidance.
_TASK_MODE_DISPLAY: dict[str, str] = {
    "tasks_remain_in_queue": (
        "continuation-harness [task-mode]: tasks_remain_in_queue. In-scope work is ready "
        "under this session's goal — keep working it. Do NOT stop to summarize or to ask the "
        "user what to do next; run the next ready task to completion. Stop is allowed only "
        "when the scoped queue is drained, you have called ScheduleWakeup for an external "
        "blocker, or the user has already said 'stop'."
    ),
    "all_remaining_tasks_blocked": (
        "continuation-harness [task-mode]: all_remaining_tasks_blocked. bd ready is empty but "
        "open tasks remain blocked on dependencies. Do NOT stop to ask the user what to do next — "
        "call the ScheduleWakeup tool for when the blockers clear, which both releases this "
        "turn and brings you back to continue. Stop without that only if the user has already "
        "said 'stop'."
    ),
}


def _read_payload() -> dict:
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return {}


def _read_last_user_message(transcript_path: str) -> Optional[str]:
    """Return the most recent user message text from the transcript tail.

    Mirrors the read_recent_messages pattern in validate_no_shirking.py so that
    _user_released() in would_block_stop actually fires when the user says 'stop'.
    Returns None if transcript_path is empty, unreadable, or has no user turns.
    """
    if not transcript_path:
        return None
    path = pathlib.Path(transcript_path)
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    tail = raw[-_TRANSCRIPT_WINDOW:] if len(raw) > _TRANSCRIPT_WINDOW else raw
    last_user_text: Optional[str] = None
    for line in tail.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = entry.get("message", entry)
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
        content = msg.get("content", [])
        parts: list[str] = []
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for blk in content:
                if isinstance(blk, dict) and blk.get("type") == "text":
                    parts.append(blk.get("text", ""))
                elif isinstance(blk, str):
                    parts.append(blk)
        if parts:
            last_user_text = "\n".join(parts)
    return last_user_text


def _check_task_mode_queue(session_mode: dict, run_bd=None) -> Tuple[str, str]:
    """Run bd ready / bd list in repo_cwd to determine if queue-drain allows stop.

    Returns (decision, reason) where decision is "allow" or "block".

    Capability probe, NOT a directory check. A git worktree has no literal
    `.beads/` directory but `bd` still resolves the shared Dolt DB via the
    redirect file / BEADS_DIR env (see beads-worktree-integration rule). The
    prior implementation short-circuited to ("allow", "task_mode_no_beads_in_cwd")
    whenever `repo_cwd/.beads` was absent — which silently ungated EVERY worktree
    session (2026-06-01 incident: session 75be09cc allowed Stop 8x while a ready
    sibling task remained). We now probe `bd` directly and degrade to allow ONLY
    when bd cannot resolve a queue at all, while still keeping a real beads repo
    (one whose `.beads/` is present) blocked when bd merely hiccups.

    `run_bd` is injectable for testing; in production it defaults to a
    subprocess runner scoped to repo_cwd and the molecule/task parent.
    """
    repo_cwd = session_mode.get("repo_cwd", "")
    # Scope priority: parent_id (molecule root) > task_id (standalone task) > unscoped.
    # parent_id is set when the claimed task has a parent (e.g., a molecule step).
    # task_id is the fallback for standalone/leaf tasks: bd ready --parent <leaf-id>
    # returns [] since leaf tasks have no children, so the gate allows Stop once
    # the leaf task is closed — which is correct. Without scoping, bd ready returns
    # the entire repo backlog, causing derailment into unrelated tasks.
    parent_id = session_mode.get("parent_id") or session_mode.get("task_id")

    if not repo_cwd:
        return ("block", "task_mode_no_cwd")

    # A real beads repo announces itself with a `.beads/` dir; a worktree does
    # not (it uses a redirect / BEADS_DIR). We use this ONLY to decide how to
    # degrade when bd is unavailable — never to skip the queue check.
    has_beads_dir = (pathlib.Path(repo_cwd) / ".beads").exists()

    if run_bd is None:
        import json as _json

        def run_bd(args: list[str]) -> Optional[list]:
            """Run bd with --json output; returns parsed list or None on failure."""
            cmd = ["bd"] + args + ["--json"] + (["--parent", parent_id] if parent_id else [])
            try:
                r = subprocess.run(cmd, cwd=repo_cwd, capture_output=True, text=True, timeout=15)
                return _json.loads(r.stdout)
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError,
                    _json.JSONDecodeError, ValueError):
                return None

    ready = run_bd(["ready"])
    if ready is None:
        # bd produced no parseable queue. Inside a real beads repo this is a
        # transient error — stay blocked so the agent can't sneak out. Outside
        # one (no .beads/ dir AND bd can't resolve a DB), it's genuinely not a
        # beads context — degrade gracefully so the gate never permanently traps.
        if has_beads_dir:
            return ("block", "task_mode_bd_ready_failed")
        return ("allow", "task_mode_bd_unavailable")
    if len(ready) > 0:
        return ("block", "tasks_remain_in_queue")

    # bd ready empty: distinguish "all done" from "all remaining tasks blocked".
    open_items = run_bd(["list"])
    if open_items is None:
        if has_beads_dir:
            return ("block", "task_mode_bd_list_failed")
        return ("allow", "task_mode_bd_unavailable")
    if len(open_items) > 0:
        return ("block", "all_remaining_tasks_blocked")

    return ("allow", "queue_drained")


_IMPLICIT_QUEUE_DISPLAY = (
    "continuation-harness: your contract verify passed, but bd still has unfinished work in "
    "this repo. If any of it is in this session's scope, keep going — do NOT stop to summarize "
    "or to ask the user what to do next. If the only open work is unrelated backlog from other "
    "sessions, do not drain it (that is scope creep): instead close out your own claimed tasks, "
    "or call ScheduleWakeup if you are waiting on something external. "
    "Hint: `bd list --status=in_progress` shows what is still claimed."
)


def _created_at_in_scope(item: dict, watermark: "_dt2.datetime") -> bool:
    """True if `item` is session-fresh (created_at >= watermark).

    FAIL-SAFE: a missing/unparseable created_at returns True (treat as in-scope)
    so an item of unknown age biases toward BLOCK, never toward a premature stop.
    """
    if not isinstance(item, dict):
        return True
    ca = _parse_iso(item.get("created_at", ""))
    if ca is None:
        return True
    if ca.tzinfo is None:
        ca = ca.replace(tzinfo=_dt2.timezone.utc)
    wm = watermark if watermark.tzinfo else watermark.replace(tzinfo=_dt2.timezone.utc)
    return ca >= wm


def _check_bd_queue_implicit(
    cwd: str,
    thread_dir=None,
    run_bd=None,
    watermark=None,
) -> Tuple[str, str]:
    """Watermark-scoped implicit Stop-path (beads 858.2 + 858.4).

    Blocks only on SESSION-FRESH bd work (created_at >= watermark); older backlog
    is treated as not-this-session's and does NOT block (fixes the a2n over-block).
    The query set is {in_progress ∪ ready ∪ open} — dropping `open` re-opens FN-4
    (a session-fresh bead blocked on unmet deps is in neither ready nor in_progress).

    Capability probe (858.4, fixes E-1): no `.beads/`-directory check — a worktree
    has no dir but bd resolves via redirect/BEADS_DIR; degrade to advisory-allow only
    when bd genuinely cannot resolve a queue. `watermark` absent ⇒ advisory-allow
    (never a hard block on unscoped backlog, never now()). `run_bd`/`watermark`
    injectable for tests.
    """
    if not cwd:
        return ("allow", "implicit_queue_no_cwd")

    if watermark is None and thread_dir is not None:
        watermark = resolve_watermark(pathlib.Path(thread_dir))

    if run_bd is None:
        import json as _json

        def run_bd(args: list[str]) -> Optional[list]:
            try:
                r = subprocess.run(
                    ["bd"] + args + ["--json"],
                    cwd=cwd, capture_output=True, text=True, timeout=15,
                )
                return _json.loads(r.stdout)
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError,
                    _json.JSONDecodeError, ValueError):
                return None

    # No watermark (session predating this feature) ⇒ cannot scope ⇒ advisory allow.
    if watermark is None:
        return ("allow", "scope_no_watermark")

    # {in_progress ∪ ready ∪ open}, capability-probe: degrade on bd FAILURE only.
    in_progress = run_bd(["list", "--status=in_progress"])
    ready = run_bd(["ready"])
    open_items = run_bd(["list", "--status=open"])
    if in_progress is None or ready is None or open_items is None:
        return ("allow", "scope_bd_failed")

    seen: dict = {}
    for it in list(in_progress) + list(ready) + list(open_items):
        if isinstance(it, dict):
            seen[it.get("id") or id(it)] = it
    if any(_created_at_in_scope(it, watermark) for it in seen.values()):
        return ("block", "implicit_queue_scoped")
    return ("allow", "implicit_queue_scoped_drained")


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
    transcript_path = payload.get("transcript_path", "")

    thread_dir = thread_dir_for_session(session_id, HARNESS_ROOT)
    thread_dir.mkdir(parents=True, exist_ok=True)

    # B1 fix: read last user message from transcript so _user_released() fires.
    recent_user_message = _read_last_user_message(transcript_path)

    # Task mode: queue-drain is the session-scope stopping criterion.
    # User release and wakeup remain universal overrides (checked via would_block_stop
    # with contract=None, which short-circuits to the universal paths before contract check).
    session_mode = _load_json(thread_dir / "session_mode.json")
    if isinstance(session_mode, dict) and session_mode.get("mode") == "task":
        scheduled = _load_json(thread_dir / "scheduled.json")
        override_state = {
            "contract": None,
            "scheduled": scheduled,
            "recent_user_message": recent_user_message,
        }
        override_decision, override_reason = would_block_stop(override_state)
        if override_decision == "allow":
            # user_released or wakeup_registered — universal overrides apply in task mode too.
            _log_incident({
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "session_id": session_id,
                "decision": override_decision,
                "reason": override_reason,
                "was_correct": None,
                "notes": "task_mode_universal_override",
            })
            return 0
        decision, reason = _check_task_mode_queue(session_mode)
        _log_incident({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "session_id": session_id,
            "decision": decision,
            "reason": reason,
            "was_correct": None,
            "notes": "task_mode",
        })
        if decision == "block":
            display = _TASK_MODE_DISPLAY.get(reason) or RESUMPTION_PROMPT.format(reason=reason)
            print(json.dumps({"decision": "block", "reason": display}))
        return 0

    # No task mode: contract gate.
    # Per continuation-harness spec, the three Stop-permission paths are universal:
    # verification_passed, wakeup_registered, user_released. Sessions that never
    # declared a contract reach those checks via would_block_stop and fall through
    # to ("block", "no_contract") iff none of the three holds. The prior B2 carve-out
    # (no contract.json → silent allow) was an unspec'd inversion of that invariant
    # and made the gate's coverage proportional to whether the agent remembered to
    # call init_contract.py — a presence-only check the gate-design rule forbids.
    state = load_thread_state(thread_dir, recent_user_message=recent_user_message)
    decision, reason = would_block_stop(state)

    # B3 fix: after verification_passed, check bd queue in cwd.
    # Catches sessions where task-mode was not entered via the PreToolUse hook
    # (e.g., bd claims made inside subagents) but bd work is still in-flight.
    # Universal overrides (user_released, wakeup_registered) bypass this check.
    if decision == "allow" and reason == "verification_passed":
        try:
            cwd = os.getcwd()
        except OSError:
            cwd = ""
        bd_decision, bd_reason = _check_bd_queue_implicit(cwd, thread_dir=thread_dir)
        if bd_decision == "block":
            decision, reason = bd_decision, bd_reason

    _log_incident({
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "session_id": session_id,
        "decision": decision,
        "reason": reason,
        "was_correct": None,
        "notes": "implicit_queue_check" if reason.startswith("implicit_queue_") else "",
    })

    if decision == "block":
        display = (
            _IMPLICIT_QUEUE_DISPLAY
            if reason.startswith("implicit_queue_")
            else RESUMPTION_PROMPT.format(reason=reason)
        )
        out = {"decision": "block", "reason": display}
        print(json.dumps(out))
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
