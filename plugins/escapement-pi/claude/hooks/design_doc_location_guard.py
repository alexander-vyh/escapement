#!/usr/bin/env python3
"""PostToolUse hook: warn when writing design docs to docs/plans/ directly.

Fires as PostToolUse on Write and Edit (Claude Code; Pi maps its write/edit onto
them) and on apply_patch (Codex, where every file the patch adds, updates or
moves to is checked).

Advisory only — never blocks. Emits a warning when a target file path
matches docs/plans/*design* to nudge toward using openspec/changes/ instead.
The warning is written for the agent, so it goes out as
`hookSpecificOutput.additionalContext` -- the channel Claude Code, Codex and
the Pi extension all hand to the model after a tool call -- with the same text
as `systemMessage` for the user. It used to go to stderr, which on an exit-0
PostToolUse reaches neither.

Fast-path exits:
  - Non-PostToolUse events
  - Tools that do not write files
  - File paths not matching docs/plans/*design*

Fail-open: any error silently allows.

Input (via stdin):
  JSON with hook_event_name, tool_name, tool_input (and cwd for apply_patch)
Exit codes:
  0 — always (advisory only)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _host_output  # noqa: E402

try:
    from _codex_patch import payload_targets as _patch_targets
except ImportError:  # pragma: no cover - fail open: an unread patch warns about nothing
    def _patch_targets(*_args, **_kwargs):
        return None


# ---------------------------------------------------------------------------
# Path matching
# ---------------------------------------------------------------------------

# Match paths containing docs/plans/ with "design" somewhere in the filename
_DESIGN_DOC_PATTERN = re.compile(
    r'(?:^|/)docs/plans/.*design', re.IGNORECASE
)

MESSAGE = (
    "You're writing a design doc to docs/plans/. Consider whether this "
    "content should live in openspec/changes/ instead, which provides "
    "structured spec management, validation, and archiving. "
    "This is advisory — the write was not blocked."
)


def is_design_doc_path(file_path: str) -> bool:
    """Return True if the path looks like a design doc in docs/plans/."""
    return bool(_DESIGN_DOC_PATTERN.search(file_path))


def written_paths(data: dict) -> list[str]:
    """Every file the finished tool call wrote, whichever host's edit tool."""
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    if not isinstance(tool_input, dict):
        return []
    if tool_name in ("Write", "Edit"):
        file_path = tool_input.get("file_path", "")
        return [file_path] if file_path else []
    if tool_name == "apply_patch":
        found = _patch_targets(tool_input, str(data.get("cwd") or "")) or []
        return [path for kind, path in found if kind != "Delete"]
    return []


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

    if not any(is_design_doc_path(path) for path in written_paths(data)):
        return 0

    print(json.dumps(_host_output.advisory(MESSAGE, "PostToolUse")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
