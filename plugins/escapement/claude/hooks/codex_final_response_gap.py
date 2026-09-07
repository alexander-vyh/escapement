#!/usr/bin/env python3
"""SessionStart advisory for the continuation gaps Codex still has."""

from __future__ import annotations

import json
import sys

_SYSTEM_MESSAGE = (
    "Escapement Codex: final-answer wind-down over reversible work is gated here, but "
    "wakeup scheduling, task-mode binding, and the local judge are not available."
)

_ADDITIONAL_CONTEXT = (
    "Escapement Codex adapter notice: the Stop adapter holds a final answer that winds "
    "down while reversible work remains, so treat a block as the shared decision core "
    "speaking, not a transient error. What Codex still lacks: scheduled wakeups, "
    "task-mode repository binding, and the local judge rung, so nothing here re-enters "
    "a session once it truly ends. Continue from explicit bd, git, OpenSpec, and "
    "outcome-verification state before final responses; do not treat a summary of "
    "follow-ups as completion."
)


def _read_payload() -> dict:
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError, ValueError):
        return {}


def _event_name(payload: dict) -> str:
    event = payload.get("hook_event_name") or payload.get("hookEventName") or ""
    return event if isinstance(event, str) else ""


def main() -> int:
    payload = _read_payload()
    event = _event_name(payload)
    if event and event != "SessionStart":
        return 0

    print(json.dumps({
        "systemMessage": _SYSTEM_MESSAGE,
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": _ADDITIONAL_CONTEXT,
        },
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
