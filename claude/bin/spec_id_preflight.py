#!/usr/bin/env python3
"""Spec-id referential-integrity preflight.

Bead: claude-workflow-setup-ao0.

## The gap this closes

`work-breakdown` bakes ``--spec-id=...specs/{cap}.md#{requirement}`` into beads
tasks. The ``spec_id_enforcement`` hook validates that the anchor resolves to a
real ``### Requirement: ...`` heading — but only AT CREATION TIME. If a later
discovery/spec edit renames or deletes that requirement heading, every baked-in
spec-id pointing at the old anchor is silently orphaned: the bead still claims
traceability to a requirement that no longer exists under that name.

This script is the re-validation pass. It scans the spec-ids currently attached
to beads and reports every one whose ``file#anchor`` no longer resolves to a
real requirement heading. It exits non-zero iff at least one orphan exists, so
it can be wired into CI or run as a preflight before relying on spec-id
traceability.

## Resolution semantics (mirrors spec_id_enforcement.validate_spec_id)

A spec-id ``path#anchor`` resolves iff:
  1. ``path`` (relative to the project root) is an existing, readable file, and
  2. if an ``anchor`` is present, some line in that file is
     ``### Requirement: <name>`` whose ``<name>`` equals the anchor either
     literally (case-insensitive) or after kebab->space normalisation
     (``render-the-widget`` <-> ``Render the widget``).

A spec-id with no anchor resolves iff the file exists.

Note: this is intentionally the *referential* check (does the anchor still
point at a real heading), which is the orphan condition the bead names. It does
NOT re-run the placeholder-value rejection that the creation-time gate does —
placeholders never make it into the tracker because the creation gate blocks
them; re-checking them here would conflate two different failure modes.

## Usage

    # Scan the live tracker (queries bd):
    python3 claude/bin/spec_id_preflight.py
    python3 claude/bin/spec_id_preflight.py --project-dir /path/to/repo

Exit codes:
  0 — every bead spec-id resolves (or no spec-ids found)
  1 — at least one bead spec-id is orphaned (details printed to stdout)
  2 — could not enumerate beads (bd unavailable / errored)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Optional


# bd may surface the spec-id under any of these key names depending on version.
_SPEC_ID_KEYS = ("spec_id", "specID", "spec-id", "specId")


# ---------------------------------------------------------------------------
# Pure resolution core
# ---------------------------------------------------------------------------

def _requirement_headings(content: str) -> list[str]:
    """Return the lowercased names of every ``### Requirement: <name>`` heading."""
    return [
        line[len("### Requirement:"):].strip().lower()
        for line in content.splitlines()
        if line.startswith("### Requirement:")
    ]


def check_spec_id(spec_id: str, project_dir: Path) -> tuple[bool, str]:
    """Return ``(resolved, reason)`` for a single spec-id.

    ``resolved`` is True iff the path exists and (when an anchor is present)
    the anchor matches a real ``### Requirement: ...`` heading. ``reason`` is a
    human-readable explanation when not resolved (empty when resolved).
    """
    if not spec_id or not spec_id.strip():
        # No spec-id to check — nothing to orphan. Callers should filter these
        # out, but treat an empty value as "resolved / nothing to do".
        return True, ""

    if "#" in spec_id:
        path_part, anchor = spec_id.split("#", 1)
    else:
        path_part, anchor = spec_id, ""

    spec_path = (project_dir / path_part).resolve()
    if not spec_path.is_file():
        return False, (
            f"path '{path_part}' no longer resolves to a file "
            f"(spec moved or deleted)"
        )

    if not anchor:
        return True, ""

    try:
        content = spec_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False, f"path '{path_part}' exists but cannot be read"

    headings = _requirement_headings(content)
    if not headings:
        return False, (
            f"spec file '{path_part}' no longer contains any "
            f"'### Requirement: ...' headings"
        )

    anchor_spaced = anchor.replace("-", " ").lower()
    matched = any(
        heading == anchor.lower() or heading == anchor_spaced
        for heading in headings
    )
    if not matched:
        available = ", ".join(sorted(headings)[:3])
        more = "..." if len(headings) > 3 else ""
        return False, (
            f"anchor '#{anchor}' no longer matches any "
            f"'### Requirement: ...' heading in '{path_part}' "
            f"(heading was renamed or removed). Current headings: "
            f"{available}{more}"
        )

    return True, ""


def scan_spec_ids(
    pairs: Iterable[tuple[str, Optional[str]]],
    project_dir: Path,
) -> list[tuple[str, str, str]]:
    """Classify ``(bead_id, spec_id)`` pairs.

    Returns the list of orphans as ``(bead_id, spec_id, reason)``. Beads with
    no spec-id (None / empty) are skipped — they cannot be orphaned because
    they never claimed traceability to a requirement.
    """
    orphans: list[tuple[str, str, str]] = []
    for bead_id, spec_id in pairs:
        if not spec_id or not spec_id.strip():
            continue
        resolved, reason = check_spec_id(spec_id, project_dir)
        if not resolved:
            orphans.append((bead_id, spec_id, reason))
    return orphans


def run(
    pairs: Iterable[tuple[str, Optional[str]]],
    project_dir: Path,
) -> int:
    """Scan the pairs and report. Returns 0 if clean, 1 if any orphan exists."""
    pairs = list(pairs)
    orphans = scan_spec_ids(pairs, project_dir)

    checked = sum(1 for _bid, sid in pairs if sid and sid.strip())
    if not orphans:
        print(
            f"spec-id preflight: OK — {checked} spec-id(s) checked, "
            f"0 orphaned anchors."
        )
        return 0

    print(
        f"spec-id preflight: FAIL — {len(orphans)} of {checked} spec-id(s) "
        f"have orphaned anchors:"
    )
    for bead_id, spec_id, reason in orphans:
        print(f"  - {bead_id}: {spec_id}")
        print(f"      {reason}")
    print(
        "\nA spec heading was renamed/removed after these beads were created. "
        "Either restore the heading, or update each bead's --spec-id to the "
        "new anchor."
    )
    return 1


# ---------------------------------------------------------------------------
# bd enumeration (live tracker)
# ---------------------------------------------------------------------------

def _extract_spec_id(issue: dict) -> Optional[str]:
    """Pull the spec-id off a bd issue dict under any known key name."""
    for key in _SPEC_ID_KEYS:
        val = issue.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    # Some bd versions nest it under metadata/extra as JSON.
    for container_key in ("metadata", "extra"):
        container = issue.get(container_key)
        if isinstance(container, str):
            try:
                container = json.loads(container)
            except (json.JSONDecodeError, ValueError):
                container = {}
        if isinstance(container, dict):
            for key in _SPEC_ID_KEYS:
                val = container.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip()
    return None


def _bd_json(args: list[str]) -> Optional[object]:
    try:
        result = subprocess.run(
            ["bd", *args],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return None


def enumerate_bead_spec_ids() -> Optional[list[tuple[str, Optional[str]]]]:
    """Return ``(bead_id, spec_id)`` for every bead in the tracker.

    Returns None if bd could not be queried at all (so the caller can exit 2
    rather than silently reporting "0 orphans" on a broken enumeration —
    fail-loud, per never-suppress).
    """
    listing = _bd_json(["list", "--json"])
    if listing is None:
        return None

    if isinstance(listing, dict):
        items = listing.get("issues") or listing.get("items") or []
    elif isinstance(listing, list):
        items = listing
    else:
        items = []

    pairs: list[tuple[str, Optional[str]]] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        bead_id = it.get("id")
        if not bead_id:
            continue
        spec_id = _extract_spec_id(it)
        if spec_id is None:
            # The list view may omit spec-id; fetch the full issue.
            full = _bd_json(["show", str(bead_id), "--json"])
            if isinstance(full, list):
                full = full[0] if full else {}
            if isinstance(full, dict):
                spec_id = _extract_spec_id(full)
        pairs.append((str(bead_id), spec_id))
    return pairs


def _resolve_project_dir() -> Path:
    cwd = Path(os.getcwd()).resolve()
    for parent in [cwd, *cwd.parents]:
        if (parent / ".beads").is_dir():
            return parent
    return cwd


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Re-validate that beads' baked-in --spec-id anchors still "
        "resolve to real '### Requirement: ...' headings."
    )
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=None,
        help="Project root. Default: walk up from cwd to find .beads/.",
    )
    args = parser.parse_args()

    project_dir = (
        args.project_dir.resolve()
        if args.project_dir is not None
        else _resolve_project_dir()
    )

    pairs = enumerate_bead_spec_ids()
    if pairs is None:
        print(
            "spec-id preflight: ERROR — could not enumerate beads (is bd "
            "installed and is this a beads repo?).",
            file=sys.stderr,
        )
        return 2

    return run(pairs, project_dir)


if __name__ == "__main__":
    sys.exit(main())
