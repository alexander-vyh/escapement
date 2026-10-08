#!/usr/bin/env python3
"""A claimed bead's frozen oracle, and the debts it leaves (escapement-l9lo).

derive_contract.py turns a bead into a contract; this module keeps the session's
binding to beads in `active_bead.json` and decides when a contract may stand as
proof for the work.

State, one file per thread dir:
  bead_id / claimed_at       the active bead (latest successful claim wins)
  acceptance_sha256, command its oracle as frozen at claim (frozen_at: when)
  freeze_pending             bd could not be read at claim; frozen on the next read
  proven / proven_sha256     the frozen oracle's last verify run was green
  frozen                     every bead's first freeze this session (no laundering)
  owed                       beads left behind whose oracle never passed, or was
                             never readable (`pending`) — debts exactly like the
                             active bead's own
  refreezes                  explicit --refreeze and late-freeze audit entries,
                             shown to the human once

A pending freeze or an owed oracle blocks Stop whether or not contract.json
exists. While bd stays unreadable the only exits are the user saying "stop" or,
once bd answers, an explicit `derive_contract.py --bead <id> --refreeze`; a bead
bd positively reports as missing (a typo, a rejected claim) is never bound.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from derive_contract import (  # noqa: E402
    BeadNotFound,
    OracleNotDeclared,
    acceptance_sha256,
    derive_contract,
    extract_verify_oracle,
    fetch_bead,
)

ACTIVE_BEAD = "active_bead.json"


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _read_json(path: pathlib.Path) -> "dict | None":
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _write_json(path: pathlib.Path, value: dict) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        json.dump(value, f, indent=2)
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


def _lookup(fetch, bead_id: str) -> "tuple[dict | None, bool]":
    """(bead, missing): missing only when bd positively reports no such bead."""
    try:
        bead = fetch(bead_id)
    except BeadNotFound:
        return None, True
    except _FETCH_ERRORS:
        return None, False
    return (bead if isinstance(bead, dict) else None), False


def _fetch_or_none(fetch, bead_id: str) -> "dict | None":
    return _lookup(fetch, bead_id)[0]


def _oracle_of(bead: "dict | None") -> "str | None":
    bead = bead or {}
    return extract_verify_oracle(bead.get("acceptance_criteria") or bead.get("acceptance"))


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
    after detouring through another — cannot launder a rewritten acceptance. The
    bead being left behind keeps its debt: an unproven oracle, or one never
    readable, moves to `owed`. A bead without an oracle still becomes active —
    that is what retires the previous bead's contract — and leaves the agent to
    declare.
    """
    fetch = fetch or fetch_bead
    thread_dir = pathlib.Path(thread_dir)
    previous = _read_json(thread_dir / ACTIVE_BEAD) or {}
    if previous.get("bead_id") == bead_id:
        if previous.get("freeze_pending"):
            _settle_pending(thread_dir, fetch, session_id=session_id)
        return
    bead, missing = _lookup(fetch, bead_id)
    if missing:
        print(
            f"derive_contract: bd reports no bead {bead_id}, so the claim is not bound; "
            "the session's binding is unchanged.",
            file=sys.stderr,
        )
        return
    if previous.get("freeze_pending"):
        _settle_pending(thread_dir, fetch, session_id=session_id)
        previous = _read_json(thread_dir / ACTIVE_BEAD) or {}
    owed = dict(previous.get("owed") or {})
    prev_id = previous.get("bead_id")
    if prev_id and previous.get("freeze_pending"):
        owed[prev_id] = {"pending": True, "claimed_at": previous.get("claimed_at")}
    elif prev_id and previous.get("acceptance_sha256") and not previous.get("proven"):
        # Leaving a bead whose frozen oracle never passed does not cancel it:
        # closing it and claiming a throwaway would hand the agent its own exam.
        owed[prev_id] = {
            "acceptance_sha256": previous["acceptance_sha256"],
            "command": previous.get("command"),
        }
    owed.pop(bead_id, None)  # active again: its debt is the active record's
    frozen = dict(previous.get("frozen") or {})
    record = {
        "bead_id": bead_id,
        "claimed_at": _now(),
        "acceptance_sha256": frozen.get(bead_id),
        "frozen": frozen,
        "owed": owed,
        "refreezes": list(previous.get("refreezes") or []),
        "freeze_pending": True,
    }
    _write_json(thread_dir / ACTIVE_BEAD, record)
    if not _settle_pending(thread_dir, fetch, session_id=session_id, bead=bead, at_claim=True):
        print(
            f"derive_contract: could not read bead {bead_id} at claim, so its ```verify "
            "oracle is not frozen yet. It will be frozen on the next check once bd answers; "
            "until then Stop stays blocked and no agent-declared contract is accepted for it.",
            file=sys.stderr,
        )


def _late_entry(bead_id: str, bead: dict, claimed_at, command: "str | None") -> "dict | None":
    """An audit entry when a late freeze adopted text edited after the claim."""
    updated = _parse_ts(bead.get("updated_at"))
    claimed = _parse_ts(claimed_at)
    if updated is None or claimed is None or updated <= claimed:
        return None
    return {
        "bead_id": bead_id,
        "at": _now(),
        "late_freeze": True,
        "updated_at": bead.get("updated_at"),
        "claimed_at": claimed_at,
        "to_command": command,
    }


def _settle_owed(active: dict, fetch) -> "dict | None":
    """Freeze owed debts that were never readable. Returns the new record or None."""
    owed = dict(active.get("owed") or {})
    pending = [oid for oid, debt in owed.items() if isinstance(debt, dict) and debt.get("pending")]
    if not pending:
        return None
    frozen = dict(active.get("frozen") or {})
    log = list(active.get("refreezes") or [])
    changed = False
    for oid in pending:
        bead, missing = _lookup(fetch, oid)
        if bead is None and not missing:
            continue  # still unreadable: stays a pending debt
        changed = True
        try:
            contract = derive_contract(bead) if bead is not None else None
        except OracleNotDeclared:
            contract = None
        if contract is None:
            owed.pop(oid)  # bd says it has no usable oracle (or no bead): nothing was owed
            continue
        sha, command = contract["acceptance_sha256"], contract["verification_command"]
        frozen.setdefault(oid, sha)
        owed[oid] = {"acceptance_sha256": frozen[oid], "command": command, "frozen_at": _now()}
        entry = _late_entry(oid, bead, owed[oid].get("claimed_at") or active.get("claimed_at"), command)
        if entry:
            log.append(entry)
    return dict(active, owed=owed, frozen=frozen, refreezes=log) if changed else None


def _settle_pending(
    thread_dir: pathlib.Path,
    fetch=None,
    *,
    session_id=None,
    bead: "dict | None" = None,
    at_claim: bool = False,
) -> bool:
    """Freeze what the claim-time lookup could not: the active bead and owed debts.

    One bd timeout at claim must not unbind the bead, so the freeze is retried on
    re-claim and lazily on every check. A late freeze of text edited after the
    claim is logged for the human. Returns False only while the active bead is
    still unreadable.
    """
    fetch = fetch or fetch_bead
    path = pathlib.Path(thread_dir) / ACTIVE_BEAD
    active = _read_json(path)
    if not active:
        return True
    settled = _settle_owed(active, fetch)
    if settled is not None:
        active = settled
        _write_json(path, active)
    if not active.get("freeze_pending"):
        return True
    bead_id = active["bead_id"]
    if bead is None:
        bead, missing = _lookup(fetch, bead_id)
        if missing:  # deleted since the claim: nothing to freeze, nothing owed
            _write_json(path, dict(active, freeze_pending=False))
            return True
    if bead is None:
        return False
    record = dict(active, freeze_pending=False)
    contract = None
    try:
        contract = derive_contract(bead, session_id=session_id)
    except OracleNotDeclared:
        contract = None
    if contract is not None:
        frozen = dict(record.get("frozen") or {})
        if record.get("acceptance_sha256") in (None, contract["acceptance_sha256"]):
            record["acceptance_sha256"] = frozen[bead_id] = contract["acceptance_sha256"]
            record["command"] = contract["verification_command"]
            record["frozen"] = frozen
            record["frozen_at"] = _now()
            entry = None if at_claim else _late_entry(
                bead_id, bead, record.get("claimed_at"), record["command"])
            if entry:
                record["refreezes"] = list(record.get("refreezes") or []) + [entry]
        else:
            contract = None  # rewritten since its first freeze: binding_problem reports it
    _write_json(path, record)
    if contract is not None:
        _write_json(pathlib.Path(thread_dir) / "contract.json", contract)
    return True


def _refrozen(active: dict, bead_id: str, sha: "str | None", command: "str | None") -> dict:
    """The active record after an explicit --refreeze, with an audit entry."""
    frozen_map = dict(active.get("frozen") or {})
    if sha:
        frozen_map[bead_id] = sha
    else:
        frozen_map.pop(bead_id, None)
    log = list(active.get("refreezes") or [])
    log.append({
        "bead_id": bead_id,
        "at": _now(),
        "from_sha256": active.get("acceptance_sha256"),
        "from_command": active.get("command"),
        "to_sha256": sha,
        "to_command": command,
    })
    owed = dict(active.get("owed") or {})
    owed.pop(bead_id, None)
    return dict(active, acceptance_sha256=sha, command=command, frozen=frozen_map,
                proven=False, refreezes=log, owed=owed)


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


def mark_proven(thread_dir: pathlib.Path, *, fetch=None) -> None:
    """Record what the on-disk contract's LAST RUN says about the active bead's oracle.

    Reads contract.json itself, so no caller can hand it a contract to judge:
    `proven` becomes true only when that file's last_run is a fresh, unsuppressed
    pass (the same test the Stop gate applies) of exactly the frozen command,
    against a readable bead. Any other run of the bound oracle — a red one
    included — clears it. Editing the state files directly is out of scope.
    """
    path = pathlib.Path(thread_dir) / ACTIVE_BEAD
    active = _read_json(path)
    contract = _read_json(pathlib.Path(thread_dir) / "contract.json")
    if not (
        active
        and contract
        and active.get("acceptance_sha256")
        and contract.get("bead_id") == active.get("bead_id")
    ):
        return
    from would_block_stop import _verification_passed_this_turn  # local: import cycle

    bead = _fetch_or_none(fetch or fetch_bead, active["bead_id"])
    proven = (
        _verification_passed_this_turn(contract)
        and contract.get("expected_exit", 0) == 0
        and contract.get("acceptance_sha256") == active["acceptance_sha256"]
        and contract.get("verification_command") == active.get("command")
        and bead is not None
        and acceptance_sha256(bead) == active["acceptance_sha256"]
        and _oracle_of(bead) == contract.get("verification_command")
    )
    if proven:
        _write_json(path, dict(active, proven=True, proven_sha256=active["acceptance_sha256"]))
    elif active.get("proven"):
        _write_json(path, dict(active, proven=False, proven_sha256=None))


def _describe(entry: dict) -> str:
    bead_id = entry.get("bead_id", "?")
    if entry.get("late_freeze"):
        return (
            f"{bead_id}: frozen late as `{entry.get('to_command')}` — bd was unreadable "
            f"at claim and the bead was edited after it (updated {entry.get('updated_at')})"
        )
    if entry.get("retired_while_inactive"):
        return f"{bead_id}: `{entry.get('from_command')}` abandoned unproven (never passed)"
    return (
        f"{bead_id}: `{entry.get('from_command')}` -> "
        f"`{entry.get('to_command') or '(oracle removed; agent-declared contract)'}`"
    )


def refreeze_notice(thread_dir: pathlib.Path) -> "str | None":
    """Oracle changes not yet shown to the human, as one sentence; marks them shown.

    Settles a pending freeze first, so every Stop path — not only the contract
    gate — freezes once bd answers and reports a late freeze the same turn.
    """
    _settle_pending(thread_dir)
    path = pathlib.Path(thread_dir) / ACTIVE_BEAD
    active = _read_json(path)
    if not active:
        return None
    log = list(active.get("refreezes") or [])
    fresh = [entry for entry in log if isinstance(entry, dict) and not entry.get("reported")]
    if not fresh:
        return None
    parts = [_describe(entry) for entry in fresh]
    for entry in fresh:
        entry["reported"] = True
    _write_json(path, dict(active, refreezes=log))
    return (
        "continuation-harness: a bead's frozen oracle was changed outside a normal claim "
        "this session (--refreeze or a late freeze) — " + "; ".join(parts)
        + ". Check that this still proves the outcome."
    )


def _released(active: dict, bead: "dict | None") -> bool:
    """A closed bead whose frozen oracle passed has done its job; what follows is
    unclaimed work the agent may declare for. Closing it unproven releases nothing,
    or one tracker action would hand the agent back its own exam."""
    return (
        bool(active.get("proven"))
        and bead is not None
        and bead.get("status") == "closed"
        # a rewrite after the proof (even to a stronger oracle) is unproven
        and acceptance_sha256(bead) == active.get("proven_sha256")
    )


def oracle_in_force(thread_dir: pathlib.Path, *, fetch=None) -> "str | None":
    """The active bead whose frozen oracle IS the contract (or whose oracle is not
    known yet because bd was unreadable at claim), or None."""
    _settle_pending(thread_dir, fetch)
    active = _read_json(pathlib.Path(thread_dir) / ACTIVE_BEAD) or {}
    active_id = active.get("bead_id")
    if active_id and active.get("freeze_pending"):
        return active_id
    if not active_id or not active.get("acceptance_sha256"):
        return None
    if _released(active, _fetch_or_none(fetch or fetch_bead, active_id)):
        return None
    return active_id


def _debt(active: dict) -> "str | None":
    """An open debt that no contract can discharge: a pending freeze or owed oracles."""
    if active.get("freeze_pending"):
        return (
            f"bead {active.get('bead_id')}'s ```verify oracle could not be read when it "
            "was claimed (bd unavailable), so nothing can stand in for it yet. Retry once "
            f"bd answers: `derive_contract.py --bead {active.get('bead_id')}`."
        )
    owed = active.get("owed") or {}
    if owed:
        names = ", ".join(
            oid + (" (oracle not yet readable)" if isinstance(debt, dict) and debt.get("pending") else "")
            for oid, debt in sorted(owed.items())
        )
        return (
            f"bead(s) {names} were left with a frozen ```verify oracle that never passed. "
            "Re-claim each (`bd update <id> --claim`) and make its oracle pass, or retire "
            "it by explicit decision with `derive_contract.py --bead <id> --refreeze` "
            "(reported to the user at Stop)."
        )
    return None


def binding_problem(contract, thread_dir: pathlib.Path, *, fetch=None) -> "str | None":
    """Why the session may not stop on `contract` (None when contract.json is absent
    or unreadable) given its bead binding, or None.

    A pending freeze, an owed oracle, or a bound oracle that never passed blocks
    whether or not a contract exists. Comparisons that need an unreadable bead
    are skipped; the debts above are not, so a bd outage holds a bound session
    until bd answers or the user says "stop".
    """
    fetch = fetch or fetch_bead
    _settle_pending(thread_dir, fetch)
    active = _read_json(pathlib.Path(thread_dir) / ACTIVE_BEAD) or {}
    debt = _debt(active)
    if debt:
        return debt
    active_id = active.get("bead_id")
    frozen = active.get("acceptance_sha256")
    if not isinstance(contract, dict):
        if active_id and frozen and not active.get("proven"):
            return (
                f"bead {active_id}'s frozen ```verify oracle has not passed, and there is "
                f"no contract to run it. Restore it with `derive_contract.py --bead "
                f"{active_id}`, then run verify."
            )
        return None
    bound_id = contract.get("bead_id")
    command = contract.get("verification_command") or ""  # raw: no whitespace laundering
    if bound_id and contract.get("expected_exit", 0) != 0:
        return f"a bead-derived contract expects exit 0; this one expects {contract.get('expected_exit')}."

    if active_id and frozen:
        bead = _fetch_or_none(fetch, active_id)
        released = _released(active, bead)
        if not released and bead is not None and acceptance_sha256(bead) != frozen:
            return _rewritten(active_id)
        if bound_id == active_id and not released:
            if contract.get("acceptance_sha256") != frozen or (
                bead is not None and _oracle_of(bead) != command
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
