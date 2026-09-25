#!/usr/bin/env python3
"""Detect self-neutering ("suppressed") verification commands (move 1b).

A contract's ``verification_command`` is the agent's to write, so an agent can
reach exit 0 by GUTTING the check instead of fixing the work — the never-suppress
violation relocated to the contract oracle (escapement-e9v.2). The
harness Stop gate uses this to refuse to count a suppressed green as a real pass.

Conservative by design: flag only UNAMBIGUOUS self-neutering —
  - a bare no-op command (``true`` / ``:``),
  - failure-masking ``|| true`` / ``|| :`` / ``|| exit 0``,
  - a trailing ``; true`` / ``; :`` / ``; exit 0``,
  - an embedded hook-disable (``--no-verify`` / ``SKIP=`` / ``HUSKY=0``).

Deliberately NOT flagged (need a baseline or actually propagate the failure;
they stay with the oracle-downgrade detectors + human review):
  - scope-narrowing (``pytest -k one_test``),
  - ``|| exit`` with no code (exits with the failing command's status),
  - ``true && pytest`` (prefix; pytest still runs and propagates).
"""

from __future__ import annotations

import re

_SUPPRESSION_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"^\s*(?:true|:)\s*$"),
     "the verify command is a no-op (`true`/`:`) — it proves nothing"),
    (re.compile(r"\|\|\s*(?:true\b|:|exit\s+0\b)"),
     "the verify command masks failure with `|| true` / `|| exit 0`"),
    (re.compile(r";\s*(?:true|:|exit\s+0)\s*$"),
     "the verify command ends in `; true` / `; exit 0`, forcing exit 0"),
    (re.compile(r"(?<![\w-])--no-verify\b"),
     "the verify command disables hooks (`--no-verify`)"),
    (re.compile(r"(?:^|\s)SKIP="),
     "the verify command skips hooks (`SKIP=`)"),
    (re.compile(r"(?:^|\s)HUSKY=0\b"),
     "the verify command disables hooks (`HUSKY=0`)"),
]


def is_suppressed_verification(command: object) -> str | None:
    """Return a reason string if the command is self-neutering, else None."""
    if not isinstance(command, str) or not command.strip():
        return None
    for pattern, reason in _SUPPRESSION_PATTERNS:
        if pattern.search(command):
            return reason
    return None
