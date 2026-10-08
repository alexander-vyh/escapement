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
A successful `bd update <id> --claim` binds the session to that bead and freezes
its oracle as the contract; bead_binding.py owns that binding and the invariant
that only a passing oracle, a recorded --refreeze/--retire, or the user saying
stop retires it. Sessions that never claim a bead keep agent-declared contracts.

Usage:
  derive_contract.py --bead <issue-id> [--refreeze]
  derive_contract.py --check     # exit 3 + reason if the contract is not valid proof
  derive_contract.py --retire    # end the bead binding by explicit, reported decision
"""

from __future__ import annotations

import argparse
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


def fetch_bead(bead_id: str, *, cwd: "str | None" = None, timeout: float = 10) -> dict:
    """Fetch a bead record via `bd show <id> --json` (first element), run in `cwd`.

    bd resolves its database from the working directory, so "no such bead" is
    only meaningful in the bead's own repo.
    """
    proc = subprocess.run(
        ["bd", "show", bead_id, "--json"],
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=timeout,
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
                      help="Exit 3 with the reason if the contract is not proof for the bound bead.")
    mode.add_argument("--retire", action="store_true",
                      help="End this session's bead binding by explicit decision (shown to the user).")
    parser.add_argument("--refreeze", action="store_true",
                        help="Adopt the bound bead's CURRENT oracle after it changed since claim.")
    args = parser.parse_args(argv)
    import bead_binding  # local: bead_binding imports this module

    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID")
    try:
        thread_dir = thread_dir_for_session(session_id, harness_home())
    except InvalidActorIdentity as exc:
        print(f"refusing to derive contract: invalid actor identity: {exc}", file=sys.stderr)
        return 2
    thread_dir.mkdir(parents=True, exist_ok=True)

    if args.check:
        contract = bead_binding.read_json(thread_dir / "contract.json")
        problem = bead_binding.binding_problem(contract, thread_dir)
        if problem:
            print(f"contract is not proof for the bound bead: {problem}", file=sys.stderr)
            return 3
        return 0
    if args.retire:
        return bead_binding.retire(thread_dir)
    if (bead_binding.read_json(thread_dir / bead_binding.ACTIVE_BEAD) or {}).get("bead_id"):
        return bead_binding.derive_bound(
            thread_dir, args.bead, refreeze=args.refreeze, session_id=session_id)

    try:
        contract = derive_contract(_fetch(args.bead), session_id=session_id)
    except OracleNotDeclared as exc:
        # Fail closed: write nothing, non-zero exit. The Stop gate stays blocked
        # rather than unlocking on a phantom oracle.
        print(f"refusing to derive contract: {exc}", file=sys.stderr)
        return 2
    except (BeadNotFound, subprocess.SubprocessError, ValueError) as exc:
        print(f"could not read bead {args.bead!r}: {exc}", file=sys.stderr)
        return 1
    out = thread_dir / "contract.json"
    bead_binding.write_json(out, contract)
    print(f"contract derived from {args.bead} -> {out}")
    print(json.dumps(contract, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
