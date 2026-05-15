#!/usr/bin/env python3
"""Claude Code hook: nudge on bd close to verify discovery outcomes.

Fires as PreToolUse on Bash commands containing `bd close`.

Finds the most recently touched design — `openspec/changes/{name}/` first
(primary), `docs/plans/` second (legacy fallback) — and surfaces four things as
an "ask" so the agent confirms before closing:
  - proof of delivery        — did you verify the real-world outcome?
  - anti-metrics             — did any failure condition occur?
  - oversized walking skeleton (>3 tasks) — did Phase 1 leak into the skeleton?
  - unresolved [SKELETON-BLOCKING] open questions — the skeleton was designed
                               around a gap

This is a nudge (ask), never a hard block (deny). The skeleton-size and
open-question checks only apply in openspec mode (legacy docs/plans/ predates
those conventions).

Input (via stdin):
  JSON with hook_event_name, tool_name, tool_input, cwd
Exit codes:
  0 — always (nudge or silent allow)
"""

import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional


NINETY_DAYS = 90 * 24 * 60 * 60


# ---------------------------------------------------------------------------
# Locating the design
# ---------------------------------------------------------------------------

def find_recent_openspec_changes(changes_dir: Path) -> list:
    """Return change directories under openspec/changes/ touched in the last 90
    days. Skips the `archive/` directory."""
    if not changes_dir.is_dir():
        return []
    cutoff = time.time() - NINETY_DAYS
    out = []
    for d in changes_dir.iterdir():
        if not d.is_dir() or d.name == "archive":
            continue
        try:
            if d.stat().st_mtime >= cutoff:
                out.append(d)
        except OSError:
            continue
    return out


def find_recent_design_docs(plans_dir: Path) -> list:
    """Return *.md files in docs/plans/ modified within the last 90 days (legacy)."""
    if not plans_dir.is_dir():
        return []
    cutoff = time.time() - NINETY_DAYS
    docs = []
    for f in plans_dir.glob("*.md"):
        try:
            if f.is_file() and f.stat().st_mtime >= cutoff:
                docs.append(f)
        except OSError:
            continue
    return docs


# ---------------------------------------------------------------------------
# Section extraction
# ---------------------------------------------------------------------------

def extract_section_content(content: str, heading: str) -> Optional[str]:
    """Extract text under a ## heading, stopping at the next ## or end of file."""
    pattern = rf"^{re.escape(heading)}\s*\n(.*?)(?=^## |\Z)"
    m = re.search(pattern, content, re.MULTILINE | re.DOTALL)
    if m:
        text = m.group(1).strip()
        return text if text else None
    return None


def find_proof_of_delivery(content: str) -> Optional[str]:
    """Extract the proof of delivery sentence from a design doc."""
    section = extract_section_content(content, "## Proof of Delivery")
    if not section:
        return None
    m = re.search(r"I will know this is worth continuing when\s+(.+?)(?:\.|$)", section)
    if m:
        return m.group(0).strip().rstrip(".")
    lines = [l.strip() for l in section.splitlines()
             if l.strip() and not l.strip().startswith(">")]
    return " ".join(lines) if lines else section


def find_anti_metrics(content: str) -> Optional[str]:
    """Extract the anti-metrics from a design doc."""
    section = extract_section_content(content, "## Anti-Metrics")
    if not section:
        return None
    m = re.search(r"Even if this works perfectly, it has failed if\s+(.+?)(?:\.|$)", section)
    if m:
        return m.group(0).strip().rstrip(".")
    lines = [l.strip() for l in section.splitlines()
             if l.strip() and not l.strip().startswith(">")]
    return " ".join(lines) if lines else section


# ---------------------------------------------------------------------------
# Walking skeleton + open question checks (openspec mode only)
# ---------------------------------------------------------------------------

def count_list_items(text: str) -> int:
    """Count top-level markdown list items (`- `, `* `, `N. `, `- [ ] `).

    Indented sub-items and non-list lines are not counted.
    """
    count = 0
    for line in text.splitlines():
        if re.match(r"^([-*]|\d+\.)\s", line):
            count += 1
    return count


def count_skeleton_tasks(change_dir: str) -> Optional[int]:
    """Count walking-skeleton tasks for an openspec change.

    Prefers tasks.md (feature/epic). Falls back to the `## Walking Skeleton`
    section of design.md (rapid). Returns None when neither is present.
    """
    cd = Path(change_dir)
    tasks_md = cd / "tasks.md"
    if tasks_md.is_file():
        try:
            return count_list_items(tasks_md.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            return None
    design_md = cd / "design.md"
    if design_md.is_file():
        try:
            content = design_md.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        section = extract_section_content(content, "## Walking Skeleton")
        if section:
            return count_list_items(section)
    return None


def find_skeleton_blocking_oqs(content: str) -> list:
    """Return the [SKELETON-BLOCKING] entries in the Open Questions section."""
    section = extract_section_content(content, "## Open Questions")
    if not section:
        return []
    return [line.strip() for line in section.splitlines()
            if "[SKELETON-BLOCKING]" in line]


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

    if hook_event != "PreToolUse":
        return 0
    if tool_name != "Bash":
        return 0
    if "bd close" not in command:
        return 0

    project_dir = data.get("cwd", "") or data.get("workingDirectory", "") or os.getcwd()

    # --- Locate the design: openspec/changes/ first, docs/plans/ as fallback ---
    design_content: Optional[str] = None
    change_dir: Optional[Path] = None

    changes = find_recent_openspec_changes(Path(project_dir) / "openspec" / "changes")
    if changes:
        changes.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        change_dir = changes[0]
        design_md = change_dir / "design.md"
        if design_md.is_file():
            try:
                design_content = design_md.read_text(encoding="utf-8", errors="replace")
            except OSError:
                design_content = None
    else:
        docs = find_recent_design_docs(Path(project_dir) / "docs" / "plans")
        if docs:
            docs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
            for doc in docs:
                try:
                    design_content = doc.read_text(encoding="utf-8", errors="replace")
                    break
                except OSError:
                    continue

    if design_content is None and change_dir is None:
        return allow()

    # --- Run the checks ---
    parts = []

    if design_content:
        proof = find_proof_of_delivery(design_content)
        if proof:
            parts.append(
                f"The proof of delivery says: \"{proof}\"\n"
                "Did you verify this end-to-end? What was the result?"
            )
        anti_metrics = find_anti_metrics(design_content)
        if anti_metrics:
            parts.append(
                f"The anti-metrics say: \"{anti_metrics}\"\n"
                "Did any of these occur?"
            )

    # Skeleton-size and open-question checks are openspec-mode only.
    if change_dir is not None:
        task_count = count_skeleton_tasks(str(change_dir))
        if task_count is not None and task_count > 3:
            parts.append(
                f"The walking skeleton has {task_count} tasks — the rule is 1-3. "
                "Is this still a skeleton, or did Phase 1 leak into it? Re-cut, or "
                "confirm this is intentional."
            )
        if design_content:
            blocking = find_skeleton_blocking_oqs(design_content)
            if blocking:
                listed = "\n".join(f"  {b}" for b in blocking)
                parts.append(
                    f"{len(blocking)} open question(s) marked [SKELETON-BLOCKING] "
                    f"are still unresolved:\n{listed}\n"
                    "The skeleton can't produce a trustworthy signal until these "
                    "are resolved."
                )

    if not parts:
        return allow()

    return ask(hook_event, "\n\n".join(parts))


if __name__ == "__main__":
    sys.exit(main())
