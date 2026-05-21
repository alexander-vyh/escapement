#!/usr/bin/env python3
"""
continuation-harness Stop gate.

Pure function that decides whether a Claude Code (or other agent CLI) session
may stop, based on observable filesystem state. No prose pattern matching.
No LLM judgment. State-only.

Decision rules:
  ("allow", "verification_passed")  -- contract.last_run.exit_code == expected_exit AND timestamp within current turn
  ("allow", "wakeup_registered")    -- scheduled.json has at least one future-dated entry
  ("allow", "user_released")        -- recent user message matches explicit-stop set
  ("block", "no_completion_or_resumption_proof") -- none of the above; contract exists
  ("block", "no_contract")          -- no contract.json AND no wakeup AND no user release
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import re
import sys
from typing import Optional, Tuple

# State root: where contracts / wakeups / incidents live. Standard per-user
# location, independent of where the harness CODE is installed or invoked from,
# so concurrent sessions in any repo share one state dir and NOTHING is ever
# written into a project working tree. Override with CONTINUATION_HARNESS_HOME
# (or legacy HARNESS_ROOT). NO author-specific / repo-specific path is baked in.
DEFAULT_HARNESS_ROOT = pathlib.Path(
    os.environ.get(
        "CONTINUATION_HARNESS_HOME",
        pathlib.Path.home() / ".claude" / "harness",
    )
)


def harness_home() -> pathlib.Path:
    """The state root (env-overridable). Single source of truth for all tools."""
    return pathlib.Path(os.environ.get("HARNESS_ROOT", DEFAULT_HARNESS_ROOT))

EXPLICIT_STOP_SET = frozenset({
    "stop",
    "stop here",
    "end here",
    "that's enough",
    "thats enough",
    "done for now",
    "we're done",
    "were done",
    "okay stop",
    "ok stop",
    "halt",
})

# "Current turn" window. last_run older than this is treated as stale so an
# old passing run can't be reused indefinitely. 5 minutes is the default —
# long enough for legitimate verification runs, short enough that a passing
# run from yesterday doesn't unlock today's Stop.
CURRENT_TURN_WINDOW_SECONDS = 300


def _now() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def _parse_iso(s: str) -> Optional[_dt.datetime]:
    if not isinstance(s, str):
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return _dt.datetime.fromisoformat(s)
    except (ValueError, AttributeError):
        return None


def _load_json(path: pathlib.Path):
    if not path.exists():
        return None
    try:
        with path.open() as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def _verification_passed_this_turn(contract: Optional[dict]) -> bool:
    if not isinstance(contract, dict):
        return False
    last = contract.get("last_run")
    if not isinstance(last, dict):
        return False
    if last.get("exit_code") != contract.get("expected_exit", 0):
        return False
    ts = _parse_iso(last.get("timestamp", ""))
    if ts is None:
        return False
    age = (_now() - ts).total_seconds()
    return 0 <= age <= CURRENT_TURN_WINDOW_SECONDS


def _wakeup_registered(scheduled: Optional[list]) -> bool:
    if not isinstance(scheduled, list):
        return False
    now = _now()
    for entry in scheduled:
        if not isinstance(entry, dict):
            continue
        wake_at = _parse_iso(entry.get("wake_at", ""))
        if wake_at is not None and wake_at > now:
            return True
    return False


def _user_released(recent_user_message: Optional[str]) -> bool:
    if not isinstance(recent_user_message, str):
        return False
    normalized = recent_user_message.strip().lower().rstrip(".!?")
    return normalized in EXPLICIT_STOP_SET


def would_block_stop(thread_state: dict) -> Tuple[str, str]:
    """
    Decide whether a Stop event for this thread should be blocked.

    thread_state keys:
      contract:               dict | None    (parsed contract.json)
      scheduled:              list | None    (parsed scheduled.json — an array)
      recent_user_message:    str  | None    (most recent user message text)

    Returns (decision, reason) where decision is "allow" or "block".
    """
    contract = thread_state.get("contract")
    scheduled = thread_state.get("scheduled")
    recent_user_message = thread_state.get("recent_user_message")

    if _verification_passed_this_turn(contract):
        return ("allow", "verification_passed")
    if _wakeup_registered(scheduled):
        return ("allow", "wakeup_registered")
    if _user_released(recent_user_message):
        return ("allow", "user_released")
    if not isinstance(contract, dict):
        return ("block", "no_contract")
    return ("block", "no_completion_or_resumption_proof")


def sanitize_session_id(session_id: Optional[str]) -> str:
    """Reduce a session id to a safe single path component.

    Keeps only alphanumerics, dash, underscore; caps length. A malformed or
    malicious session id can never escape the threads/ directory because the
    result contains no '/', '..', or other path metacharacters.
    """
    if not session_id or not isinstance(session_id, str):
        return ""
    return re.sub(r"[^A-Za-z0-9_-]", "", session_id)[:128]


def thread_dir_for_session(
    session_id: Optional[str],
    harness_root: Optional[pathlib.Path] = None,
) -> pathlib.Path:
    """Resolve the per-session thread directory.

    Pure function of (HARNESS_THREAD_DIR override, session_id, HARNESS_ROOT).
    Keyed by session_id so concurrent sessions / named subagents working the
    same repo do not collide on a shared contract. Resolution priority:

      1. HARNESS_THREAD_DIR env override (explicit; for tests / special cases)
      2. sanitized session_id  -> {harness_root}/threads/{session_id}
      3. fallback              -> {harness_root}/threads/current
    """
    override = os.environ.get("HARNESS_THREAD_DIR")
    if override:
        return pathlib.Path(override)
    if harness_root is None:
        harness_root = pathlib.Path(
            os.environ.get("HARNESS_ROOT", DEFAULT_HARNESS_ROOT)
        )
    sid = sanitize_session_id(session_id)
    if sid:
        return harness_root / "threads" / sid
    return harness_root / "threads" / "current"


def load_thread_state(
    thread_dir: pathlib.Path,
    recent_user_message: Optional[str] = None,
) -> dict:
    """Load thread state from filesystem. Convenience for Stop-hook adapter."""
    return {
        "contract": _load_json(thread_dir / "contract.json"),
        "scheduled": _load_json(thread_dir / "scheduled.json"),
        "recent_user_message": recent_user_message,
    }


def _cli_main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(
            "usage: would_block_stop.py <thread_dir> [recent_user_message]",
            file=sys.stderr,
        )
        return 2
    thread_dir = pathlib.Path(argv[1])
    recent = argv[2] if len(argv) > 2 else None
    state = load_thread_state(thread_dir, recent)
    decision, reason = would_block_stop(state)
    print(json.dumps({"decision": decision, "reason": reason}))
    return 0


if __name__ == "__main__":
    sys.exit(_cli_main(sys.argv))
