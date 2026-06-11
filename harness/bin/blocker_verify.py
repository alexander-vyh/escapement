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
# Semantic no-op detection (value-not-presence, gate-design Rule 3).
#
# A trivial command is one whose every "atomic" component is a known no-op
# after stripping wrappers and decomposing on shell operators.  We use a
# recursive semantic normaliser rather than an enumeration because an
# enumeration is always bypassable by novel compositions (confirmed canaries:
# `:|:`, `{ true; }`).
#
# Atomic no-ops (the closed base set):
#   true, :, exit 0
#   path-qualified: /bin/true, /usr/bin/true, ...
#   always-true expressions: [ n -eq n ], (( 1 ))
#
# Wrapper stripping (recursive):
#   env/command [assignments/flags] <cmd>  →  strip prefix, recurse on <cmd>
#   exec <cmd>                             →  strip exec, recurse on <cmd>
#   sh -c <cmd> / bash -c <cmd>           →  recurse on the -c argument
#   ( <cmd> ) or { <cmd>; }               →  recurse on inner content
#
# Decomposition (all parts must be trivial):
#   cmd1 && cmd2, cmd1 || cmd2, cmd1 ; cmd2, cmd1 | cmd2  →  check each part
#
# Named fragile implementation (the test's stated canary): a pure frozenset
# expansion of the named 8 strings (command true / env true / etc.) cannot
# catch `:|:` or `{ true; }` without knowing what `:` means in composition.
# ---------------------------------------------------------------------------

# Atomic no-ops after all wrappers are stripped (normalised lowercase).
_ATOMIC_NOOP_EXACT = frozenset({
    "true", ":", "exit 0", "exit",
})

# Path-qualified variants of `true` (case-insensitive).
_PATH_TRUE_RE = re.compile(r"^(/[^/\s]+)*/true$", re.IGNORECASE)

# Always-true bracket: [ n -eq n ] or [ n == n ] — same literal on both sides.
_BRACKET_TRUE_RE = re.compile(
    r"^\[\s*([^\s\]]+)\s*(?:-eq|==)\s*\1\s*\]$"
)

# Shell operators that separate commands for decomposition.
# Note: split on || and && before ; and |, so longer tokens match first.
_OP_SPLIT_RE = re.compile(r"&&|\|\||[;|\n]")

# Shell redirections to strip before atom-checking (e.g. 2>/dev/null, >/tmp/x).
_REDIRECT_RE = re.compile(r"\d*(?:>>|>&?|<&?|<<)(?:\S+)")

# Tokens/prefixes that wrap another command without changing its semantics.
_WRAPPER_CMDS = frozenset({"env", "command", "exec"})

# Name=value assignment at start of token.
_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _is_atomic_noop(atom: str) -> bool:
    """Return True iff `atom` (stripped, lowercased) is a known atomic no-op.

    Strips shell redirections (e.g. 2>/dev/null) before checking, since they
    do not change the semantic no-op nature of the command.
    """
    atom = atom.strip().rstrip(";").strip()
    if not atom:
        return True  # empty is trivially a no-op
    # Strip shell redirections before comparing (e.g. true 2>/dev/null → true).
    atom = _REDIRECT_RE.sub("", atom).strip()
    if not atom:
        return True
    low = atom.lower()
    if low in _ATOMIC_NOOP_EXACT:
        return True
    if _PATH_TRUE_RE.match(low):
        return True
    if _BRACKET_TRUE_RE.match(atom):
        return True
    # (( 1 )) or (( 0 == 0 )) — arithmetic always-true; treat as trivial.
    if re.match(r"^\(\(\s*\d+\s*\)\)$", atom):
        return True
    return False


def _is_trivial_command(cmd: str) -> bool:  # noqa: C901 — readable is worth more
    """Return True iff cmd is a semantically trivial no-op that proves nothing.

    Uses a recursive semantic normaliser: strip wrappers, decompose on shell
    operators, check every atom.  Fails safe (returns False) on any input that
    does not match a known trivial pattern so substantive commands are never
    over-rejected.
    """
    if not cmd or not cmd.strip():
        return True

    cmd = cmd.strip()

    # ---------------------------------------------------------------
    # Step 1 — strip outer brace group  { ...; }  →  recurse on inner
    # ---------------------------------------------------------------
    if cmd.startswith("{") and cmd.endswith("}"):
        inner = cmd[1:-1].strip().rstrip(";").strip()
        if inner:
            return _is_trivial_command(inner)

    # ---------------------------------------------------------------
    # Step 2 — strip outer subshell  ( ... )  →  recurse on inner
    # (Only when the parentheses are the outermost shell structure, not
    # part of a compound expression like `(true) && something`.)
    # ---------------------------------------------------------------
    if cmd.startswith("(") and cmd.endswith(")"):
        inner = cmd[1:-1].strip()
        if inner:
            return _is_trivial_command(inner)

    # ---------------------------------------------------------------
    # Step 3 — decompose on shell operators  &&  ||  ;  |
    #
    # For ||: if the LEFT operand is trivially a no-op (true/:), the
    # right-hand side never executes — the whole expression is trivial.
    # This catches `true||false`: `true` always succeeds so `false` is
    # dead code, providing no real verification.
    #
    # For &&, ;, |: every part must be trivial for the whole to be trivial.
    # ---------------------------------------------------------------
    # Handle || specially before the generic split.
    if "||" in cmd:
        # Split only on ||, check if first part is trivially a no-op.
        or_parts = [p.strip() for p in re.split(r"\|\|", cmd) if p.strip()]
        if or_parts and _is_trivial_command(or_parts[0]):
            return True
        # If neither first trivial check works, fall through to all-parts check.
        if all(_is_trivial_command(p) for p in or_parts if p.strip()):
            return True
    parts = [p.strip() for p in _OP_SPLIT_RE.split(cmd) if p.strip()]
    if len(parts) > 1:
        return all(_is_trivial_command(p) for p in parts)

    # Single segment from here on.
    # ---------------------------------------------------------------
    # Step 4 — tokenize the segment (fail safe on shlex errors)
    # ---------------------------------------------------------------
    try:
        import shlex
        tokens = shlex.split(cmd)
    except ValueError:
        return False  # unparseable → treat as substantive (fail safe)

    if not tokens:
        return True

    # ---------------------------------------------------------------
    # Step 5 — strip leading wrapper commands (env, command, exec)
    # and env-var assignments, then recurse on the effective command.
    # ---------------------------------------------------------------
    i = 0
    # Strip leading env-var assignments (NAME=VALUE tokens).
    while i < len(tokens) and _ASSIGN_RE.match(tokens[i]):
        i += 1
    if i >= len(tokens):
        return True  # only assignments — no effective command

    # Strip `env`/`command`/`exec` wrappers.
    while i < len(tokens) and tokens[i].lower() in _WRAPPER_CMDS:
        i += 1
        # Skip any flags/assignments that follow the wrapper.
        while i < len(tokens) and (
            _ASSIGN_RE.match(tokens[i]) or tokens[i].startswith("-")
        ):
            # Flags with a value argument (-u NAME, -i, -S ..., --arg=val).
            if tokens[i] in ("-u", "-S") and i + 1 < len(tokens):
                i += 2
            else:
                i += 1
        if i >= len(tokens):
            return True  # wrapper with no effective command

    # After stripping, check if the remainder is `sh -c <cmd>` or `bash -c <cmd>`.
    if i < len(tokens) and tokens[i].lower() in ("sh", "bash", "dash", "zsh"):
        # Look for a `-c` flag followed by a command string to recurse on.
        j = i + 1
        # Skip any shell flags before -c.
        while j < len(tokens) and tokens[j].startswith("-") and tokens[j] != "-c":
            j += 1
        if j < len(tokens) and tokens[j] == "-c" and j + 1 < len(tokens):
            return _is_trivial_command(tokens[j + 1])
        # No -c found — fall through to atom check on the shell name itself.

    # Rejoin remaining tokens into the effective command and atom-check.
    effective = " ".join(tokens[i:])
    return _is_atomic_noop(effective)


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
