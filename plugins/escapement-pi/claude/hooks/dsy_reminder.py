#!/usr/bin/env python3
"""UserPromptSubmit hook (Claude, Codex, Pi): remind the model of the design
principles agents tend to drop, on every prompt.

Agents overbuild; the user used to retype this reminder by hand. It rides every
prompt (not once per session) because only per-prompt injection survives
context compaction. It goes through additionalContext, the one channel all
three hosts hand to the model, and never through systemMessage, which would
show as UI noise on every prompt.

Independent of stdin and of the working directory by design: nothing here can
make the reminder go missing.

Exit codes:
  0 — always; emits additionalContext JSON
"""

from __future__ import annotations

import json
import sys

REMINDER = "DRY. SOLID. YAGNI."


def main() -> int:
    try:
        sys.stdin.read()
    except (OSError, ValueError):
        pass
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": REMINDER,
        },
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
