#!/usr/bin/env python3
"""Claude Code hook: warn when writing design docs to docs/plans/ directly.

Fires as PostToolUse on Write and Edit tools.

Advisory only — never blocks. Emits a warning when the target file path
matches docs/plans/*design* to nudge toward using openspec/changes/ instead.

Fast-path exits:
  - Non-PostToolUse events
  - Non-Write/Edit tools
  - File paths not matching docs/plans/*design*

Fail-open: any error silently allows.

Input (via stdin):
  JSON with hook_event_name, tool_name, tool_input
Exit codes:
  0 — always (advisory only)
"""

import json
import re
import sys


# ---------------------------------------------------------------------------
# Path matching
# ---------------------------------------------------------------------------

# Match paths containing docs/plans/ with "design" somewhere in the filename
_DESIGN_DOC_PATTERN = re.compile(
    r'(?:^|/)docs/plans/.*design', re.IGNORECASE
)


def is_design_doc_path(file_path: str) -> bool:
    """Return True if the path looks like a design doc in docs/plans/."""
    return bool(_DESIGN_DOC_PATTERN.search(file_path))


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def allow_silent() -> int:
    """Allow silently — no output."""
    return 0


def warn(message: str) -> int:
    """Emit an advisory warning to stderr (does not block).

    PostToolUse hooks surface stderr output as warnings to the user.
    stdout JSON with hookSpecificOutput is only parsed for PreToolUse.
    """
    print(message, file=sys.stderr)
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # Fail-open

    hook_event = data.get("hook_event_name", "") or data.get("hookEventName", "")
    if hook_event != "PostToolUse":
        return 0

    tool_name = data.get("tool_name", "")
    if tool_name not in ("Write", "Edit"):
        return 0

    tool_input = data.get("tool_input", {})
    if not isinstance(tool_input, dict):
        return 0

    file_path = tool_input.get("file_path", "")
    if not file_path:
        return 0

    # Fast-path: not a design doc path
    if not is_design_doc_path(file_path):
        return allow_silent()

    return warn(
        "You're writing a design doc to docs/plans/. Consider whether this "
        "content should live in openspec/changes/ instead, which provides "
        "structured spec management, validation, and archiving. "
        "This is advisory — the write was not blocked."
    )


if __name__ == "__main__":
    sys.exit(main())
