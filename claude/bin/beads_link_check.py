#!/usr/bin/env python3
"""Ephemeral Beads-to-OpenSpec link-integrity check (walking skeleton).

OpenSpec change: openspec/changes/beads-openspec-link-check.

## What this does

For ONE OpenSpec change, answers — from live Beads state — whether each Bead's
``spec_id`` link is *honest*: does it resolve to a live OpenSpec anchor? It prints
a report to **stdout**, writes no file, and mutates nothing. Volatile metadata
(a generated-at timestamp) goes to **stderr** so stdout is deterministic.

It **fails closed (non-zero exit) on, and only on, a closed two-member set of
link-integrity violations** — a structured ``spec_id`` claim that does not
resolve:

  1. orphaned ``spec_id``           — the target path/file is gone, and
  2. present-but-unresolved ``spec_id`` — the file exists but the anchor was
     renamed/removed (a false GREEN strictly worse than an orphan).

Everything else is ADVISORY and exits zero: blocked work, a requirement with no
linked Beads (missing coverage), and a Bead that merely *mentions* a change path
in its description without a ``spec_id`` (silence is not a claim, so it is not a
lie). Failing closed on progress or on free prose would earn a ``|| true`` and
disable the gate.

## Reuse

Resolution semantics are NOT redefined here. This composes
``spec_id_preflight.check_spec_id`` (the repo's existing referential-integrity
core) so there is exactly one definition of "resolves" across the repo. The new
code is the change-scoping, requirement-coverage grouping, advisory semantics,
and ephemeral presentation.

## Usage

    python3 claude/bin/beads_link_check.py --change <change>
    python3 claude/bin/beads_link_check.py --change <change> --project-dir /repo
    # test / piping seam: read issues from a file instead of querying bd
    bd list --json | ... ; python3 ... --change <c> --issues-file issues.json

Exit codes:
  0 — every in-scope spec_id resolves (advisories may still be printed)
  1 — at least one link-integrity violation (orphaned / unresolved spec_id)
  2 — could not load Beads issues (bd unavailable / errored)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Reuse the repo's single definition of spec-id resolution.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
from spec_id_preflight import check_spec_id, _extract_spec_id  # noqa: E402


# ---------------------------------------------------------------------------
# Report model
# ---------------------------------------------------------------------------

@dataclass
class Violation:
    bead_id: str
    spec_id: str
    kind: str  # "orphaned-path" | "unresolved-anchor"
    reason: str
    clearing_action: str


@dataclass
class Advisory:
    bead_id: str
    kind: str  # "blocked" | "unlinked-mention"
    detail: str


@dataclass
class Report:
    change: str
    integrity_violations: list = field(default_factory=list)
    coverage: dict = field(default_factory=dict)        # heading -> [bead_id]
    missing_coverage: list = field(default_factory=list)  # [heading]
    advisory_unlinked: list = field(default_factory=list)
    advisory_blocked: list = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        return 1 if self.integrity_violations else 0


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def _requirement_anchors(project_dir: Path, change: str) -> list[str]:
    """Lowercased ``### Requirement: <name>`` headings across the change's specs."""
    specs_root = project_dir / "openspec" / "changes" / change / "specs"
    anchors: list[str] = []
    if not specs_root.is_dir():
        return anchors
    for spec_file in sorted(specs_root.rglob("*.md")):
        try:
            content = spec_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in content.splitlines():
            if line.startswith("### Requirement:"):
                anchors.append(line[len("### Requirement:"):].strip().lower())
    return anchors


def _targets_change(spec_id: str, change: str) -> bool:
    path_part = spec_id.split("#", 1)[0].lstrip("./")
    return path_part.startswith(f"openspec/changes/{change}/")


def _matched_heading(spec_id: str, anchors: list[str]) -> Optional[str]:
    """The requirement heading a resolving spec_id covers, or None."""
    if "#" not in spec_id:
        return None
    anchor = spec_id.split("#", 1)[1]
    candidates = {anchor.lower(), anchor.replace("-", " ").lower()}
    for heading in anchors:
        if heading in candidates:
            return heading
    return None


def _clearing_action(bead_id: str, spec_id: str, kind: str) -> str:
    path_part = spec_id.split("#", 1)[0]
    if kind == "orphaned-path":
        return (
            f"clear: restore the spec file at '{path_part}', or "
            f"`bd update {bead_id} --spec-id <valid-path#anchor>`"
        )
    return (
        f"clear: restore the renamed anchor, or "
        f"`bd update {bead_id} --spec-id {path_part}#<current-heading>`"
    )


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def build_report(issues: list, change: str, project_dir: Path) -> Report:
    """Build the link-integrity-and-status report for one change.

    ``issues`` is a list of bd issue dicts (id, status, description, spec_id).
    Pure: reads only the on-disk specs and the given issues; writes nothing.
    """
    project_dir = Path(project_dir)
    anchors = _requirement_anchors(project_dir, change)
    report = Report(change=change)
    report.coverage = {h: [] for h in anchors}

    for issue in sorted(issues, key=lambda i: str(i.get("id", ""))):
        bead_id = str(issue.get("id", ""))
        status = str(issue.get("status", "") or "")
        description = str(issue.get("description", "") or "")
        spec_id = _extract_spec_id(issue)

        if spec_id and _targets_change(spec_id, change):
            resolved, reason = check_spec_id(spec_id, project_dir)
            if resolved:
                heading = _matched_heading(spec_id, anchors)
                if heading is not None:
                    report.coverage.setdefault(heading, []).append(bead_id)
                if status == "blocked":
                    report.advisory_blocked.append(
                        Advisory(bead_id, "blocked", f"{spec_id}")
                    )
            else:
                path_part = spec_id.split("#", 1)[0]
                kind = (
                    "orphaned-path"
                    if not (project_dir / path_part).is_file()
                    else "unresolved-anchor"
                )
                report.integrity_violations.append(
                    Violation(
                        bead_id=bead_id,
                        spec_id=spec_id,
                        kind=kind,
                        reason=reason,
                        clearing_action=_clearing_action(bead_id, spec_id, kind),
                    )
                )
        elif not spec_id and f"openspec/changes/{change}" in description:
            # Silence in the structured channel: a prose mention is not a link
            # and not a lie. Advisory only.
            report.advisory_unlinked.append(
                Advisory(bead_id, "unlinked-mention",
                         "description mentions the change but has no spec_id")
            )
        # spec_id targeting a different change, or no signal at all -> out of scope.

    for beads in report.coverage.values():
        beads.sort()
    report.missing_coverage = sorted(h for h, b in report.coverage.items() if not b)
    report.integrity_violations.sort(key=lambda v: v.bead_id)
    report.advisory_blocked.sort(key=lambda a: a.bead_id)
    report.advisory_unlinked.sort(key=lambda a: a.bead_id)
    return report


# ---------------------------------------------------------------------------
# Rendering (stdout — deterministic, no timestamp)
# ---------------------------------------------------------------------------

def render(report: Report) -> str:
    lines: list[str] = []
    lines.append(f"beads-openspec-link-check — change: {report.change}")
    lines.append("(ephemeral derived view; OpenSpec owns intent, Beads owns task "
                 "state, harness owns proof)")
    lines.append("")

    if report.integrity_violations:
        lines.append(f"LINK-INTEGRITY VIOLATIONS ({len(report.integrity_violations)}) "
                     "— a spec_id that does not resolve:")
        for v in report.integrity_violations:
            lines.append(f"  ✗ {v.bead_id}  [{v.kind}]  {v.spec_id}")
            lines.append(f"      {v.reason}")
            lines.append(f"      {v.clearing_action}")
        lines.append("")
    else:
        lines.append("LINK-INTEGRITY: OK — every in-scope spec_id resolves.")
        lines.append("")

    lines.append("REQUIREMENT COVERAGE:")
    for heading in sorted(report.coverage):
        beads = report.coverage[heading]
        if beads:
            lines.append(f"  - {heading}: {', '.join(beads)}")
        else:
            lines.append(f"  - {heading}: (no linked beads — missing coverage)")
    lines.append("")

    if report.advisory_blocked or report.advisory_unlinked:
        lines.append("ADVISORY (does not affect exit code):")
        for a in report.advisory_blocked:
            lines.append(f"  · blocked: {a.bead_id} ({a.detail})")
        for a in report.advisory_unlinked:
            lines.append(f"  · unlinked mention: {a.bead_id} — {a.detail}")
        lines.append("")

    return "\n".join(lines).rstrip("\n") + "\n"


# ---------------------------------------------------------------------------
# Live Beads loading
# ---------------------------------------------------------------------------

def _load_issues_live() -> Optional[list]:
    try:
        result = subprocess.run(
            ["bd", "list", "--json"],
            capture_output=True, text=True, timeout=30,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return None
    if isinstance(data, dict):
        for key in ("issues", "items", "results"):
            if isinstance(data.get(key), list):
                return data[key]
        return None
    return data if isinstance(data, list) else None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Ephemeral Beads-to-OpenSpec "
                                                 "link-integrity check.")
    parser.add_argument("--change", required=True,
                        help="OpenSpec change name under openspec/changes/")
    parser.add_argument("--project-dir", default=".",
                        help="Project root (default: cwd)")
    parser.add_argument("--issues-file",
                        help="Read bd issue JSON from this file instead of "
                             "querying bd (test / piping seam)")
    args = parser.parse_args(argv)

    project_dir = Path(args.project_dir).resolve()

    if args.issues_file:
        try:
            issues = json.loads(Path(args.issues_file).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            print(f"beads-openspec-link-check: cannot read --issues-file: {exc}",
                  file=sys.stderr)
            return 2
    else:
        issues = _load_issues_live()
        if issues is None:
            print("beads-openspec-link-check: could not enumerate beads "
                  "(bd unavailable or errored).", file=sys.stderr)
            return 2

    report = build_report(issues, args.change, project_dir)
    sys.stdout.write(render(report))
    # Volatile metadata to stderr so stdout stays byte-deterministic.
    print(f"generated-at: {datetime.now(timezone.utc).isoformat()} "
          f"change={args.change}", file=sys.stderr)
    return report.exit_code


if __name__ == "__main__":
    sys.exit(main())
