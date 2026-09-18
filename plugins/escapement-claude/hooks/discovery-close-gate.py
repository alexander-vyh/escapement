#!/usr/bin/env python3
"""Claude Code hook: nudge on `bd close` to verify discovery outcomes.

Fires as PreToolUse on Bash commands that actually invoke `bd close`, and asks
about the design the *closing beads* are linked to:
  - proof of delivery        — did you verify the real-world outcome?
  - anti-metrics             — did any failure condition occur?
  - oversized walking skeleton (>3 tasks) — did Phase 1 leak into the skeleton?
  - unresolved [SKELETON-BLOCKING] open questions — the skeleton was designed
                               around a gap

TARGETING. The design is resolved from the beads named on the command line, by
reading the `openspec/changes/<name>` or `docs/plans/<file>.md` reference the
bead itself carries. It used to be "the most recently touched change dir",
which is not a relation to the bead being closed: in a repo with 20+ in-flight
changes, every close asked about whichever design some other agent had touched
last. Closing a linter bead was interrogated about a revenue pipeline's
workbook parity. Asking the wrong question is worse than asking none — it
teaches the reader that this gate's questions are noise.

A bead with no design reference gets no questions. That is the honest answer:
there is no discovery artifact to verify it against, and guessing one produces
mock bureaucracy.

MATCHING is token-position aware (see `_bd_command`), so a `bd note` whose text
mentions closing, a grep for the phrase, or `bd close --help` no longer fire it.

ESCAPE (Rule 1). Prefix the command with `# close-gate-waiver: <reason>` — at
least 20 characters, naming something beyond the bead id and design path. The
reason is recorded as waiver signal and the close proceeds.

This is a nudge (ask), never a hard block (deny). The skeleton-size and
open-question checks only apply in openspec mode (legacy docs/plans/ predates
those conventions).

Input (via stdin):
  JSON with hook_event_name, tool_name, tool_input, cwd, session_id
Exit codes:
  0 — always (nudge or silent allow)
"""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

# Shared signal capture per claude/rules/gate-design.md Rule 2.
sys.path.insert(0, str(Path(__file__).parent))
try:
    from _gate_signal import record as _record_signal
except ImportError:  # pragma: no cover
    def _record_signal(*_args, **_kwargs) -> None:
        return None

# Token-position-aware reading of the bd invocation. Without it this hook
# cannot tell a real close from the phrase appearing in prose, so it fails
# OPEN rather than falling back to a substring match that is known to misfire.
try:
    from _bd_command import subcommand_bead_ids
except ImportError:  # pragma: no cover
    subcommand_bead_ids = None  # type: ignore[assignment]

# One owner for "is this free-text reason substance or ceremony" (Rule 3).
try:
    from oracle_reason_validation import asserted_tokens, validate_oracle_reason
except ImportError:  # pragma: no cover
    asserted_tokens = None  # type: ignore[assignment]
    validate_oracle_reason = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Escape path (gate-design Rule 1)
# ---------------------------------------------------------------------------

WAIVER_RE = re.compile(r"#\s*close-gate-waiver:\s*(\S.*?)\s*$", re.MULTILINE | re.IGNORECASE)


# ---------------------------------------------------------------------------
# Locating the design the closing beads point at
# ---------------------------------------------------------------------------
#
# Resolution is a RELATION to the bead, not a property of the filesystem. The
# previous "newest mtime under openspec/changes/" heuristic had no relation to
# the bead at all, so the question it asked was about whatever another agent
# had most recently touched.
#
# No mtime cutoff on the resolved design either. The 90-day cutoff this hook
# once carried is the same oracle-downgrade pattern the kaizen 3f8d37b removed
# from discovery-gate.py: filesystem mtime is the wrong oracle for "is this
# design still authoritative." Staleness is a content question.

_OPENSPEC_REF_RE = re.compile(r"openspec/changes/([A-Za-z0-9._-]+)")
_PLANS_REF_RE = re.compile(r"docs/plans/([A-Za-z0-9._-]+\.md)")

# Total wall-clock budget for all `bd show` calls, and the per-call cap. A
# tool-call gate that outlives the command it guards is its own defect.
_LOOKUP_BUDGET_SECONDS = 6.0
_LOOKUP_TIMEOUT_SECONDS = 3.0
_MAX_BEADS_INSPECTED = 4


def bead_blob(bead_id: str, project_dir: str, deadline: float) -> Optional[str]:
    """Return `bd show --json` output for one bead, or None when unavailable.

    Every failure — bd missing, non-zero exit, timeout, budget exhausted — is
    None, which the caller treats as "no design linked" and allows. A gate that
    guesses when its lookup fails asks the wrong question instead of none.
    """
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None
    try:
        result = subprocess.run(
            ["bd", "show", bead_id, "--json"],
            cwd=project_dir or None,
            capture_output=True,
            text=True,
            timeout=min(_LOOKUP_TIMEOUT_SECONDS, remaining),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout or None


def designs_in_blob(blob: str, project_dir: Path) -> list:
    """Design paths referenced by one bead's record, in first-seen order.

    Reads the whole record — description, notes, acceptance criteria, spec id,
    labels — because a bead links its design in whichever of those the author
    used, and every one of them is an equally real link.
    """
    found = []
    for name in _OPENSPEC_REF_RE.findall(blob):
        if name == "archive":
            continue
        candidate = project_dir / "openspec" / "changes" / name / "design.md"
        if candidate.is_file() and candidate not in found:
            found.append(candidate)
    for name in _PLANS_REF_RE.findall(blob):
        candidate = project_dir / "docs" / "plans" / name
        if candidate.is_file() and candidate not in found:
            found.append(candidate)
    return found


def designs_for_beads(bead_ids: list, project_dir: str) -> list:
    """Resolve the design docs the given beads reference."""
    root = Path(project_dir) if project_dir else Path.cwd()
    deadline = time.monotonic() + _LOOKUP_BUDGET_SECONDS
    designs = []
    for bead_id in bead_ids[:_MAX_BEADS_INSPECTED]:
        blob = bead_blob(bead_id, project_dir, deadline)
        if not blob:
            continue
        for design in designs_in_blob(blob, root):
            if design not in designs:
                designs.append(design)
    return designs


# ---------------------------------------------------------------------------
# Within-session deduplication
# ---------------------------------------------------------------------------
#
# Repeated bd close calls against the same design produce the same prompts.
# Habituation → mock bureaucracy (the user says 'yes' reflexively, treating
# the question as friction not signal). Track which design's prompts have
# already fired this session; skip silent re-prompts on the same design.


def _dedup_state_file(session_id: str) -> Path:
    return Path(f"/tmp/discovery_close_gate_{session_id}.json")


def _already_prompted(session_id: str, design_path: str) -> bool:
    if not session_id:
        return False
    path = _dedup_state_file(session_id)
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        return design_path in state.get("prompted", [])
    except (OSError, json.JSONDecodeError):
        return False


def _mark_prompted(session_id: str, design_path: str) -> None:
    if not session_id:
        return
    path = _dedup_state_file(session_id)
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        state = {"prompted": []}
    if design_path not in state["prompted"]:
        state["prompted"].append(design_path)
    try:
        path.write_text(json.dumps(state), encoding="utf-8")
    except OSError:
        pass  # dedup is best-effort; failure just means the next close re-asks


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
    if subcommand_bead_ids is None:
        # The argv reader is a required sibling. Without it the only available
        # alternative is the substring match this hook was fixed to stop using.
        return 0
    closing = subcommand_bead_ids(command, "close")
    if not closing:
        # Not a close of any named bead: `bd close --help`, a bare `bd close`
        # that bd itself will reject, or the phrase inside quoted prose.
        return 0

    project_dir = data.get("cwd", "") or data.get("workingDirectory", "") or os.getcwd()
    session_id = data.get("session_id", "") or os.environ.get("CLAUDE_CODE_SESSION_ID", "")

    # --- Locate the design(s) the closing beads actually point at ---
    designs = designs_for_beads(closing, project_dir)
    if not designs:
        _record_signal(
            gate_name="discovery_close_gate",
            decision="allow",
            reason="no design doc is linked to the closing bead(s)",
            beads=",".join(closing),
        )
        return allow()

    design_source = designs[0]
    try:
        design_content = design_source.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return allow()
    parent = design_source.parent
    change_dir = parent if parent.parent.name == "changes" else None

    # --- Escape path (Rule 1): a validated waiver proceeds and is recorded ---
    waiver_match = WAIVER_RE.search(command)
    if waiver_match and validate_oracle_reason is not None and asserted_tokens is not None:
        reason = waiver_match.group(1)
        # Rule 3: the reason has to say something beyond the identifiers it is
        # waiving, or it is ceremony that re-states the gate's own subject.
        echoed = asserted_tokens([*closing, design_source.name, parent.name])
        rejection = validate_oracle_reason(reason, echoed)
        if rejection is None:
            _record_signal(
                gate_name="discovery_close_gate",
                decision="waiver-accepted",
                reason=reason.strip(),
                event_type="waiver",
                design=str(design_source),
                beads=",".join(closing),
            )
            return allow()
        _record_signal(
            gate_name="discovery_close_gate",
            decision="waiver-rejected",
            reason=reason.strip(),
            event_type="waiver",
            rejection=rejection,
            design=str(design_source),
            beads=",".join(closing),
        )

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
        _record_signal(
            gate_name="discovery_close_gate",
            decision="allow",
            reason="design checks passed; no questions to surface",
            design=str(design_source) if design_source else None,
        )
        return allow()

    # Within-session dedup: don't re-ask the same questions on consecutive
    # closes against the same design. Habituation breeds mock compliance.
    design_path_str = str(design_source) if design_source else "_unknown_"
    if _already_prompted(session_id, design_path_str):
        _record_signal(
            gate_name="discovery_close_gate",
            decision="allow",
            reason="prompts already shown for this design this session (dedup)",
            design=design_path_str,
        )
        return allow()

    # Global transparency: name the design AND why this design — the bead that
    # links it. An agent who can see the link can also see when it is wrong.
    rel_design = design_path_str
    try:
        rel_design = str(Path(design_source).relative_to(project_dir))
    except (ValueError, TypeError):
        pass
    closing_text = ", ".join(closing)
    header = (
        f"Closing {closing_text}, which links the design at `{rel_design}`:\n\n"
    )
    footer = (
        "\n\nIf this design is not what these beads deliver, say so — that is a "
        "mis-linked bead worth fixing. To close without answering, re-run with "
        "a leading `# close-gate-waiver: <reason>` naming why verification does "
        "not apply here (20+ chars, and not just the bead id or design name)."
    )

    _record_signal(
        gate_name="discovery_close_gate",
        decision="ask",
        reason=f"surfacing {len(parts)} design-doc question(s) before close",
        design=design_path_str,
        beads=closing_text,
        question_count=len(parts),
    )
    _mark_prompted(session_id, design_path_str)
    return ask(hook_event, header + "\n\n".join(parts) + footer)


if __name__ == "__main__":
    sys.exit(main())
