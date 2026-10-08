#!/usr/bin/env python3
"""Shadow landing verifier: would a blocking verifier have stopped this landing?

Records the answer and never decides (escapement-obwo). A landing is a PR merged
with `gh pr merge` or a bead closed with `bd close`, seen on PostToolUse of a call
that ran (and confirmed by GitHub's `MERGED` / the tracker's `closed`, because
Codex reports no exit status). When the landed diff touches behaviour files (the
TDD gate's classification), it WOULD be blocked for any of these reason codes:
`oracle-failed` (a closed bead's oracle failed in a throwaway checkout of the
landed commit), `no-oracle`, `no-challenger` (no mutation challenger / outcome
verifier dispatched this session). A merge is recorded with its PR number and
head; its oracle is not run, CI ran it. No behaviour file: `not-applicable`.

The hook spends at most its sync limit (2s; SHADOW_VERIFIER_SYNC_SECONDS, capped
at 10s), writes a `provisional` record and hands off to a DETACHED runner that
owns the budget, the oracle's process group and the final record.
Verdicts, ownership, records and the promotion rule: shadow_verifier.md.

SHADOW ONLY, by construction rather than by configuration: stdout is replaced
before anything runs and no code path chooses an exit status, so no host can
read a decision from this hook.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _shadow_run import (  # noqa: E402
    acquire_slot,
    add_harness_bin_to_path,
    budget,
    first_verdict,
    lookup,
    run_bounded,
    sync_seconds,
)

GATE = "shadow_verifier"
PR_LOOKUP_SECONDS = 5.0
LOOKUP_TIMEOUT_SECONDS = 10.0
CLEANUP_TIMEOUT_SECONDS = 15.0
MAX_RUNNERS_PER_REPO = 2
# Below this much remaining budget a step is not started ("budget-exhausted").
MIN_STEP_SECONDS = 1.0
OUTPUT_TAIL_CHARS = 400
COMMAND_CHARS = 200
MAX_LISTED_FILES = 20
PR_FIELDS = "number,url,headRefOid,state,files"
# Verdicts that judged a landing, and so are counted once per landing.
JUDGED = frozenset({"would-pass", "would-block", "not-applicable"})
# Reason codes, in the order they are reported.
ORACLE_FAILED, NO_ORACLE, NO_CHALLENGER = "oracle-failed", "no-oracle", "no-challenger"


class Terminated(BaseException):
    """The runner was told to stop; its oracle must die and its record be written."""


def _record(decision: str, reason: str, evidence: dict) -> None:
    from _gate_signal import record

    if not record(gate_name=GATE, decision=decision, reason=reason, **evidence):
        print(f"{GATE}: gate signal unavailable; landing {evidence.get('landing_id')} "
              f"{decision} not recorded", file=sys.stderr)


def _remaining(deadline: float) -> float:
    return deadline - time.monotonic()


def _session(data: dict) -> str:
    return data.get("session_id") or os.environ.get("CLAUDE_SESSION_ID", "default")


# --- the hook: observe dispatches, detect landings that ran, record, hand off --------


def _succeeded(data: dict) -> bool:
    response = data.get("tool_response")
    if isinstance(response, dict):
        return not (response.get("is_error") is True or response.get("interrupted") is True)
    return True


def _hook(data: object) -> None:
    from _agent_dispatch import agent_dispatch, host
    from _bd_command import pr_merges, subcommand_bead_ids
    from _effective_cwd import normalized

    if not isinstance(data, dict):
        return
    dispatch = agent_dispatch(data)
    if dispatch is not None:
        from _shadow_challengers import observe

        observe(data, dispatch, _session(data))
        return
    if data.get("tool_name") != "Bash":
        return
    if data.get("hook_event_name", "PostToolUse") != "PostToolUse" or not _succeeded(data):
        return
    data = normalized(data)
    tool_input = data.get("tool_input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    if not isinstance(command, str):
        return
    closes, merges = subcommand_bead_ids(command, "close"), pr_merges(command)
    if not closes and not merges:
        return

    deadline = time.monotonic() + sync_seconds()
    base = {"mode": "shadow", "host": host(data), "command": command[:COMMAND_CHARS],
            "session_id": _session(data), "tool_use_id": data.get("tool_use_id"),
            # Challenger and contract evidence is the session's, not this PR's.
            "evidence_scope": "session",
            "budget_seconds": budget()}
    landings = [{**base, "kind": "merge", "landing_id": uuid.uuid4().hex,
                 "pr_selector": selector, "pr_repo": repo} for selector, repo in merges]
    if closes:
        landings.append({**base, "kind": "close", "landing_id": uuid.uuid4().hex, "beads": closes})

    cwd = data.get("cwd")
    located = None
    if isinstance(cwd, str) and os.path.isdir(cwd):
        located = lookup(["git", "rev-parse", "--path-format=absolute", "--show-toplevel",
                          "--git-common-dir", "HEAD"], cwd, _remaining(deadline))
    lines = located.split() if located else []
    if len(lines) != 3:
        for evidence in landings:
            _record("inconclusive", f"no git checkout at {evidence['kind']}", evidence)
        return
    repo_root, common_dir, head = lines
    _use_root_beads(Path(common_dir))
    dirty = None
    if closes:
        status = lookup(["git", "status", "--porcelain", "--untracked-files=no", "--", ".",
                         ":(exclude).beads"], repo_root, _remaining(deadline))
        dirty = None if status is None else bool(status.strip())

    for evidence in landings:
        evidence["repo"] = repo_root
        if evidence["kind"] == "merge":
            evidence["checkout_head"] = head
        else:
            evidence.update(head_sha=head, dirty=dirty)
        _record("provisional", f"{evidence['kind']} detected; verdict pending in a detached runner",
                evidence)
        if evidence["kind"] == "close" and dirty is None:
            _record("inconclusive", "working tree state unknown at close", evidence)
        elif evidence["kind"] == "close" and dirty:
            _record("inconclusive", "uncommitted changes at close: the landed commit is not the work",
                    evidence)
        else:
            _spawn_runner({"repo_root": repo_root, "common_dir": common_dir, "evidence": evidence},
                          deadline)


def _use_root_beads(common_dir: Path) -> None:
    """Point the signal store at the root checkout's .beads, so a linked
    worktree's records are not stranded. An explicit BEADS_DIR wins."""
    if os.environ.get("BEADS_DIR") and Path(os.environ["BEADS_DIR"]).is_dir():
        return
    beads = common_dir.parent / ".beads"
    if beads.is_dir():
        os.environ["BEADS_DIR"] = str(beads)


def _spawn_runner(job: dict, deadline: float) -> None:
    runner = subprocess.Popen(
        [sys.executable, "-B", str(Path(__file__).resolve()), "--runner", json.dumps(job)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        cwd=job["repo_root"], start_new_session=True, close_fds=True,
    )
    # It forks and exits at once; every landing shares the hook's one sync limit.
    # A slow fork is left to finish on its own, and the next landing still gets
    # its runner.
    try:
        runner.wait(timeout=max(_remaining(deadline), 0.5))
    except subprocess.TimeoutExpired:
        pass


# --- the runner: judge the landed commit within the budget, write the verdict ---------


def _session_contract(session_id: str) -> dict | None:
    from would_block_stop import harness_home, thread_dir_for_session

    try:
        contract = json.loads(
            (thread_dir_for_session(session_id, harness_home()) / "contract.json").read_text()
        )
    except (OSError, ValueError):
        return None
    return contract if isinstance(contract, dict) else None


def _claimed_bead(contract: dict | None) -> str | None:
    if contract and contract.get("source") == "bead-derived" and contract.get("thread_id"):
        return str(contract["thread_id"])
    return None


def _actor(repo_root: str, deadline: float) -> str:
    """bd's own default actor: $BEADS_ACTOR, then git user.name, then $USER."""
    actor = os.environ.get("BEADS_ACTOR", "").strip()
    if actor:
        return actor
    name = lookup(["git", "config", "user.name"], repo_root,
                  min(LOOKUP_TIMEOUT_SECONDS, _remaining(deadline))) or ""
    return name.strip() or os.environ.get("USER", "")


def _checkout(repo_root: str, head: str, deadline: float) -> str | None:
    """A throwaway detached checkout of exactly the landed commit."""
    tree = tempfile.mkdtemp(prefix="shadow-verifier-")
    added = lookup(["git", "-c", "core.hooksPath=/dev/null", "worktree", "add", "--detach", tree, head],
                   repo_root, min(LOOKUP_TIMEOUT_SECONDS * 3, _remaining(deadline)))
    if added is None:
        _remove_checkout(repo_root, tree)
        return None
    return tree


def _remove_checkout(repo_root: str, tree: str) -> None:
    lookup(["git", "worktree", "remove", "--force", tree], repo_root, CLEANUP_TIMEOUT_SECONDS)
    shutil.rmtree(tree, ignore_errors=True)
    lookup(["git", "worktree", "prune"], repo_root, CLEANUP_TIMEOUT_SECONDS)


def _behaviour(files: list[str] | None) -> list[str] | None:
    """Behaviour files, as the TDD gate classifies them: not tests, not exempt
    (docs, config, scripts, ...). None when the landed files are unknown."""
    if files is None:
        return None
    import importlib.util

    spec = importlib.util.spec_from_file_location("_tdd_gate", Path(__file__).resolve().parent / "tdd-gate.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    return [path for path in files if not gate.is_test_file(path) and not gate.is_exempt_file(path)]


def _branch_files(repo_root: str, head: str, deadline: float) -> list[str] | None:
    """Files the landed commit changed since it left the remote default branch."""
    from git_change_scope import remote_default_target

    target = remote_default_target(Path(repo_root))
    if target is None:
        return None
    timeout = min(LOOKUP_TIMEOUT_SECONDS, _remaining(deadline))
    base = lookup(["git", "merge-base", target.oid, head], repo_root, timeout)
    if base is None:
        return None
    changed = lookup(["git", "diff", "--name-only", base.strip(), head], repo_root, timeout)
    return None if changed is None else [line for line in changed.splitlines() if line.strip()]


def _bead_oracle(bead_id: str, job: dict, deadline: float, owners: tuple[str, str | None],
                 *, require_closed: bool) -> dict | str:
    """The oracle command to run for a bead, or its final result when there is none to run."""
    from derive_contract import OracleNotDeclared, derive_contract

    if _remaining(deadline) < MIN_STEP_SECONDS:
        return {"id": bead_id, "verify": "budget-exhausted"}
    shown = lookup(["bd", "show", bead_id, "--json"], job["repo_root"],
                   min(LOOKUP_TIMEOUT_SECONDS, _remaining(deadline)))
    try:
        bead = json.loads(shown) if shown else None
    except ValueError:
        bead = None
    if isinstance(bead, list):
        bead = bead[0] if bead else None
    if not isinstance(bead, dict):
        return {"id": bead_id, "verify": "unreadable"}
    if require_closed and bead.get("status") != "closed":
        return {"id": bead_id, "verify": "not-closed", "status": bead.get("status")}
    # Reading an oracle is safe for any bead; only RUNNING one is gated on
    # ownership, so a foreign bead's missing oracle is still reported as such.
    try:
        oracle = derive_contract(bead)["verification_command"]
    except OracleNotDeclared as exc:
        return {"id": bead_id, "verify": "no-oracle", "detail": str(exc)[:OUTPUT_TAIL_CHARS]}
    actor, claimed = owners
    if bead_id != claimed and (bead.get("assignee") or "") != actor:
        return {"id": bead_id, "verify": "not-run", "assignee": bead.get("assignee"),
                "command": oracle[:COMMAND_CHARS],
                "detail": f"foreign bead: not claimed by this session, not assigned to {actor!r}"}
    return oracle


def _contract_oracle(contract: dict) -> dict | str:
    """A hand-authored session contract's own oracle, screened like a bead's."""
    from init_contract import is_evaporating_oracle, is_trivial_oracle

    oracle = str(contract.get("verification_command") or "")
    reason = is_trivial_oracle(oracle) or is_evaporating_oracle(oracle)
    if reason:
        return {"id": "session-contract", "verify": "no-oracle", "detail": reason[:OUTPUT_TAIL_CHARS]}
    return oracle


def _run_oracle(oracle_id: str, oracle: str, job: dict, deadline: float, tree: list) -> dict:
    shown = oracle[:COMMAND_CHARS]
    if tree[0] is None:
        tree[0] = _checkout(job["repo_root"], job["evidence"]["head_sha"], deadline)
        if tree[0] is None:
            return {"id": oracle_id, "verify": "checkout-failed", "command": shown}
    remaining = _remaining(deadline)
    if remaining < MIN_STEP_SECONDS:
        return {"id": oracle_id, "verify": "budget-exhausted", "command": shown}
    try:
        result = run_bounded(oracle, shell=True, cwd=tree[0], timeout=remaining)
    except OSError as exc:
        return {"id": oracle_id, "verify": "fail", "command": shown, "detail": str(exc)}
    if result is None:
        return {"id": oracle_id, "verify": "timeout", "command": shown,
                "timeout_seconds": round(remaining, 1)}
    returncode, output = result
    return {"id": oracle_id, "verify": "pass" if returncode == 0 else "fail", "command": shown,
            "exit_code": returncode, "output_tail": output[-OUTPUT_TAIL_CHARS:]}


def _resolve_pr(job: dict, deadline: float) -> tuple[str, str] | list[str]:
    """Fill the PR's number, URL and head; return its files, or an early verdict."""
    evidence, repo_root = job["evidence"], job["repo_root"]
    argv = ["gh", "pr", "view", *([evidence["pr_selector"]] if evidence["pr_selector"] else []),
            "--json", PR_FIELDS, *(["-R", evidence["pr_repo"]] if evidence["pr_repo"] else [])]
    shown = lookup(argv, repo_root, min(PR_LOOKUP_SECONDS, _remaining(deadline)))
    try:
        pr = json.loads(shown) if shown else None
    except ValueError:
        pr = None
    if not isinstance(pr, dict) or not isinstance(pr.get("headRefOid"), str):
        return "inconclusive", "pull request could not be resolved (gh pr view)"
    evidence.update(pr_number=pr.get("number"), pr_url=pr.get("url"), head_sha=pr["headRefOid"],
                    pr_state=pr.get("state"))
    if pr.get("state") != "MERGED":
        return "not-landed", f"pull request is {pr.get('state')}, not merged"
    files = pr.get("files")
    return [f["path"] for f in files if isinstance(f, dict) and isinstance(f.get("path"), str)] \
        if isinstance(files, list) else []


def _declared(item: dict | str, oracle_id: str) -> dict:
    """A merge's oracle, recorded as declared (CI ran it) rather than run."""
    if isinstance(item, dict):
        return item
    return {"id": oracle_id, "verify": "declared", "command": item[:COMMAND_CHARS]}


def _verdict(results: list[dict], behaviour: list[str] | None,
             challengers: list[dict]) -> tuple[str, str, list[str]]:
    """(decision, reason, reason codes). Called only once behaviour is not []."""
    codes: list[str] = []
    definite, unsure = [], []
    if not results:
        results = [{"id": "landing", "verify": "no-oracle"}]
    for result in results:
        state, name = result["verify"], result["id"]
        if state == "fail":
            codes.append(ORACLE_FAILED)
            definite.append(f"{name}: verify failed")
        elif state == "no-oracle" and behaviour:
            codes.append(NO_ORACLE)
            definite.append(f"{name}: no oracle")
        elif state == "no-oracle":
            unsure.append(f"{name}: no oracle, landed diff unknown")
        elif state == "not-run":
            unsure.append(f"{name}: not-run (foreign bead)")
        elif state not in ("pass", "declared"):
            unsure.append(f"{name}: verify {state}")
    if not challengers and behaviour:
        codes.append(NO_CHALLENGER)
        definite.append("no challenger: behaviour changed and no mutation challenger or outcome "
                        "verifier was dispatched this session")
    elif not challengers:
        unsure.append("no challenger, landed diff unknown")
    codes = sorted(set(codes), key=(ORACLE_FAILED, NO_ORACLE, NO_CHALLENGER).index)
    if definite:
        return "would-block", "; ".join(definite + unsure), codes
    if unsure:
        return "inconclusive", "; ".join(unsure), codes
    return "would-pass", "the landing has a passing or CI-run oracle and was challenged", codes


def _judge(job: dict, deadline: float) -> tuple[str, str]:
    """Fill the evidence as each fact is learned (an error keeps what came before)."""
    from _shadow_challengers import dispatched

    evidence, repo_root = job["evidence"], job["repo_root"]
    add_harness_bin_to_path()
    contract = _session_contract(evidence["session_id"])
    owners = (_actor(repo_root, deadline), _claimed_bead(contract))
    evidence["reason_codes"] = []
    results: list[dict] = []
    if evidence["kind"] == "merge":
        files = _resolve_pr(job, deadline)
        if isinstance(files, tuple):
            return files
        # A merge is bound to the session's contract: its bead, or its own oracle.
        if owners[1]:
            results.append(_declared(_bead_oracle(owners[1], job, deadline, owners, require_closed=False),
                                     owners[1]))
        elif contract and contract.get("verification_command"):
            results.append(_declared(_contract_oracle(contract), "session-contract"))
        targets, pending = [], []
    else:
        files = _branch_files(repo_root, evidence["head_sha"], deadline)
        targets = evidence["beads"]
        pending = [_bead_oracle(bead_id, job, deadline, owners, require_closed=True) for bead_id in targets]
    evidence["beads"] = results
    behaviour = _behaviour(files)
    evidence["behaviour_files"] = None if behaviour is None else behaviour[:MAX_LISTED_FILES]
    evidence["challengers"] = challengers = dispatched(evidence["session_id"])
    if pending and all(isinstance(p, dict) and p["verify"] == "not-closed" for p in pending):
        results.extend(pending)
        return "not-landed", "no bead in the command is closed"
    if behaviour == []:
        results.extend(p for p in pending if isinstance(p, dict))
        return "not-applicable", "no behaviour file changed (docs, tests and config only)"
    tree: list[str | None] = [None]
    try:
        for target, item in zip(targets, pending):
            results.append(item if isinstance(item, dict) else _run_oracle(target, item, job, deadline, tree))
    finally:
        if tree[0] is not None:
            _remove_checkout(repo_root, tree[0])
    landed = [r for r in results if r["verify"] != "not-closed"]
    decision, reason, codes = _verdict(landed, behaviour, challengers)
    evidence["reason_codes"] = codes
    return decision, reason


def _landing_key(evidence: dict) -> str:
    """A landing is the PR and its head, or the closed beads and the commit."""
    if evidence["kind"] == "merge":
        return f"merge:{evidence.get('pr_number')}:{evidence.get('head_sha')}"
    return f"close:{','.join(sorted(b['id'] for b in evidence['beads']))}:{evidence.get('head_sha')}"


def _terminate(signum: int, _frame) -> None:
    raise Terminated(signal.Signals(signum).name)


def _runner(job_json: str) -> None:
    # Second fork: the process the hook waited on exits now, and this one is
    # orphaned into its own session, owned by no host.
    if os.fork() > 0:
        os._exit(0)
    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(signum, _terminate)
    job = json.loads(job_json)
    evidence = job["evidence"]
    deadline = time.monotonic() + evidence["budget_seconds"]
    try:
        if acquire_slot(Path(job["common_dir"]), MAX_RUNNERS_PER_REPO) is None:
            _record("inconclusive", f"runner busy: {MAX_RUNNERS_PER_REPO} runners already judging "
                    "this repository", evidence)
        else:
            decision, reason = _judge(job, deadline)
            first = first_verdict(Path(job["common_dir"]), _landing_key(evidence),
                                  evidence["landing_id"]) if decision in JUDGED else None
            if first:
                evidence["duplicate_of"] = first
                decision, reason = "duplicate", f"already judged as landing {first}"
            _record(decision, reason, evidence)
    except Terminated as exc:
        _record("inconclusive", f"runner terminated ({exc})", evidence)
    except BaseException as exc:  # noqa: BLE001 - nothing above this frame to catch it
        _record("error", f"{type(exc).__name__}: {exc}"[:OUTPUT_TAIL_CHARS], evidence)
    os._exit(0)  # do not wait on daemon reader threads


def main(argv: list[str]) -> int:
    if argv[1:2] == ["--runner"] and len(argv) == 3:
        _runner(argv[2])
        return 0
    # Nothing this process prints can reach a host: that is what makes it shadow.
    sys.stdout = io.StringIO()
    try:
        _hook(json.load(sys.stdin))
    except SystemExit:
        pass  # no code path here may choose the exit status
    except Exception:  # noqa: BLE001 - a shadow check must never alter a landing
        pass
    return 0


if __name__ == "__main__":
    main(sys.argv)
    sys.exit(0)
