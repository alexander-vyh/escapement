#!/usr/bin/env python3
"""UserPromptSubmit hook: nudge toward discovery when a prompt looks like new feature work.

Fires on UserPromptSubmit (Claude Code, Codex; Pi runs it at before_agent_start).
If the prompt contains implementation-intent keywords and no recent design doc
exists in docs/plans/ or openspec/changes/, it adds a nudge to the turn's
context suggesting discovery first. Advisory — the prompt always proceeds.

Every host sends the prompt as the top-level `prompt` field and reads added
context from `hookSpecificOutput.additionalContext`. This hook used to read
`user_prompt` and answer with a PreToolUse-only `permissionDecision`, so it
never fired anywhere.

Input (via stdin):
  JSON with hook_event_name, prompt, cwd
Exit codes:
  0 — always (never blocks)
"""

import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _host_output  # noqa: E402


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


NUDGE_MESSAGE = (
    "No design doc from the last 30 days in docs/plans/ or openspec/changes/. "
    "If this prompt is new feature work rather than a fix or exploration, run "
    "/discovery (the discovery skill) before implementing."
)


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

    prompt = data.get("prompt")
    if not isinstance(prompt, str) or not prompt:
        return 0

    # If the prompt doesn't look like new feature work, stay silent
    if not looks_like_new_work(prompt):
        return 0

    # The project directory is the payload's `cwd` on every host.
    # Fall back to os.getcwd() as a last resort.
    cwd = Path(data.get("cwd", "") or data.get("workingDirectory", "") or os.getcwd())
    plans_dir = cwd / "docs" / "plans"
    openspec_dir = cwd / "openspec" / "changes"
    if has_recent_design_doc(plans_dir) or has_recent_openspec_design(openspec_dir):
        return 0

    # No design doc and prompt looks like new work — nudge
    print(json.dumps(_host_output.advisory(NUDGE_MESSAGE, "UserPromptSubmit")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
