#!/usr/bin/env python3
"""Derive a continuation-harness contract from a beads issue (fxh.10).

Collapses the write-side "triplicate authoring" lean violation: a unit of work no
longer needs its goal + oracle hand-authored a third time via
`init_contract.py --goal --verify`. Instead the bead declares its oracle ONCE, in
the place acceptance criteria already live, and the contract is derived from it.

Convention
----------
A bead declares its machine oracle as a fenced ```verify block inside its
`acceptance_criteria` (the text returned by `bd show <id> --json`):

    Creating a tracked task produces a valid harness contract with ZERO
    additional hand-authoring.

    ```verify
    python3 -m pytest harness/tests/test_contract_derivation.py -q
    ```

`goal` is taken from the bead title; `verification_command` is the extracted
command; `source` is "bead-derived".

Fail-closed (never-suppress + gate-design Rule 3)
-------------------------------------------------
A bead with no ```verify block — or a trivial one (`true` / `:` / `echo x`) —
raises OracleNotDeclared and writes NOTHING. Derivation never invents a passing
oracle; the same `is_trivial_oracle` guard that screens hand-authored contracts
screens derived ones, so there is one definition of "real oracle".

Claim binding (escapement-l9lo)
-------------------------------
A contract declared once used to keep passing for hours of unrelated later work,
and the agent wrote it itself. Now a successful `bd update <id> --claim` binds
the session to that bead (`active_bead.json`, latest claim wins) and freezes the
bead's oracle as the contract, recording a sha256 of the acceptance text. Then
`binding_problem` refuses a contract as proof when it is for another bead, was
declared before the claim, replaces a bead oracle, or the acceptance text has
changed since the freeze. Only an explicit `--refreeze` adopts rewritten text.
Sessions that never claim a bead keep agent-declared contracts unchanged.

Usage:
  derive_contract.py --bead <issue-id> [--refreeze]
  derive_contract.py --check     # exit 3 + reason if the contract is not valid proof
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from init_contract import (  # noqa: E402
    build_contract,
    is_evaporating_oracle,
    is_trivial_oracle,
)
from would_block_stop import InvalidActorIdentity, harness_home, thread_dir_for_session  # noqa: E402

# A fenced block whose info string is exactly `verify` (optionally surrounded by
# whitespace). The captured group is the command body. Non-greedy so the first
# block wins and the closing fence is the nearest one.
_VERIFY_BLOCK_RE = re.compile(
    r"```[ \t]*verify[ \t]*\r?\n(.*?)\r?\n```",
    re.DOTALL | re.IGNORECASE,
)


class BeadNotFound(Exception):
    """bd positively reports the bead does not exist (not an outage)."""


class OracleNotDeclared(Exception):
    """Raised when a bead declares no usable oracle — derivation fails closed."""


def extract_verify_oracle(acceptance_criteria: "str | None") -> "str | None":
    """Return the command inside the bead's ```verify block, or None if absent.

    Only a fence tagged `verify` counts — a plain ``` example block is ignored, so
    illustrative code in acceptance criteria is never mistaken for an oracle.
    """
    if not acceptance_criteria or not isinstance(acceptance_criteria, str):
        return None
    m = _VERIFY_BLOCK_RE.search(acceptance_criteria)
    if not m:
        return None
    command = m.group(1).strip()
    return command or None


def derive_contract(bead: dict, *, session_id: "str | None" = None) -> dict:
    """Build a contract dict from a bead record (shape of `bd show --json`[0]).

    Raises OracleNotDeclared if the bead declares no oracle or a trivial one — the
    caller must NOT fall back to writing a passing contract.
    """
    acceptance = bead.get("acceptance_criteria") or bead.get("acceptance")
    oracle = extract_verify_oracle(acceptance)
    if oracle is None:
        raise OracleNotDeclared(
            f"bead {bead.get('id', '<unknown>')!r} declares no ```verify oracle in its "
            "acceptance criteria. Add a fenced ```verify block whose command's exit code "
            "proves the outcome — derivation will not invent one."
        )
    trivial_reason = is_trivial_oracle(oracle)
    if trivial_reason is not None:
        raise OracleNotDeclared(
            f"bead {bead.get('id', '<unknown>')!r} ```verify oracle is not a real oracle: "
            f"{trivial_reason}"
        )
    # Same screen as the hand-authored path (escapement-v3mj), so "a real oracle"
    # has ONE definition regardless of which path wrote the contract.
    evaporating_reason = is_evaporating_oracle(oracle)
    if evaporating_reason is not None:
        raise OracleNotDeclared(
            f"bead {bead.get('id', '<unknown>')!r} ```verify oracle will not survive: "
            f"{evaporating_reason}"
        )

    goal = (bead.get("title") or "").strip()
    bead_id = bead.get("id")
    contract = build_contract(
        goal,
        oracle,
        source="bead-derived",
        session_id=session_id,
        thread_id=bead_id,
    )
    contract["bead_id"] = bead_id
    contract["acceptance_sha256"] = acceptance_sha256(bead)
    return contract


def acceptance_sha256(bead: dict) -> str:
    """Hash of the bead's verify COMMAND (not the whole acceptance text), so a prose
    edit is not a rewrite but any change to what actually runs is."""
    oracle = extract_verify_oracle(bead.get("acceptance_criteria") or bead.get("acceptance")) or ""
    return hashlib.sha256(oracle.encode("utf-8")).hexdigest()


def fetch_bead(bead_id: str) -> dict:
    """Fetch a bead record via `bd show <id> --json` (first element)."""
    proc = subprocess.run(
        ["bd", "show", bead_id, "--json"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        data = None
    # bd answers a missing id with a JSON error and exit 1; an outage prints no JSON.
    if (isinstance(data, dict) and "no issue" in str(data.get("error", "")).lower()) or data == []:
        raise BeadNotFound(f"bead {bead_id!r} not found")
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, proc.args, proc.stdout, proc.stderr)
    if data is None:
        raise ValueError(f"bd show {bead_id} did not return JSON")
    return data[0] if isinstance(data, list) else data


def main(argv: list[str], _fetch=fetch_bead) -> int:
    parser = argparse.ArgumentParser(description="Derive a harness contract from a bead.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--bead", help="Beads issue id to derive from.")
    mode.add_argument("--check", action="store_true",
                      help="Exit 3 with the reason if the contract is not proof for the active work.")
    parser.add_argument("--refreeze", action="store_true",
                        help="Adopt the bead's CURRENT acceptance text after it changed since claim.")
    args = parser.parse_args(argv)
    from bead_binding import (  # local: bead_binding imports this module
        ACTIVE_BEAD,
        _fetch_or_none,
        _read_json,
        _refrozen,
        _write_json,
        binding_problem,
    )

    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID")
    try:
        thread_dir = thread_dir_for_session(session_id, harness_home())
    except InvalidActorIdentity as exc:
        print(f"refusing to derive contract: invalid actor identity: {exc}", file=sys.stderr)
        return 2

    if args.check:
        problem = binding_problem(_read_json(thread_dir / "contract.json"), thread_dir, fetch=_fetch)
        if problem:
            print(f"contract is not proof for the active work: {problem}", file=sys.stderr)
            return 3
        return 0

    thread_dir.mkdir(parents=True, exist_ok=True)
    active_path = thread_dir / ACTIVE_BEAD
    active = _read_json(active_path) or {}
    is_active = active.get("bead_id") == args.bead
    frozen = active.get("acceptance_sha256") if is_active else None
    if active.get("bead_id") and not is_active:
        owed = dict(active.get("owed") or {})
        if args.refreeze and args.bead in owed:
            # Retire an owed oracle by explicit, recorded decision; the active
            # bead's contract is untouched.
            debt = owed.pop(args.bead)
            bead = _fetch_or_none(_fetch, args.bead) or {}
            oracle = extract_verify_oracle(bead.get("acceptance_criteria") or bead.get("acceptance"))
            log = list(active.get("refreezes") or [])
            log.append({
                "bead_id": args.bead,
                "at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
                "from_sha256": debt.get("acceptance_sha256"),
                "from_command": debt.get("command"),
                "to_sha256": None,
                "to_command": None,
                "retired_while_inactive": True,
                "current_oracle": oracle,
            })
            _write_json(active_path, dict(active, owed=owed, refreezes=log))
            print(f"owed oracle of bead {args.bead} retired by explicit refreeze (reported at Stop).")
            return 0
        print(
            f"refusing to derive contract: bead {args.bead} is not the active bead "
            f"({active['bead_id']}). Claim it first (`bd update {args.bead} --claim`)"
            + (", or retire its owed oracle with --refreeze." if args.bead in owed else "."),
            file=sys.stderr,
        )
        return 2

    try:
        bead = _fetch(args.bead)
        contract = derive_contract(bead, session_id=session_id)
    except OracleNotDeclared as exc:
        if args.refreeze and frozen:
            # The rewrite removed (or trivialised) the machine oracle. An explicit
            # refreeze releases the bead to an agent-declared contract instead of
            # trapping the session; the log keeps what the oracle used to be.
            _write_json(active_path, _refrozen(active, args.bead, None, None))
            print(f"bead {args.bead} no longer declares a usable oracle ({exc}); its "
                  "frozen oracle is released — declare this work's outcome with "
                  "init_contract.py.")
            return 0
        # Fail closed: write nothing, non-zero exit. The Stop gate stays blocked
        # rather than unlocking on a phantom oracle.
        print(f"refusing to derive contract: {exc}", file=sys.stderr)
        return 2
    except (BeadNotFound, subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError) as exc:
        print(f"could not read bead {args.bead!r}: {exc}", file=sys.stderr)
        return 1

    sha = contract["acceptance_sha256"]
    if frozen and frozen != sha:
        if not args.refreeze:
            print(
                f"refusing to derive contract: bead {args.bead}'s acceptance changed since "
                "it was claimed, so its oracle was rewritten mid-work. Restore the original "
                "text, or adopt the new oracle by explicit decision with --refreeze.",
                file=sys.stderr,
            )
            return 2
        contract["refrozen_from"] = frozen
        _write_json(active_path, _refrozen(active, args.bead, sha, contract["verification_command"]))
    elif is_active and not frozen:
        # A bead that gained an oracle after its claim (or whose claim-time lookup
        # failed) now owns the contract too.
        frozen_map = dict(active.get("frozen") or {}, **{args.bead: sha})
        _write_json(active_path, dict(
            active, acceptance_sha256=sha, command=contract["verification_command"],
            frozen=frozen_map, proven=False, freeze_pending=False))

    out = thread_dir / "contract.json"
    _write_json(out, contract)

    print(f"contract derived from {args.bead} -> {out}")
    print(json.dumps(contract, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
