#!/usr/bin/env python3
"""Reader for `.escapement/repo.json` — the per-project options manifest.

Resolves a repo's declared *intended outcome* and *auto-merge authorization*
(repo-outcome-authorization). This is the durable artifact the base Claude Code
system prompt defers to when it says "confirm before hard-to-reverse / outward-facing
actions — unless durably authorized." A committed declaration IS that authorization.

Fail-safe by construction: absent, malformed, or invalid declarations resolve to the
CONSERVATIVE default (intended_outcome=pr-opened, auto_merge_on_green=False). An
unconfigured repo therefore behaves exactly as today, and a missing or broken file is
NEVER treated as authorization to merge/deploy live (design anti-metric #2).

`.escapement/repo.json` schema (all keys optional; unknown keys ignored):
    {
      "intended_outcome": "committed" | "pr-opened" | "merged" | "merged-and-deployed",
      "auto_merge_on_green": true | false,
      "deploy": { ... informational, surfaced in the agent's report ... },
      "confirm_class": [ "db-migration", ... ]   # narrow set that still asks (per-repo)
    }
"""
from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass, field
from typing import Optional

# Ordered ladder: how far "done" reaches. Index encodes the ordering.
INTENDED_OUTCOME_LADDER = ("committed", "pr-opened", "merged", "merged-and-deployed")

# Auto-merge is only meaningful at or above this rung.
_MERGE_MIN_INDEX = INTENDED_OUTCOME_LADDER.index("merged")

_DEFAULT_OUTCOME = "pr-opened"


@dataclass
class RepoOutcome:
    """Resolved per-project outcome authorization.

    `source` records provenance so callers can distinguish a real declaration from a
    fallback: "declared" | "default-absent" | "default-malformed" | "default-invalid".
    `warning` is set (non-None) only when we fell back from a present-but-broken file,
    so the caller can surface it instead of silently swallowing a misconfiguration.
    """

    intended_outcome: str
    auto_merge_on_green: bool
    deploy: Optional[dict]
    confirm_class: list
    source: str
    warning: Optional[str] = None
    confirm_class_absolute: bool = True  # False when a non-empty confirm_class is declared


def _default(source: str, warning: Optional[str]) -> RepoOutcome:
    return RepoOutcome(
        intended_outcome=_DEFAULT_OUTCOME,
        auto_merge_on_green=False,
        deploy=None,
        confirm_class=[],
        source=source,
        warning=warning,
    )


def declaration_path(repo_root) -> pathlib.Path:
    return pathlib.Path(repo_root) / ".escapement" / "repo.json"


def resolve(repo_root) -> RepoOutcome:
    """Resolve the repo's outcome authorization, fail-safe on every error path."""
    path = declaration_path(repo_root)
    if not path.exists():
        return _default("default-absent", None)

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as exc:
        return _default(
            "default-malformed",
            f".escapement/repo.json is unparseable ({exc}); using conservative "
            f"default (no auto-merge).",
        )

    if not isinstance(raw, dict):
        return _default(
            "default-malformed",
            ".escapement/repo.json must be a JSON object; using conservative default "
            "(no auto-merge).",
        )

    outcome = raw.get("intended_outcome", _DEFAULT_OUTCOME)
    if outcome not in INTENDED_OUTCOME_LADDER:
        return _default(
            "default-invalid",
            f".escapement/repo.json has invalid intended_outcome {outcome!r} "
            f"(expected one of {list(INTENDED_OUTCOME_LADDER)}); using conservative "
            f"default (no auto-merge).",
        )

    # auto_merge_on_green: only a real boolean True counts; anything else is False.
    auto_merge = raw.get("auto_merge_on_green", False)
    if not isinstance(auto_merge, bool):
        auto_merge = False

    deploy = raw.get("deploy")
    if deploy is not None and not isinstance(deploy, dict):
        deploy = None

    confirm_class = raw.get("confirm_class", [])
    if not isinstance(confirm_class, list):
        confirm_class = []

    return RepoOutcome(
        intended_outcome=outcome,
        auto_merge_on_green=auto_merge,
        deploy=deploy,
        confirm_class=confirm_class,
        source="declared",
        warning=None,
        confirm_class_absolute=(len(confirm_class) == 0),
    )


def _outcome_index(outcome: str) -> int:
    try:
        return INTENDED_OUTCOME_LADDER.index(outcome)
    except ValueError:
        return INTENDED_OUTCOME_LADDER.index(_DEFAULT_OUTCOME)


def authorizes_auto_merge(outcome: RepoOutcome) -> bool:
    """The load-bearing predicate: may an agent merge a GREEN PR without asking?

    Requires BOTH the explicit flag AND an intended outcome at or above 'merged'.
    The consistency guard (flag true but outcome only pr-opened) does NOT authorize —
    you cannot auto-merge in a repo that declared it only wants a PR opened.
    """
    return bool(outcome.auto_merge_on_green) and _outcome_index(
        outcome.intended_outcome
    ) >= _MERGE_MIN_INDEX
