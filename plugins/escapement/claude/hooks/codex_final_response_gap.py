#!/usr/bin/env python3
"""SessionStart advisory for Codex's missing final-response Stop hook."""

from __future__ import annotations

import json
import sys

_SYSTEM_MESSAGE = (
    "Escapement Codex: no Stop/final-response hook is available here; final-answer "
    "wind-down cannot be mechanically blocked the way Claude Stop hooks can."
)

_ADDITIONAL_CONTEXT = (
    "Escapement Codex adapter notice: Codex currently exposes no Stop/final-response "
    "hook. Escapement can gate supported lifecycle events such as SessionStart, "
    "PreCompact, and PreToolUse, but it cannot mechanically intercept a final answer "
    "that offers to stop while reversible work remains. Continue from explicit bd, "
    "git, OpenSpec, and outcome-verification state before final responses; do not "
    "treat a summary of follow-ups as completion."
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
