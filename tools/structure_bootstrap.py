#!/usr/bin/env python3
"""Produce a reviewable declaration for a repository that has none.

The instrument previously needed someone to already know a repository's package
name. That works for the two repositories we tuned by hand and nowhere else,
which is the difference between a capability and a demo.

Bootstrap detects candidate scope, measures how much of the repository that
scope would cover, and writes a declaration skeleton whose exclusions are
deliberately left unjustified — because an exclusion is a forecast about where
the next defect will be, and a generated forecast is worthless. The file it
writes does not validate until a human says why.
"""

from __future__ import annotations

import collections
import json
import pathlib

import structure_adapters as _adapters


def candidate_scope(repo: str, limit: int = 6) -> list[str]:
    """Top-level directories holding measurable source, densest first.

    Proposed, never assumed. The output is a starting point for a human, and
    the accompanying coverage number is what tells them whether it is wrong.
    """
    files = _adapters.inventory(repo)
    counts: collections.Counter = collections.Counter()
    for paths in files.values():
        for path in paths:
            parts = path.split("/")
            if len(parts) > 1:
                counts[parts[0]] += 1
    roots = [name for name, _ in counts.most_common(limit)
             if not name.startswith(".")]
    return roots


def skeleton(repo: str, scope: list[str]) -> dict:
    cov = _adapters.coverage(repo, scope)
    unmeasured = sorted(
        (
            (row["files"] - row["measured"], language)
            for language, row in cov.by_language.items()
            if row["measured"] < row["files"]
        ),
        reverse=True,
    )
    return {
        "_": (
            "Declared intent. Measurements are never stored here — they are "
            "derived from source on every run. Replace every REVIEW marker "
            "before this file is trusted; it will not validate until you do."
        ),
        "scope": scope,
        "exclusions": [
            {
                "path": f"<{language} source outside scope>",
                "why": "REVIEW: what goes wrong here, if we never look?",
                "_unmeasured_files": count,
            }
            for count, language in unmeasured
        ],
        "pins": [],
        "waivers": [],
    }


def write(repo: str, data: dict) -> pathlib.Path:
    path = pathlib.Path(repo) / ".escapement" / "structure.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")
    return path


def render(repo: str, scope: list[str], cov: _adapters.Coverage) -> str:
    lines = [
        f"proposed scope: {', '.join(scope) or '(none detected)'}",
        "",
        _adapters.render(cov, repo),
        "",
        "  Nothing above is a decision yet. Review the scope, then justify each",
        "  exclusion: the declaration is invalid while any 'why' still says REVIEW,",
        "  so an unexamined skeleton cannot be mistaken for a considered one.",
    ]
    return "\n".join(lines)
