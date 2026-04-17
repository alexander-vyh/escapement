#!/usr/bin/env python3
"""Claude Code hook: enforce discovery (design doc) before feature/epic creation.

Fires as PreToolUse on Bash commands containing `bd create`.

For features and epics, requires a design doc in docs/plans/ with:
  - ## Problem Statement
  - ## Non-Goals
  - ## Riskiest Assumption

Bugs and chores are always allowed. Standalone tasks trigger an "ask" prompt.

Input (via stdin):
  JSON with hook_event_name, tool_name, tool_input
Exit codes:
  0 — allow or ask
  2 — deny (JSON output explains why)
"""

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import NoReturn


# ---------------------------------------------------------------------------
# Type parsing
# ---------------------------------------------------------------------------

def parse_type_flag(command: str) -> str | None:
    """Extract the story type from a bd create command.

    Handles: -t feature, --type feature, --type=feature
    Returns None if no type flag is present.
    """
    # --type=value
    m = re.search(r'--type[=](\S+)', command)
    if m:
        return m.group(1).lower()

    # --type value or -t value
    m = re.search(r'(?:--type|-t)\s+(\S+)', command)
    if m:
        val = m.group(1).lower()
        # Guard against capturing another flag as the value
        if not val.startswith('-'):
            return val

    return None


def has_parent_flag(command: str) -> bool:
    """Check if the command has a --parent flag."""
    return bool(re.search(r'--parent\b', command))


# ---------------------------------------------------------------------------
# Design doc validation
# ---------------------------------------------------------------------------

REQUIRED_SECTIONS = [
    "## Problem Statement",
    "## Non-Goals",
    "## Riskiest Assumption",
]

THIRTY_DAYS = 30 * 24 * 60 * 60


def find_recent_design_docs(plans_dir: Path) -> list[Path]:
    """Return *.md files in plans_dir modified within the last 30 days."""
    if not plans_dir.is_dir():
        return []

    cutoff = time.time() - THIRTY_DAYS
    docs = []
    for f in plans_dir.glob("*.md"):
        if f.is_file() and f.stat().st_mtime >= cutoff:
            docs.append(f)
    return docs


def check_design_doc_sections(doc: Path) -> list[str]:
    """Return list of missing required sections in the doc."""
    try:
        content = doc.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return list(REQUIRED_SECTIONS)

    missing = []
    for section in REQUIRED_SECTIONS:
        if section not in content:
            missing.append(section)
    return missing


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def allow() -> int:
    """Allow the action (exit 0, no output needed)."""
    return 0


def ask(hook_event: str, message: str) -> int:
    """Prompt the user for confirmation (exit 0 with ask decision)."""
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": hook_event,
            "permissionDecision": "ask",
            "permissionDecisionReason": message,
        }
    }))
    return 0


def deny(hook_event: str, message: str) -> NoReturn:
    """Deny the action (exit 2)."""
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": hook_event,
            "permissionDecision": "deny",
            "permissionDecisionReason": message,
        }
    }))
    sys.exit(2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    hook_event = data.get("hook_event_name", "") or data.get("hookEventName", "")
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""

    # Only fire on PreToolUse for Bash commands containing "bd create"
    if hook_event != "PreToolUse":
        return 0
    if tool_name != "Bash":
        return 0
    if "bd create" not in command:
        return 0

    # Parse the story type
    story_type = parse_type_flag(command)

    # Bugs and chores always pass
    if story_type in ("bug", "chore"):
        return allow()

    # Features and epics require a design doc
    if story_type in ("feature", "epic"):
        # Determine the project directory from the hook payload.
        # Claude Code passes the working directory as "cwd" in the hook JSON.
        # Fall back to os.getcwd() as a last resort.
        project_dir = data.get("cwd", "") or data.get("workingDirectory", "") or os.getcwd()
        plans_dir = Path(project_dir) / "docs" / "plans"
        docs = find_recent_design_docs(plans_dir)

        if not docs:
            deny(hook_event, "No design doc found. Run /discovery first.")

        # Check the best doc (most recently modified) for required sections
        docs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        best_doc = docs[0]
        missing = check_design_doc_sections(best_doc)

        if not missing:
            return allow()

        # Some sections missing — ask, listing what's missing
        missing_list = ", ".join(missing)
        return ask(
            hook_event,
            f"Design doc '{best_doc.name}' is missing required sections: "
            f"{missing_list}. Add them or say 'proceed' to continue anyway.",
        )

    # Task (explicit or default when no -t flag) without --parent → ask
    if story_type == "task" or story_type is None:
        if not has_parent_flag(command):
            return ask(
                hook_event,
                "Is this new feature work? Run /discovery first, or say 'proceed'.",
            )
        # Task with --parent is fine (subtask of existing work)
        return allow()

    # Unknown type — allow
    return allow()


if __name__ == "__main__":
    sys.exit(main())
