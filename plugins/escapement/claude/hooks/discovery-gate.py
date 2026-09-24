#!/usr/bin/env python3
"""Claude Code hook: enforce discovery (design doc) before feature/epic creation.

Fires as PreToolUse on Bash commands that actually invoke the tracker's
create subcommand -- an argv-shaped match, not a substring of the text.

For features and epics, requires a design doc at
openspec/changes/{name}/design.md (excluding archive/) with:
  - ## Problem Statement
  - ## Non-Goals
  - ## Riskiest Assumption

Bugs and chores are always allowed. Standalone tasks trigger an "ask" prompt.

Input (via stdin):
  JSON with hook_event_name, tool_name, tool_input
Exit codes:
  0 — allow, ask, OR deny. The deny decision is carried by the
      permissionDecision="deny" JSON on stdout (the single-signal contract).
      Exit 2 is the mutually-exclusive legacy stderr path; emitting both is a
      contradictory double-block, so this hook never exits 2.
"""

# PEP 604 annotations below are evaluated when each def executes, so without
# this import the module raises TypeError on import under Python 3.9.
from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import NoReturn

# Shared signal capture per claude/rules/gate-design.md Rule 2.
sys.path.insert(0, str(Path(__file__).parent))
try:
    from _gate_signal import record as _record_signal
except ImportError:  # pragma: no cover
    def _record_signal(*_args, **_kwargs) -> None:
        return None


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


def find_design_docs(openspec_changes_dir: Path) -> list[Path]:
    """Return design.md files under openspec/changes/{name}/, excluding archive."""
    if not openspec_changes_dir.is_dir():
        return []

    docs = []
    for change_dir in openspec_changes_dir.iterdir():
        if not change_dir.is_dir():
            continue
        if change_dir.name == "archive":
            continue
        design = change_dir / "design.md"
        if design.is_file():
            docs.append(design)
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
    """Deny the action via the canonical PreToolUse mechanism.

    CANONICAL DENY CONTRACT: signal the block with a single mechanism — the
    permissionDecision="deny" JSON document on stdout, exit 0. Exit 2 is the
    mutually-exclusive legacy stderr-feedback path; emitting both is a
    contradictory double-block. We use the JSON path, so this exits 0.
    """
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": hook_event,
            "permissionDecision": "deny",
            "permissionDecisionReason": message,
        }
    }))
    sys.exit(0)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

_SEGMENT_SPLIT = re.compile(r"(?:\|\||&&|[;\n|&])")


def _strip_heredoc_bodies(command: str) -> str:
    """Drop heredoc bodies, which are data the shell never executes.

    A commit message describing issue creation is not issue creation. Reading
    the body as command text is what blocked a commit whose message merely
    narrated the defect being fixed.
    """
    lines = command.split("\n")
    out: list[str] = []
    pending: list[str] = []
    skipping: str | None = None
    for line in lines:
        if skipping is not None:
            if line.strip() == skipping:
                skipping = None
            continue
        out.append(line)
        for m in re.finditer(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?", line):
            pending.append(m.group(1))
        if pending:
            skipping = pending.pop(0)
    return "\n".join(out)


def invokes_issue_create(command: str) -> bool:
    """True only when the command actually runs the tracker's create subcommand.

    Substring matching cannot tell discussing a command from running one. It
    fired on a grep whose PATTERN was the command, and on a commit message that
    described it. Both are reads; neither creates anything.

    So: strip heredoc bodies, split on shell separators, and require the binary
    at a command position with `create` as its first word — a quoted argument
    can no longer trigger the gate because it is never token zero.
    """
    for segment in _SEGMENT_SPLIT.split(_strip_heredoc_bodies(command)):
        segment = segment.strip()
        if not segment:
            continue
        try:
            tokens = shlex.split(segment, comments=True)
        except ValueError:
            continue  # unbalanced quotes — not a runnable invocation
        # Skip leading VAR=value assignments and common wrappers.
        idx = 0
        while idx < len(tokens) and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", tokens[idx]):
            idx += 1
        while idx < len(tokens) and tokens[idx] in ("command", "exec", "time", "nohup"):
            idx += 1
        if idx + 1 >= len(tokens):
            continue
        binary = os.path.basename(tokens[idx])
        if binary == "bd" and tokens[idx + 1] == "create":
            return True
    return False


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    hook_event = data.get("hook_event_name", "") or data.get("hookEventName", "")
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""

    # Fire only on a command that actually creates an issue, never on one that
    # merely mentions the words.
    if hook_event != "PreToolUse":
        return 0
    if tool_name != "Bash":
        return 0
    if not invokes_issue_create(command):
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
        openspec_changes_dir = Path(project_dir) / "openspec" / "changes"
        docs = find_design_docs(openspec_changes_dir)

        if not docs:
            _record_signal(
                gate_name="discovery_gate",
                decision="deny",
                reason="no design doc found in openspec/changes/",
                story_type=story_type,
            )
            deny(
                hook_event,
                "No design doc found in openspec/changes/{name}/design.md. "
                "Run /discovery to create one, or use --type=bug|chore if this "
                "isn't feature work.",
            )

        # Any design doc with all required sections is enough — rapid-schema docs
        # (with ## Problem rather than ## Problem Statement) naturally won't match
        # and are correctly skipped, since they describe bug/chore work the gate
        # is not concerned with.
        if any(not check_design_doc_sections(d) for d in docs):
            _record_signal(
                gate_name="discovery_gate",
                decision="allow",
                reason="valid design doc found",
                story_type=story_type,
                doc_count=len(docs),
            )
            return allow()

        # No valid feature-schema design doc — ask, showing what's missing on the
        # most recent partial doc.
        docs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        best_doc = docs[0]
        missing_list = ", ".join(check_design_doc_sections(best_doc))
        _record_signal(
            gate_name="discovery_gate",
            decision="ask",
            reason=f"design doc missing sections: {missing_list}",
            story_type=story_type,
            doc=str(best_doc.relative_to(project_dir)),
        )
        return ask(
            hook_event,
            f"No design doc with required sections found. "
            f"Most recent doc '{best_doc.relative_to(project_dir)}' is missing: "
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
