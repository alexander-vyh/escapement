#!/usr/bin/env python3
"""Claude Code hook: nudge toward discovery when a prompt looks like new feature work.

Fires on UserPromptSubmit. If the prompt contains implementation-intent keywords
and no recent design doc exists in docs/plans/ or openspec/changes/, emits an "ask"
nudge suggesting the user run /discovery first. This is advisory — the user can
always proceed.

Input (via stdin):
  JSON with hook_event_name, session_id, user_prompt, transcript_path
Exit codes:
  0 — allow or ask (never blocks)
"""

import json
import os
import re
import sys
import time
from pathlib import Path


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

THIRTY_DAYS = 30 * 24 * 60 * 60

# Phrases that indicate the prompt is about build tooling, not new features
BUILD_NOISE = [
    "build error",
    "build failed",
    "build failure",
    "build system",
    "build issue",
    "build broke",
    "build broken",
    "npm build",
    "swift build",
    "go build",
    "cargo build",
    "gradle build",
    "maven build",
    "docker build",
    "make build",
    "cmake build",
]

# Implementation-intent patterns (compiled once)
INTENT_PATTERNS = [
    re.compile(r'\bbuild\b', re.IGNORECASE),
    re.compile(r'\bimplement\b', re.IGNORECASE),
    re.compile(r'\badd\s+feature\b', re.IGNORECASE),
    re.compile(r'\bcreate\s+new\b', re.IGNORECASE),
    re.compile(r'\badd\s+new\b', re.IGNORECASE),
    re.compile(r'\bnew\s+feature\b', re.IGNORECASE),
]


# ---------------------------------------------------------------------------
# Design doc check (reuses logic from discovery-gate.py)
# ---------------------------------------------------------------------------

def has_recent_design_doc(plans_dir: Path) -> bool:
    """Return True if any *.md file in plans_dir was modified in the last 30 days."""
    if not plans_dir.is_dir():
        return False

    cutoff = time.time() - THIRTY_DAYS
    for f in plans_dir.glob("*.md"):
        if f.is_file() and f.stat().st_mtime >= cutoff:
            return True
    return False


def has_recent_openspec_design(openspec_dir: Path) -> bool:
    """Return True if any design.md in openspec/changes/*/design.md was modified in the last 30 days."""
    if not openspec_dir.is_dir():
        return False

    cutoff = time.time() - THIRTY_DAYS
    for f in openspec_dir.glob("*/design.md"):
        if f.is_file() and f.stat().st_mtime >= cutoff:
            return True
    return False


# ---------------------------------------------------------------------------
# Intent detection
# ---------------------------------------------------------------------------

def looks_like_new_work(prompt: str) -> bool:
    """Return True if the prompt appears to describe new feature implementation."""
    # Too short to be describing new work
    if len(prompt.strip()) < 10:
        return False

    lower = prompt.lower()

    # Check for build-tooling noise — if present, "build" is about the build system
    for noise in BUILD_NOISE:
        if noise in lower:
            return False

    # Check for implementation-intent keywords
    for pattern in INTENT_PATTERNS:
        if pattern.search(prompt):
            return True

    return False


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def allow() -> int:
    """Allow silently."""
    return 0


def ask(hook_event: str, message: str) -> int:
    """Prompt the user for confirmation (nudge)."""
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": hook_event,
            "permissionDecision": "ask",
            "permissionDecisionReason": message,
        }
    }))
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    hook_event = data.get("hook_event_name", "") or data.get("hookEventName", "")
    if hook_event != "UserPromptSubmit":
        return 0

    prompt = data.get("user_prompt", "") or data.get("tool_input", {}).get("prompt", "")
    if not prompt:
        return 0

    # If the prompt doesn't look like new feature work, allow silently
    if not looks_like_new_work(prompt):
        return allow()

    # Determine the project directory from the hook payload.
    # Claude Code passes the working directory as "cwd" in the hook JSON.
    # Fall back to os.getcwd() as a last resort.
    cwd = Path(data.get("cwd", "") or data.get("workingDirectory", "") or os.getcwd())
    plans_dir = cwd / "docs" / "plans"
    openspec_dir = cwd / "openspec" / "changes"
    if has_recent_design_doc(plans_dir) or has_recent_openspec_design(openspec_dir):
        return allow()

    # No design doc and prompt looks like new work — nudge
    return ask(
        hook_event,
        "I don't see a design doc for this. Is this exploratory, a fix, or "
        "new work? If new work, run /discovery first.",
    )


if __name__ == "__main__":
    sys.exit(main())
