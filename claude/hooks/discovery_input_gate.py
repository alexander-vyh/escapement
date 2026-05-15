#!/usr/bin/env python3
"""Claude Code hook: gate solution artifacts on a confirmed problem framing.

Fires as PreToolUse on Write/Edit. When the target is a solution artifact
(`proposal.md` or `design.md`) under an OpenSpec change, this hook requires a
confirmed `problem-framing.md` in the same change directory before the write is
allowed.

Mechanical backstop for the discovery Input Gate — prevents the
"draft-and-fabricate" failure where discovery fills an unconfirmed framing with
plausible prose.

This hook is a FLOOR, not a ceiling. It can only check that the six framing
fields are *filled* — it cannot judge whether the content is *good*. A riskiest
assumption that reads only "we will succeed" passes this hook. Content quality is
the interview's job (brainstorming's forcing check) and the human's job.

Behavior (uniform — no special-cased field, no "ask" path):
  - `rapid`-schema changes are exempt.
  - Missing problem-framing.md            -> deny
  - Any of the six fields unfilled
    (missing header, empty body, or TBD)  -> deny
  - All six fields filled                 -> allow

A field that genuinely does not apply is filled with "none - <reason>", which
counts as filled. Only genuinely unfilled fields block.

  - `.openspec.yaml` unreadable           -> fail closed (require the framing)
  - Unparseable stdin                     -> fail open (allow)

Input (via stdin):
  JSON with hook_event_name, tool_name, tool_input
Exit codes:
  0 — allow
  2 — deny (JSON output explains why)
"""

import json
import sys
from pathlib import Path
from typing import NoReturn, Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GATED_ARTIFACTS = ("design.md", "proposal.md")

REQUIRED_FIELDS = [
    "Problem",
    "Why Now",
    "Decision Authority",
    "Behavioral Population",
    "Riskiest Assumption",
    "Success Criteria",
]

# A field body containing one of these markers is "unfilled" — the question was
# deferred, not answered. Note: "none" is deliberately NOT a marker. "none" means
# a considered judgment that the dimension does not apply, which counts as filled.
TBD_MARKERS = ("tbd", "todo", "???", "fixme")


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def is_gated_artifact(file_path: str) -> Optional[str]:
    """Return the change directory if file_path is a gated solution artifact.

    A gated artifact is `design.md` or `proposal.md` whose parent directory is
    `openspec/changes/{name}`. `problem-framing.md` is never gated — writing the
    framing itself must always be allowed. Returns None when not gated.
    """
    if not file_path:
        return None
    p = Path(file_path)
    if p.name not in GATED_ARTIFACTS:
        return None
    change_dir = p.parent
    if (change_dir.parent.name == "changes"
            and change_dir.parent.parent.name == "openspec"):
        return str(change_dir)
    return None


def read_schema(change_dir: str) -> Optional[str]:
    """Return the schema from `.openspec.yaml`, or None if unreadable/missing."""
    yaml_path = Path(change_dir) / ".openspec.yaml"
    try:
        content = yaml_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("schema:"):
            return stripped.split(":", 1)[1].strip()
    return None


def _parse_sections(content: str) -> dict:
    """Map each '## Header' to its body text (until the next '## ' or EOF)."""
    sections: dict = {}
    current = None
    buf: list = []
    for line in content.splitlines():
        if line.startswith("## "):
            if current is not None:
                sections[current] = "\n".join(buf).strip()
            current = line[3:].strip()
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf).strip()
    return sections


def _body_is_unfilled(body: str) -> bool:
    """A field body is unfilled if empty or contains a TBD-style marker."""
    if not body.strip():
        return True
    low = body.lower()
    return any(marker in low for marker in TBD_MARKERS)


def validate_framing(framing_path: str) -> dict:
    """Inspect problem-framing.md content.

    Returns a dict:
      exists — bool, whether the file could be read
      bad    — list of required field names that are unfilled (absent header,
               empty body, or a TBD-style marker)

    A field filled with "none - <reason>" is considered filled — a considered
    judgment that the dimension does not apply. Only genuinely unfilled fields
    appear in `bad`. No field is special-cased.
    """
    try:
        content = Path(framing_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"exists": False, "bad": []}

    sections = _parse_sections(content)
    norm = {k.lower(): v for k, v in sections.items()}

    bad: list = []
    for field in REQUIRED_FIELDS:
        body = norm.get(field.lower())
        if body is None or _body_is_unfilled(body):
            bad.append(field)

    return {"exists": True, "bad": bad}


# ---------------------------------------------------------------------------
# Output helper
# ---------------------------------------------------------------------------

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
        return 0  # fail open on malformed input

    hook_event = data.get("hook_event_name", "") or data.get("hookEventName", "")
    if hook_event != "PreToolUse":
        return 0

    tool_name = data.get("tool_name", "")
    if tool_name not in ("Write", "Edit"):
        return 0

    tool_input = data.get("tool_input", {})
    file_path = tool_input.get("file_path", "") if isinstance(tool_input, dict) else ""

    change_dir = is_gated_artifact(file_path)
    if change_dir is None:
        return 0  # not a gated solution artifact

    # rapid-schema work is exempt. An unreadable schema fails CLOSED — we treat
    # it as feature/epic and require the framing.
    if read_schema(change_dir) == "rapid":
        return 0

    framing_path = str(Path(change_dir) / "problem-framing.md")
    result = validate_framing(framing_path)
    artifact_name = Path(file_path).name

    if not result["exists"]:
        deny(
            hook_event,
            f"No confirmed problem framing. Discovery requires problem-framing.md "
            f"in this change directory before drafting {artifact_name}. Run "
            f"/brainstorming for the convergent interview, or supply the six "
            f"framing fields inline and confirm them.",
        )

    if result["bad"]:
        fields = ", ".join(result["bad"])
        plural = "fields" if len(result["bad"]) > 1 else "field"
        deny(
            hook_event,
            f"problem-framing.md has unfilled {plural}: {fields}. A field that "
            f"genuinely does not apply must say 'none - <reason>', not be left "
            f"blank or TBD. Complete the framing before drafting {artifact_name}.",
        )

    return 0  # all six fields filled — allow


if __name__ == "__main__":
    sys.exit(main())
