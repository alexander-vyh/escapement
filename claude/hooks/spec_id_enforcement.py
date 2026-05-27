#!/usr/bin/env python3
"""Claude Code hook: enforce --spec-id on bd create under mol-feature molecules.

Fires as PreToolUse on Bash commands containing `bd create`.

When the command has a --parent flag pointing to an issue that belongs to a
mol-feature molecule, this hook blocks if --spec-id is missing.

Fast-path exits:
  - Non-PreToolUse events
  - Non-Bash tools
  - Commands without "bd create"
  - Commands that already have --spec-id
  - Commands without --parent (standalone creates are not gated here)

Fail-open: any error (bd not found, JSON parse, etc.) silently allows.

Input (via stdin):
  JSON with hook_event_name, tool_name, tool_input
Exit codes:
  0 — allow
  2 — deny (JSON output explains why)
"""

import json
import re
import subprocess
import sys
import time
from typing import NoReturn


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Total time budget for all bd show subprocess calls (seconds)
_TOTAL_TIMEOUT = 5.0

# Maximum ancestor hops to walk when checking for mol-feature
_MAX_ANCESTOR_DEPTH = 3

# Per-call subprocess timeout (seconds) — will be clamped by remaining budget
_PER_CALL_TIMEOUT = 2.0


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def parse_flag(command: str, flag: str) -> str | None:
    """Extract the value of a --flag from a command string.

    Handles: --flag=value, --flag value
    Returns None if the flag is not present.
    """
    # --flag=value
    m = re.search(rf'--{re.escape(flag)}[=](\S+)', command)
    if m:
        return m.group(1)

    # --flag value
    m = re.search(rf'--{re.escape(flag)}\s+(\S+)', command)
    if m:
        val = m.group(1)
        if not val.startswith('-'):
            return val

    return None


def has_flag(command: str, flag: str) -> bool:
    """Check if --flag or --flag=... is present."""
    return bool(re.search(rf'--{re.escape(flag)}(?:\s|=|$)', command))


# ---------------------------------------------------------------------------
# Molecule detection
# ---------------------------------------------------------------------------

def _check_issue_for_mol_feature(issue_data: dict) -> bool:
    """Check if a single issue's labels or metadata indicate mol-feature."""
    labels = issue_data.get("labels", [])
    if isinstance(labels, str):
        labels = [labels]

    for label in labels:
        if "mol-feature" in str(label).lower():
            return True

    metadata = issue_data.get("metadata", {})
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except (json.JSONDecodeError, TypeError):
            metadata = {}

    formula = metadata.get("formula", "")
    if "mol-feature" in str(formula).lower():
        return True

    return False


def is_mol_feature_parent(parent_id: str) -> bool:
    """Check if the parent issue belongs to a mol-feature molecule.

    Walks up the issue tree iteratively (up to _MAX_ANCESTOR_DEPTH hops)
    with a shared time budget of _TOTAL_TIMEOUT seconds across all
    subprocess calls.

    Returns False on any error (fail-open).
    """
    deadline = time.monotonic() + _TOTAL_TIMEOUT
    current_id = parent_id
    visited: set[str] = set()

    for _ in range(_MAX_ANCESTOR_DEPTH):
        if not current_id or current_id in visited:
            return False

        visited.add(current_id)

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False  # Time budget exhausted — fail-open

        try:
            result = subprocess.run(
                ["bd", "show", current_id, "--json"],
                capture_output=True,
                text=True,
                timeout=min(_PER_CALL_TIMEOUT, remaining),
            )
            if result.returncode != 0:
                return False

            data = json.loads(result.stdout)

        except Exception:
            return False  # Fail-open

        if _check_issue_for_mol_feature(data):
            return True

        # Walk up to the parent
        current_id = data.get("parent", "")

    return False


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def allow() -> int:
    """Allow the action silently."""
    return 0


def deny(message: str) -> NoReturn:
    """Deny the action with an explanation."""
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
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
    except (json.JSONDecodeError, ValueError):
        return 0  # Fail-open

    hook_event = data.get("hook_event_name", "") or data.get("hookEventName", "")
    if hook_event != "PreToolUse":
        return 0

    tool_name = data.get("tool_name", "")
    if tool_name != "Bash":
        return 0

    tool_input = data.get("tool_input", {})
    command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""

    # Fast-path: not a bd create command
    if "bd create" not in command:
        return 0

    # Fast-path: already has --spec-id
    if has_flag(command, "spec-id"):
        return allow()

    # Only enforce when creating under a parent
    parent_id = parse_flag(command, "parent")
    if not parent_id:
        return allow()

    # Check if the parent belongs to a mol-feature molecule
    if not is_mol_feature_parent(parent_id):
        return allow()

    # Parent is mol-feature and no --spec-id — block
    deny(
        "This bd create is under a mol-feature molecule but is missing --spec-id. "
        "Add --spec-id <spec-identifier> to link this task to its specification. "
        "Example: bd create \"my task\" --parent {parent} "
        "--spec-id openspec/changes/<change-name>/specs/<capability>.md#<requirement-name>"
        .format(parent=parent_id)
    )

    return 0  # unreachable, but keeps type checkers happy


if __name__ == "__main__":
    sys.exit(main())
