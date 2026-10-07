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
    text = bead.get("acceptance_criteria") or bead.get("acceptance") or ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


ACTIVE_BEAD = "active_bead.json"


def _read_json(path: pathlib.Path) -> "dict | None":
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _write_json(path: pathlib.Path, value: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=2))
    os.replace(tmp, path)


def _parse_ts(value) -> "_dt.datetime | None":
    try:
        ts = _dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=_dt.timezone.utc)


_FETCH_ERRORS = (
    OracleNotDeclared,
    subprocess.CalledProcessError,
    subprocess.TimeoutExpired,
    ValueError,
    OSError,
)


def _fetch_or_none(fetch, bead_id: str) -> "dict | None":
    try:
        bead = fetch(bead_id)
    except _FETCH_ERRORS:
        return None
    return bead if isinstance(bead, dict) else None


def bind_claimed_bead(
    thread_dir: pathlib.Path,
    bead_id: str,
    *,
    session_id: "str | None" = None,
    fetch=None,
) -> None:
    """Record a successful claim; freeze the bead's oracle as the contract.

    Latest claim wins, unlike session_mode.json's first-claim scope: the active
    bead is what the session is working on NOW. Every bead's first freeze is kept
    for the life of the session (`frozen`), so re-claiming a bead — directly or
    after detouring through another — cannot launder a rewritten acceptance. A
    bead without an oracle still becomes active — that is what retires the
    previous bead's contract — and leaves the agent to declare.
    """
    fetch = fetch or fetch_bead
    thread_dir = pathlib.Path(thread_dir)
    previous = _read_json(thread_dir / ACTIVE_BEAD) or {}
    if previous.get("bead_id") == bead_id:
        return
    frozen = dict(previous.get("frozen") or {})
    record = {
        "bead_id": bead_id,
        "claimed_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "acceptance_sha256": frozen.get(bead_id),
        "frozen": frozen,
    }
    contract = None
    bead = _fetch_or_none(fetch, bead_id)
    if bead is not None:
        try:
            contract = derive_contract(bead, session_id=session_id)
        except OracleNotDeclared:
            contract = None
    if contract is not None:
        if record["acceptance_sha256"] in (None, contract["acceptance_sha256"]):
            record["acceptance_sha256"] = frozen[bead_id] = contract["acceptance_sha256"]
            record["command"] = contract["verification_command"]
        else:
            contract = None  # rewritten since its first freeze: binding_problem reports it
    _write_json(thread_dir / ACTIVE_BEAD, record)
    if contract is not None:
        _write_json(thread_dir / "contract.json", contract)


def _refrozen(active: dict, bead_id: str, sha: "str | None", command: "str | None") -> dict:
    """The active record after an explicit --refreeze, with an audit entry."""
    frozen_map = dict(active.get("frozen") or {})
    if sha:
        frozen_map[bead_id] = sha
    else:
        frozen_map.pop(bead_id, None)
    log = list(active.get("refreezes") or [])
    log.append({
        "at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "from_sha256": active.get("acceptance_sha256"),
        "from_command": active.get("command"),
        "to_sha256": sha,
        "to_command": command,
    })
    return dict(active, acceptance_sha256=sha, command=command, frozen=frozen_map,
                proven=False, refreezes=log)


def _rewritten(bead_id: str) -> str:
    return (
        f"bead {bead_id}'s acceptance text changed since its oracle was frozen — the "
        "oracle was rewritten mid-work. Restore the original acceptance, or adopt the "
        f"new one by explicit decision: `derive_contract.py --bead {bead_id} --refreeze`."
    )


def _declared_after_claim(contract: dict, active: dict) -> bool:
    declared = _parse_ts(contract.get("created_at"))
    claimed = _parse_ts(active.get("claimed_at"))
    return declared is not None and (claimed is None or declared >= claimed)


def mark_proven(thread_dir: pathlib.Path, contract) -> None:
    """After a green verify: the active bead's frozen oracle has passed."""
    path = pathlib.Path(thread_dir) / ACTIVE_BEAD
    active = _read_json(path)
    if (
        active
        and isinstance(contract, dict)
        and active.get("acceptance_sha256")
        and contract.get("bead_id") == active.get("bead_id")
        and contract.get("acceptance_sha256") == active["acceptance_sha256"]
    ):
        _write_json(path, dict(active, proven=True))


def _released(active: dict, bead: "dict | None") -> bool:
    """A closed bead whose frozen oracle passed has done its job; what follows is
    unclaimed work the agent may declare for. Closing it unproven releases nothing,
    or one tracker action would hand the agent back its own exam."""
    return bool(active.get("proven")) and bead is not None and bead.get("status") == "closed"


def oracle_in_force(thread_dir: pathlib.Path, *, fetch=None) -> "str | None":
    """The active bead whose frozen oracle IS the contract, or None."""
    active = _read_json(pathlib.Path(thread_dir) / ACTIVE_BEAD) or {}
    active_id = active.get("bead_id")
    if not active_id or not active.get("acceptance_sha256"):
        return None
    if _released(active, _fetch_or_none(fetch or fetch_bead, active_id)):
        return None
    return active_id


def binding_problem(contract, thread_dir: pathlib.Path, *, fetch=None) -> "str | None":
    """Why `contract` cannot stand as proof for the session's active work, or None.

    Fails open only on an unreadable bead (bd down must not trap a session);
    every comparison that can be made is made.
    """
    if not isinstance(contract, dict):
        return None
    fetch = fetch or fetch_bead
    active = _read_json(pathlib.Path(thread_dir) / ACTIVE_BEAD) or {}
    active_id = active.get("bead_id")
    frozen = active.get("acceptance_sha256")
    bound_id = contract.get("bead_id")
    command = (contract.get("verification_command") or "").strip()

    if active_id and frozen:
        bead = _fetch_or_none(fetch, active_id)
        released = _released(active, bead)
        if not released and bead is not None and acceptance_sha256(bead) != frozen:
            return _rewritten(active_id)
        if bound_id == active_id and not released:
            oracle = extract_verify_oracle(
                (bead or {}).get("acceptance_criteria") or (bead or {}).get("acceptance")
            )
            if contract.get("acceptance_sha256") != frozen or (
                bead is not None and oracle != command
            ):
                return (
                    f"this contract is not bead {active_id}'s oracle as frozen at claim. "
                    f"Run `derive_contract.py --bead {active_id}` to restore it."
                )
            return None
        if not released:
            return (
                f"bead {active_id} declares its own ```verify oracle, so it is the "
                f"contract; this contract ({contract.get('source', 'unknown source')}"
                f"{', bead ' + bound_id if bound_id else ''}) cannot replace it. Run "
                f"`derive_contract.py --bead {active_id}` to restore it."
            )
    if active_id and frozen and bound_id == active_id:
        return None  # the released bead's own oracle, already proven
    if active_id and bound_id != active_id:  # also reached once a proven bead closes
        if bound_id:
            return (
                f"this contract proves bead {bound_id}, but the active bead is {active_id}. "
                f"Declare {active_id}'s outcome (init_contract.py) or add a ```verify "
                f"block to its acceptance and run `derive_contract.py --bead {active_id}`."
            )
        if not _declared_after_claim(contract, active):
            return (
                f"this contract was declared before bead {active_id} was claimed, so "
                f"it describes earlier work. Declare {active_id}'s outcome "
                "(init_contract.py) or add a ```verify block to its acceptance."
            )
        return None
    if bound_id and contract.get("acceptance_sha256"):
        bead = _fetch_or_none(fetch, bound_id)
        if bead is not None and acceptance_sha256(bead) != contract["acceptance_sha256"]:
            return _rewritten(bound_id)
    return None


def fetch_bead(bead_id: str) -> dict:
    """Fetch a bead record via `bd show <id> --json` (first element)."""
    proc = subprocess.run(
        ["bd", "show", bead_id, "--json"],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    data = json.loads(proc.stdout)
    if isinstance(data, list):
        if not data:
            raise OracleNotDeclared(f"bead {bead_id!r} not found")
        return data[0]
    return data


def main(argv: list[str], _fetch=fetch_bead) -> int:
    parser = argparse.ArgumentParser(description="Derive a harness contract from a bead.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--bead", help="Beads issue id to derive from.")
    mode.add_argument("--check", action="store_true",
                      help="Exit 3 with the reason if the contract is not proof for the active work.")
    mode.add_argument("--proven", action="store_true",
                      help="Record that the active bead's frozen oracle passed (called by verify).")
    parser.add_argument("--refreeze", action="store_true",
                        help="Adopt the bead's CURRENT acceptance text after it changed since claim.")
    args = parser.parse_args(argv)

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

    if args.proven:
        mark_proven(thread_dir, _read_json(thread_dir / "contract.json"))
        return 0

    thread_dir.mkdir(parents=True, exist_ok=True)
    active_path = thread_dir / ACTIVE_BEAD
    active = _read_json(active_path) or {}
    is_active = active.get("bead_id") == args.bead
    frozen = active.get("acceptance_sha256") if is_active else None

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
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
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
        # A bead that gained an oracle after its claim now owns the contract too.
        frozen_map = dict(active.get("frozen") or {}, **{args.bead: sha})
        _write_json(active_path, dict(
            active, acceptance_sha256=sha, command=contract["verification_command"],
            frozen=frozen_map, proven=False))

    out = thread_dir / "contract.json"
    _write_json(out, contract)

    print(f"contract derived from {args.bead} -> {out}")
    print(json.dumps(contract, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
