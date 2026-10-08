#!/usr/bin/env python3
"""A claimed bead's frozen oracle is the session's contract (escapement-l9lo).

INVARIANT. Once a bead is bound in a session, its debt is retired only by
  (a) its frozen oracle passing in `verify`, run inside the bead's own repo;
  (b) an explicit, recorded `derive_contract.py --refreeze` or `--retire`,
      shown to the human at Stop;
  (c) the user saying "stop".
Nothing bd reports — missing, deleted, closed, unreadable, timed out — retires
or erases a debt; it only means "cannot settle now, keep holding".

One binding at a time, in `active_bead.json`:
  bead_id, repo, claimed_at   the bound bead (bd's canonical id) and the repo
                              every bd call for it runs in
  acceptance_sha256, command  its oracle, frozen at claim (frozen_at)
  freeze_pending              bd could not be read at claim; frozen when it can
  proven, proven_sha256       the frozen oracle's last verify run was green
  refreezes                   audit entries (refreeze, retire, late freeze),
                              shown to the human once

Claiming another bead while the bound one is unproven does not rebind: the
agent is told to pass it or retire it. A claim of an id bd reports missing in
the claim's own repo (a typo, a rejected claim) is not bound.

bd time per process is capped at BD_BUDGET_SECONDS in total, and each bead is
looked up at most once per process, so a hanging bd holds the session rather
than stalling Stop.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from derive_contract import (  # noqa: E402
    BeadNotFound,
    OracleNotDeclared,
    acceptance_sha256,
    derive_contract,
    fetch_bead,
)

ACTIVE_BEAD = "active_bead.json"
BD_BUDGET_SECONDS = 10.0

_LOOKUPS: "dict[tuple, tuple]" = {}
_SPENT = [0.0]


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def read_json(path: pathlib.Path) -> "dict | None":
    try:
        value = json.loads(pathlib.Path(path).read_text())
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def write_json(path: pathlib.Path, value: dict) -> None:
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


def repo_root(cwd: str) -> str:
    """The git top level of `cwd`, or `cwd` itself outside a repository."""
    try:
        r = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=cwd,
                           capture_output=True, text=True, timeout=5)
        if r.returncode == 0 and r.stdout.strip():
            return os.path.realpath(r.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    return os.path.realpath(cwd)


def _in_repo(path, repo) -> bool:
    if not path or not repo:
        return False
    path, repo = os.path.realpath(path), os.path.realpath(repo)
    return path == repo or path.startswith(repo.rstrip(os.sep) + os.sep)


def lookup(bead_id: str, repo: "str | None") -> "tuple[dict | None, bool]":
    """(bead, missing) from bd run in `repo`; once per bead per process, within budget.

    `missing` is True only when bd positively reports no such bead. Only the
    claim acts on it; after a claim it never retires anything.
    """
    key = (bead_id, repo)
    if key in _LOOKUPS:
        return _LOOKUPS[key]
    left = BD_BUDGET_SECONDS - _SPENT[0]
    result: tuple = (None, False)
    if left >= 0.5:
        started = time.monotonic()
        try:
            bead = fetch_bead(bead_id, cwd=repo, timeout=left)
            result = (bead if isinstance(bead, dict) else None, False)
        except BeadNotFound:
            result = (None, True)
        except (OracleNotDeclared, subprocess.SubprocessError, ValueError, OSError):
            result = (None, False)
        _SPENT[0] += time.monotonic() - started
    _LOOKUPS[key] = result
    return result


def _active(thread_dir) -> dict:
    return read_json(pathlib.Path(thread_dir) / ACTIVE_BEAD) or {}


def _holds(active: dict) -> bool:
    """The bound bead still owes its oracle (pending, or frozen and never passed)."""
    return bool(active.get("bead_id")) and bool(
        active.get("freeze_pending") or (active.get("acceptance_sha256") and not active.get("proven"))
    )


def _late_entry(active: dict, bead: dict, command: "str | None") -> "dict | None":
    """An audit entry when a freeze after the claim adopts a bead edited after it."""
    updated, claimed = _parse_ts(bead.get("updated_at")), _parse_ts(active.get("claimed_at"))
    if updated is None or claimed is None or updated <= claimed:
        return None
    return {"bead_id": bead.get("id") or active.get("bead_id"), "at": _now(), "late_freeze": True,
            "updated_at": bead.get("updated_at"), "to_command": command}


def _freeze(thread_dir, active: dict, bead: dict, *, at_claim: bool, session_id=None) -> dict:
    """Freeze `bead`'s oracle (or its absence) into the binding; write contract.json."""
    try:
        contract = derive_contract(bead, session_id=session_id)
    except OracleNotDeclared:
        contract = None
    record = dict(active, bead_id=bead.get("id") or active["bead_id"], freeze_pending=False,
                  frozen_at=_now(), acceptance_sha256=None, command=None, proven=False)
    if contract is not None:
        record.update(acceptance_sha256=contract["acceptance_sha256"],
                      command=contract["verification_command"])
    entry = None if at_claim else _late_entry(active, bead, record["command"])
    if entry:
        record["refreezes"] = list(record.get("refreezes") or []) + [entry]
    write_json(pathlib.Path(thread_dir) / ACTIVE_BEAD, record)
    if contract is not None:
        write_json(pathlib.Path(thread_dir) / "contract.json", contract)
    return record


def settle(thread_dir, *, session_id=None) -> dict:
    """Freeze a pending binding if bd can now read the bead; return the binding."""
    active = _active(thread_dir)
    if active.get("freeze_pending"):
        bead, _missing = lookup(active["bead_id"], active.get("repo"))
        if bead is not None:
            active = _freeze(thread_dir, active, bead, at_claim=False, session_id=session_id)
    return active


def bind_claimed_bead(thread_dir, typed_id: str, *, cwd: str, session_id=None) -> None:
    """Bind a successful claim, unless the bound bead still owes its oracle."""
    thread_dir = pathlib.Path(thread_dir)
    repo = repo_root(cwd)
    bead, missing = lookup(typed_id, repo)
    if missing:
        print(f"derive_contract: bd reports no bead {typed_id} in {repo}, so the claim is "
              "not bound.", file=sys.stderr)
        return
    bead_id = (bead or {}).get("id") or typed_id
    active = settle(thread_dir, session_id=session_id)
    if active.get("bead_id") in (bead_id, typed_id):
        return
    if _holds(active):
        print(f"derive_contract: claim of {bead_id} is not bound — bead {active['bead_id']} "
              "still owes its ```verify oracle. Pass it (`verify`), or retire it by explicit "
              "decision with `derive_contract.py --retire` (shown to the user).", file=sys.stderr)
        return
    record = {"bead_id": bead_id, "repo": repo, "claimed_at": _now(), "freeze_pending": True,
              "refreezes": list(active.get("refreezes") or [])}
    write_json(thread_dir / ACTIVE_BEAD, record)
    if bead is not None:
        _freeze(thread_dir, record, bead, at_claim=True, session_id=session_id)
    else:
        print(f"derive_contract: could not read bead {bead_id} at claim, so its ```verify "
              "oracle is not frozen yet; it is frozen once bd answers, and until then Stop "
              "stays blocked.", file=sys.stderr)


def _released(active: dict, bead: "dict | None") -> bool:
    """A proven bead that is closed, unchanged since the proof, no longer has
    precedence: what follows is unclaimed work the agent may declare for."""
    return (bool(active.get("proven")) and bead is not None and bead.get("status") == "closed"
            and acceptance_sha256(bead) == active.get("proven_sha256"))


def oracle_in_force(thread_dir) -> "str | None":
    """The bound bead whose oracle no agent-declared contract may replace, or None."""
    active = settle(thread_dir)
    if active.get("freeze_pending"):
        return active["bead_id"]
    if not active.get("acceptance_sha256"):
        return None
    if _released(active, lookup(active["bead_id"], active.get("repo"))[0]):
        return None
    return active["bead_id"]


def _rewritten(bead_id: str) -> str:
    return (f"bead {bead_id}'s ```verify oracle changed since it was frozen — rewritten "
            "mid-work. Restore it, or adopt the new one by explicit decision: "
            f"`derive_contract.py --bead {bead_id} --refreeze`.")


def _declared_after_claim(contract: dict, active: dict) -> bool:
    declared, claimed = _parse_ts(contract.get("created_at")), _parse_ts(active.get("claimed_at"))
    return declared is not None and (claimed is None or declared >= claimed)


def binding_problem(contract, thread_dir) -> "str | None":
    """Why the session may not stop on `contract` (None: no readable contract.json)
    given its binding, or None. Debts hold whether or not a contract exists."""
    active = settle(thread_dir)
    aid, frozen, repo = active.get("bead_id"), active.get("acceptance_sha256"), active.get("repo")
    contract = contract if isinstance(contract, dict) else None
    bound_id = (contract or {}).get("bead_id")
    if not aid:
        if bound_id and contract.get("acceptance_sha256"):
            bead = lookup(bound_id, None)[0]
            if bead is not None and acceptance_sha256(bead) != contract["acceptance_sha256"]:
                return _rewritten(bound_id)
        return None
    if active.get("freeze_pending"):
        return (f"bead {aid}'s ```verify oracle could not be read when it was claimed (bd "
                "unavailable), so nothing can stand in for it yet. It is frozen once bd answers "
                f"in {repo}; or retire it with `derive_contract.py --retire` (shown to the user).")
    bead = lookup(aid, repo)[0] if frozen else None
    if frozen and not _released(active, bead):
        if contract is None:
            return (f"bead {aid}'s frozen ```verify oracle has not passed and there is no "
                    f"contract to run it. Restore it with `derive_contract.py --bead {aid}`.")
        if bound_id != aid:
            return (f"bead {aid} declares its own ```verify oracle, so it is the contract; "
                    f"this contract ({contract.get('source', 'unknown source')}) cannot "
                    f"replace it. Run `derive_contract.py --bead {aid}` to restore it.")
        if contract.get("expected_exit", 0) != 0 or contract.get("acceptance_sha256") != frozen \
                or contract.get("verification_command") != active.get("command"):
            return (f"this contract is not bead {aid}'s oracle as frozen at claim. Run "
                    f"`derive_contract.py --bead {aid}` to restore it.")
        if bead is not None and acceptance_sha256(bead) != frozen:
            return _rewritten(aid)
        last = contract.get("last_run")
        if isinstance(last, dict) and last.get("cwd") and not _in_repo(last["cwd"], repo):
            return (f"bead {aid}'s oracle last ran in {last['cwd']}, outside its repo {repo}; "
                    "run `verify` from inside the repo.")
        return None
    if contract is None or (frozen and bound_id == aid):
        return None
    if bound_id and bound_id != aid:
        return (f"this contract proves bead {bound_id}, but the bound bead is {aid}. Declare "
                f"{aid}'s outcome (init_contract.py) or add a ```verify block to its acceptance "
                f"and run `derive_contract.py --bead {aid}`.")
    if not _declared_after_claim(contract, active):
        return (f"this contract was declared before bead {aid} was claimed, so it describes "
                f"earlier work. Declare {aid}'s outcome (init_contract.py).")
    return None


def mark_proven(thread_dir) -> None:
    """Record what the on-disk contract's last run says about the bound oracle.

    Proven only when contract.json's last_run is a fresh, unsuppressed pass of
    exactly the frozen command, run inside the bead's repo, against a readable,
    unchanged bead. Any other run clears it. Editing state files is out of scope.
    """
    path = pathlib.Path(thread_dir) / ACTIVE_BEAD
    active = read_json(path)
    contract = read_json(pathlib.Path(thread_dir) / "contract.json")
    if not (active and contract and active.get("acceptance_sha256")
            and contract.get("bead_id") == active.get("bead_id")):
        return
    from would_block_stop import _verification_passed_this_turn  # local: import cycle

    bead = lookup(active["bead_id"], active.get("repo"))[0]
    last = contract.get("last_run") or {}
    proven = (
        _verification_passed_this_turn(contract)
        and contract.get("expected_exit", 0) == 0
        and contract.get("acceptance_sha256") == active["acceptance_sha256"]
        and contract.get("verification_command") == active.get("command")
        and _in_repo(last.get("cwd"), active.get("repo"))
        and bead is not None
        and acceptance_sha256(bead) == active["acceptance_sha256"]
    )
    if proven or active.get("proven"):
        write_json(path, dict(active, proven=proven,
                              proven_sha256=active["acceptance_sha256"] if proven else None))


def _log(active: dict, **entry) -> list:
    return list(active.get("refreezes") or []) + [dict(entry, at=_now())]


def derive_bound(thread_dir, bead_id: str, *, refreeze: bool, session_id=None) -> int:
    """`derive_contract.py --bead` while a bead is bound: re-derive it, adopt a
    rewrite (--refreeze), or freeze a pending one. Never switches the binding."""
    thread_dir = pathlib.Path(thread_dir)
    active = settle(thread_dir, session_id=session_id)
    aid = active["bead_id"]
    bead, _missing = lookup(bead_id, active.get("repo"))
    if (bead or {}).get("id", bead_id) != aid:
        why = (f"bead {aid} still owes its oracle — pass it, or retire it with "
               "`derive_contract.py --retire` (shown to the user)" if _holds(active)
               else f"the bound bead is {aid}; claim {bead_id} first (`bd update {bead_id} --claim`)")
        print(f"refusing to derive contract: {why}.", file=sys.stderr)
        return 2
    if bead is None:
        print(f"could not read bead {bead_id} in {active.get('repo')}; nothing changed.",
              file=sys.stderr)
        return 1
    try:
        contract = derive_contract(bead, session_id=session_id)
    except OracleNotDeclared as exc:
        if refreeze and active.get("acceptance_sha256"):
            write_json(thread_dir / ACTIVE_BEAD, dict(
                active, acceptance_sha256=None, command=None, proven=False,
                refreezes=_log(active, bead_id=aid, from_command=active.get("command"),
                               to_command=None)))
            print(f"bead {aid} no longer declares a usable oracle ({exc}); its frozen oracle "
                  "is released — declare this work's outcome with init_contract.py.")
            return 0
        print(f"refusing to derive contract: {exc}", file=sys.stderr)
        return 2
    sha, command = contract["acceptance_sha256"], contract["verification_command"]
    frozen = active.get("acceptance_sha256")
    if frozen and frozen != sha:
        if not refreeze:
            print(f"refusing to derive contract: {_rewritten(aid)}", file=sys.stderr)
            return 2
        contract["refrozen_from"] = frozen
        write_json(thread_dir / ACTIVE_BEAD, dict(
            active, acceptance_sha256=sha, command=command, proven=False,
            refreezes=_log(active, bead_id=aid, from_command=active.get("command"),
                           to_command=command)))
    elif not frozen:
        # An oracle added after the claim is adopted, and logged when the bead
        # was edited after the claim — the agent may have written its own exam.
        _freeze(thread_dir, active, bead, at_claim=False, session_id=session_id)
    write_json(thread_dir / "contract.json", contract)
    print(f"contract derived from {aid} -> {thread_dir / 'contract.json'}")
    print(json.dumps(contract, indent=2))
    return 0


def retire(thread_dir) -> int:
    """`derive_contract.py --retire`: end the binding by explicit, recorded decision."""
    thread_dir = pathlib.Path(thread_dir)
    active = _active(thread_dir)
    if not active.get("bead_id"):
        print("nothing to retire: no bead is bound in this session.", file=sys.stderr)
        return 2
    log = _log(active, bead_id=active["bead_id"], retired=True, proven=bool(active.get("proven")),
               from_command=active.get("command"))
    write_json(thread_dir / ACTIVE_BEAD, {"refreezes": log})
    print(f"bead {active['bead_id']} retired; this is reported to the user at Stop.")
    return 0


def _describe(entry: dict) -> str:
    bead_id = entry.get("bead_id", "?")
    if entry.get("late_freeze"):
        return (f"{bead_id}: late freeze as `{entry.get('to_command')}`, from text edited "
                f"after the claim (updated {entry.get('updated_at')})")
    if entry.get("retired"):
        state = "proven" if entry.get("proven") else "never passed"
        return f"{bead_id}: `{entry.get('from_command')}` retired by explicit decision ({state})"
    return (f"{bead_id}: `{entry.get('from_command')}` -> "
            f"`{entry.get('to_command') or '(oracle removed; agent-declared contract)'}`")


def refreeze_notice(thread_dir) -> "str | None":
    """Oracle changes not yet shown to the human, as one sentence; marks them shown.
    Settles a pending binding first, so a late freeze is reported on any Stop path."""
    settle(thread_dir)
    path = pathlib.Path(thread_dir) / ACTIVE_BEAD
    active = read_json(path)
    if not active:
        return None
    log = list(active.get("refreezes") or [])
    fresh = [e for e in log if isinstance(e, dict) and not e.get("reported")]
    if not fresh:
        return None
    parts = [_describe(e) for e in fresh]
    for e in fresh:
        e["reported"] = True
    write_json(path, dict(active, refreezes=log))
    return ("continuation-harness: a bead's frozen oracle changed outside a normal claim "
            "this session (--refreeze, --retire or a late freeze) — " + "; ".join(parts)
            + ". Check that this still proves the outcome.")
