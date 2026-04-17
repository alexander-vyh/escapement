#!/usr/bin/env python3
"""Claude Code hook: nudge on bd close to verify proof of delivery and anti-metrics.

Fires as PreToolUse on Bash commands containing `bd close`.

Searches docs/plans/ for design docs modified in the last 90 days. If found,
extracts proof of delivery and anti-metrics sections and surfaces them as an
"ask" prompt so the agent confirms real-world outcomes before closing.

This is a nudge (ask), never a hard block (deny).

Input (via stdin):
  JSON with hook_event_name, tool_name, tool_input
Exit codes:
  0 — always (nudge or silent allow)
"""

import json
import os
import re
import sys
import time
from pathlib import Path


# ---------------------------------------------------------------------------
# Design doc scanning
# ---------------------------------------------------------------------------

NINETY_DAYS = 90 * 24 * 60 * 60


def find_recent_design_docs(plans_dir: Path) -> list[Path]:
    """Return *.md files in plans_dir modified within the last 90 days."""
    if not plans_dir.is_dir():
        return []

    cutoff = time.time() - NINETY_DAYS
    docs = []
    for f in plans_dir.glob("*.md"):
        if f.is_file() and f.stat().st_mtime >= cutoff:
            docs.append(f)
    return docs


def extract_section_content(content: str, heading: str) -> str | None:
    """Extract text under a ## heading, stopping at the next ## or end of file."""
    pattern = rf"^{re.escape(heading)}\s*\n(.*?)(?=^## |\Z)"
    m = re.search(pattern, content, re.MULTILINE | re.DOTALL)
    if m:
        text = m.group(1).strip()
        return text if text else None
    return None


def find_proof_of_delivery(content: str) -> str | None:
    """Extract the proof of delivery sentence from a design doc."""
    section = extract_section_content(content, "## Proof of Delivery")
    if not section:
        return None
    # Look for the key sentence pattern
    m = re.search(r"I will know this is worth continuing when\s+(.+?)(?:\.|$)", section)
    if m:
        return m.group(0).strip().rstrip(".")
    # Fall back to the full section content (minus markdown formatting)
    lines = [l.strip() for l in section.splitlines() if l.strip() and not l.strip().startswith(">")]
    return " ".join(lines) if lines else section


def find_anti_metrics(content: str) -> str | None:
    """Extract the anti-metrics from a design doc."""
    section = extract_section_content(content, "## Anti-Metrics")
    if not section:
        return None
    # Look for the key sentence pattern
    m = re.search(r"Even if this works perfectly, it has failed if\s+(.+?)(?:\.|$)", section)
    if m:
        return m.group(0).strip().rstrip(".")
    # Fall back to the full section content
    lines = [l.strip() for l in section.splitlines() if l.strip() and not l.strip().startswith(">")]
    return " ".join(lines) if lines else section


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def allow() -> int:
    """Allow the action silently (exit 0, no output)."""
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

    # Only fire on PreToolUse for Bash commands containing "bd close"
    if hook_event != "PreToolUse":
        return 0
    if tool_name != "Bash":
        return 0
    if "bd close" not in command:
        return 0

    # Search for design docs
    # Determine the project directory from the hook payload.
    # Claude Code passes the working directory as "cwd" in the hook JSON.
    # Fall back to os.getcwd() as a last resort.
    project_dir = data.get("cwd", "") or data.get("workingDirectory", "") or os.getcwd()
    plans_dir = Path(project_dir) / "docs" / "plans"
    docs = find_recent_design_docs(plans_dir)

    if not docs:
        return allow()

    # Check the most recently modified doc
    docs.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    proof = None
    anti_metrics = None

    for doc in docs:
        try:
            content = doc.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        if proof is None:
            proof = find_proof_of_delivery(content)
        if anti_metrics is None:
            anti_metrics = find_anti_metrics(content)

        # Stop once we have both
        if proof and anti_metrics:
            break

    # If we found neither, allow silently
    if not proof and not anti_metrics:
        return allow()

    # Build the nudge message
    parts = []
    if proof:
        parts.append(
            f"The proof of delivery says: \"{proof}\"\n"
            "Did you verify this end-to-end? What was the result?"
        )
    if anti_metrics:
        parts.append(
            f"The anti-metrics say: \"{anti_metrics}\"\n"
            "Did any of these occur?"
        )

    message = "\n\n".join(parts)
    return ask(hook_event, message)


if __name__ == "__main__":
    sys.exit(main())
