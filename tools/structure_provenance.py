#!/usr/bin/env python3
"""Provenance for a derived measurement.

A stored number is authority without accountability: anyone can edit it and
nothing detects the edit. This module makes a number a *claim with a
re-derivation recipe* instead — the value plus enough identity that re-running
the measurement either reproduces it or visibly does not.

It exists because of two real failures in this estate, neither of them a lie:

  * A complexity baseline absorbed a radon de-duplication fix across 212
    revisions, so a series in which aggregate complexity rose 39% read as a 14%
    fall for three months. The number did not change dishonestly; its
    *definition* did, and nothing recorded which definition produced which
    value.
  * A P1 bead quoted propagation cost, cycle counts and largest-cycle size that
    were produced by this very tool six hours before four of its graph bugs
    were fixed. Nobody re-derived. Prose is a storage medium too.

Both are caught by the same three fields: what was measured, what measured it,
and under which configuration.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import pathlib
import subprocess
import datetime as _dt


def _git(repo: pathlib.Path, *args: str, timeout: int = 30) -> str:
    try:
        done = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip()


def _content_hash(paths: list[pathlib.Path]) -> str:
    """Hash of the measuring code itself, for when git cannot speak for it."""
    digest = hashlib.sha256()
    for path in sorted(paths):
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"<unreadable>")
    return digest.hexdigest()[:12]


def tool_identity(sources: list[pathlib.Path] | None = None) -> dict:
    """Identify the code that produced a measurement.

    A commit sha alone is not enough. If the measuring code has uncommitted
    edits, that sha names something other than what ran, so the identity says
    so and falls back to hashing the bytes. An identity that can silently
    describe the wrong code is the failure this module exists to prevent.
    """
    here = pathlib.Path(__file__).resolve()
    sources = sources or [here]
    repo = here.parent
    sha = _git(repo, "rev-parse", "HEAD")
    rel = [str(p) for p in sources]
    dirty = bool(_git(repo, "status", "--porcelain", "--", *rel))
    return {
        "tool_sha": sha or "unknown",
        "tool_dirty": dirty,
        "tool_content": _content_hash(sources),
    }


def config_digest(config: dict) -> str:
    """Stable digest over everything that changes the answer.

    Roots, exclusions, thresholds, flags. Two measurements are comparable only
    when this matches; when it does not, the series is discontinuous and should
    say so rather than being plotted as one line.
    """
    canonical = json.dumps(config, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:12]


@dataclasses.dataclass
class Provenance:
    """Everything needed to re-derive a number, and nothing else."""

    input_sha: str = ""
    input_repo: str = ""
    tool_sha: str = ""
    tool_dirty: bool = False
    tool_content: str = ""
    config_digest: str = ""
    measured_at: str = ""
    recipe: str = ""

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    def comparable_to(self, other: "Provenance") -> bool:
        """Two measurements may be differenced only under one definition."""
        return (
            self.config_digest == other.config_digest
            and self.tool_content == other.tool_content
        )

    def warning(self) -> str:
        """Why this number might not mean what a reader assumes. Empty if fine."""
        if self.tool_dirty:
            return (
                "measuring code has uncommitted changes; tool_sha does not "
                "identify what ran — re-derive from a clean tree before quoting"
            )
        return ""


def build(
    *,
    repo: str | pathlib.Path,
    input_sha: str,
    config: dict,
    recipe: str,
    sources: list[pathlib.Path] | None = None,
) -> Provenance:
    identity = tool_identity(sources)
    return Provenance(
        input_sha=input_sha,
        input_repo=str(repo),
        config_digest=config_digest(config),
        measured_at=_dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        recipe=recipe,
        **identity,
    )
