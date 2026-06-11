#!/usr/bin/env python3
"""Blocker verification and waiver validation for the stop-gate (R3).

A blocked bead is only a legitimate stop-gate release when the blocker claim is
substantiated:
  - `blocker-verify: <cmd>` — a shell command that exits 0 within a bounded timeout.
    Trivial commands (true / : / exit 0 / empty) are rejected WITHOUT execution
    (value-not-presence, gate-design Rule 3).
  - `blocker-waiver: <reason>` — a human-readable reason ≥20 chars and not a
    placeholder ("tbd", "n/a", "todo", ...).

A bead is `blocker_satisfied` iff it carries a passing verify OR a valid waiver.
A bare prose blocker claim satisfies neither and is always unsatisfied.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import Optional

# ---------------------------------------------------------------------------
# Trivial-command rejection set (value-not-presence, gate-design Rule 3).
# These would exit 0 if run, but they prove nothing — they are the exact
# bypass a presence-only implementation would accept.
#
# F2 (verifier Finding 2): the original narrow set {"true", ":", "exit 0"} is
# bypassed by path-qualified variants (/bin/true, /usr/bin/true), shell-decorated
# variants (true 2>/dev/null), compounds (true && true), and always-true bracket
# expressions ([ 0 -eq 0 ]). The set is extended and the normaliser strips the
# common wrappings before matching.
# ---------------------------------------------------------------------------
_TRIVIAL_COMMANDS = frozenset({
    "true", ":", "exit 0",
    # path-qualified variants of true
    "/bin/true", "/usr/bin/true",
    # always-true bracket / arithmetic expressions
    "[ 0 -eq 0 ]", "test 0 -eq 0",
})

# Regex patterns for compound no-op structures that are semantically trivial.
# Any command matching one of these is rejected without execution.
_TRIVIAL_COMPOUND_RE = re.compile(
    r"^(?:"
    r"(?:/\S+/)?true\s*(?:&&\s*(?:/\S+/)?true\s*)*"  # true && true (chained)
    r"|(?:/\S+/)?true\s+2>/dev/null"                  # true 2>/dev/null
    r"|exit\s+0\s*$"                                  # exit 0 (with optional space)
    r")\s*$",
    re.IGNORECASE,
)


def _is_trivial_command(cmd: str) -> bool:
    """Return True if cmd is a trivially passing no-op that proves nothing.

    Normalisation: strip whitespace and trailing semicolons before comparing,
    then do a case-insensitive membership check against the trivial set.
    Then check compound no-op patterns.
    """
    if not cmd or not cmd.strip():
        return True
    normalised = cmd.strip().rstrip(";").strip().lower()
    if not normalised:
        return True
    if normalised in _TRIVIAL_COMMANDS:
        return True
    if _TRIVIAL_COMPOUND_RE.match(normalised):
        return True
    # Always-true bracket: [ <n> -eq <n> ] or [ 1 -eq 1 ] etc.
    if re.match(r"^\[\s*(\d+)\s*-eq\s*\1\s*\]$", normalised):
        return True
    return False


# ---------------------------------------------------------------------------
# Placeholder waiver patterns.
# ---------------------------------------------------------------------------
_PLACEHOLDER_WAIVER = re.compile(
    r"^\s*(tbd|todo|n/?a|na|none|\?+)\s*$",
    re.IGNORECASE,
)
_WAIVER_MIN_CHARS = 20


@dataclass
class VerifyResult:
    """Outcome of a verify or waiver check."""
    confirmed: bool
    reason: str  # short machine-readable tag for logging


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def verify_command(cmd: Optional[str], timeout: int = 10) -> VerifyResult:
    """Run a `blocker-verify:` shell command and return a VerifyResult.

    Rejects trivial commands (true / : / exit 0 / empty) WITHOUT execution.
    A real command that exits 0 within `timeout` seconds is confirmed.
    Any non-zero exit, timeout, or execution error is unverified.
    """
    if not cmd or not cmd.strip():
        return VerifyResult(confirmed=False, reason="no_command")
    if _is_trivial_command(cmd):
        return VerifyResult(confirmed=False, reason="trivial_command")
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return VerifyResult(confirmed=True, reason="exit_0")
        return VerifyResult(confirmed=False, reason="nonzero_exit")
    except subprocess.TimeoutExpired:
        return VerifyResult(confirmed=False, reason="timeout")
    except (OSError, ValueError):
        return VerifyResult(confirmed=False, reason="exec_error")


def valid_waiver(reason: Optional[str]) -> bool:
    """Return True iff reason is a substantive, non-placeholder waiver.

    Requirements: not None/empty, not a known placeholder, ≥20 characters.
    """
    if not reason or not isinstance(reason, str):
        return False
    stripped = reason.strip()
    if not stripped:
        return False
    if _PLACEHOLDER_WAIVER.match(stripped):
        return False
    if len(stripped) < _WAIVER_MIN_CHARS:
        return False
    return True


@dataclass
class BlockerSpec:
    """Parsed blocker annotations from a bead's description text."""
    verify_command: Optional[str]
    waiver_reason: Optional[str]


def parse_blocker_spec(text: Optional[str]) -> BlockerSpec:
    """Parse `blocker-verify:` and `blocker-waiver:` lines from a bead's text.

    Only the FIRST occurrence of each key is extracted.  A bare prose blocker
    claim yields BlockerSpec(verify_command=None, waiver_reason=None), which
    the gate treats as unverified.
    """
    verify_cmd: Optional[str] = None
    waiver_rsn: Optional[str] = None
    if not text or not isinstance(text, str):
        return BlockerSpec(verify_command=None, waiver_reason=None)
    for line in text.splitlines():
        stripped = line.strip()
        if verify_cmd is None and stripped.lower().startswith("blocker-verify:"):
            verify_cmd = stripped[len("blocker-verify:"):].strip() or None
        elif waiver_rsn is None and stripped.lower().startswith("blocker-waiver:"):
            waiver_rsn = stripped[len("blocker-waiver:"):].strip() or None
    return BlockerSpec(verify_command=verify_cmd, waiver_reason=waiver_rsn)


def blocker_satisfied(bead: dict) -> VerifyResult:
    """Return a VerifyResult indicating whether a blocked bead's claim is satisfied.

    A bead is satisfied iff:
      - its `blocker-verify:` command exits 0 (not trivial), OR
      - its `blocker-waiver:` reason is valid (≥20 chars, non-placeholder).

    A bare prose claim (no verify, no waiver) is never satisfied.
    """
    description = bead.get("description") or ""
    spec = parse_blocker_spec(description)

    if spec.verify_command is not None:
        result = verify_command(spec.verify_command)
        if result.confirmed:
            return result
        # verify present but failed — fall through to waiver check

    if spec.waiver_reason is not None and valid_waiver(spec.waiver_reason):
        return VerifyResult(confirmed=True, reason="valid_waiver")

    return VerifyResult(confirmed=False, reason="unverified_claim")
