#!/usr/bin/env python3
"""UserPromptSubmit hook: tell the model the current local time on every prompt.

Models otherwise only know the session-start date. One compact line, e.g.
`now: Thu 2026-10-08 00:33 PDT (UTC-0700)`, carries weekday, date, minute,
zone abbreviation and numeric offset, so the model can convert to/from UTC.

Sent as `hookSpecificOutput.additionalContext` only: that is the key every host
passes to the model, and a top-level `systemMessage` would show as UI noise on
every turn. The prompt payload is ignored, so unreadable stdin still gets the
time. Fires every prompt by design (no per-session flag): the time goes stale.
"""

import json
import sys
import time


def main() -> int:
    try:
        sys.stdin.read()
    except Exception:
        pass
    line = time.strftime("now: %a %Y-%m-%d %H:%M %Z (UTC%z)", time.localtime())
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": line,
    }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
