#!/usr/bin/env python3
"""escapement-l9lo — a claimed bead's acceptance oracle is the continuation contract.

Outcome (user-observable)
-------------------------
When a session claims a bead, the bead's ```verify acceptance block — written
before the code — becomes the contract that `verify` runs and the Stop gate
accepts, frozen at claim time. An agent can no longer end its turn on a contract
it wrote for itself, for earlier work, or from acceptance text rewritten after
the claim. A session with no claimed bead keeps declaring its own contract.

Oracle
------
The REAL entrypoints, run as subprocesses against an isolated harness root and a
fake `bd` that serves bead records from disk: the claim hook
(task_mode_entry.py), `init_contract.py`, `derive_contract.py`, the `verify`
shell entrypoint, and the Stop hook. The observable verdict is the Stop hook's
block/allow output and verify's exit code — not any helper's return value.

Wrong implementations these tests reject
----------------------------------------
- "claim ignored": the claim does not derive the bead's oracle, so the session
  keeps whatever contract it had (test_claim_freezes_bead_oracle_as_contract).
- "always prefer the agent contract": init_contract.py silently replaces a bead
  oracle, or a hand-written contract.json passes verify/Stop
  (test_agent_contract_cannot_replace_bead_oracle).
- "hash computed but never compared": the acceptance text is hashed at claim
  but a rewritten oracle still verifies green
  (test_acceptance_rewritten_after_claim_is_reported).
- "re-derive silently uses the new text": derive_contract.py re-freezes a
  rewritten acceptance without an explicit --refreeze
  (test_acceptance_rewritten_after_claim_is_reported).
- "bead switch ignored": a contract that went green for bead A still lets the
  session stop after it claims bead B — the l9lo defect
  (test_bead_switch_invalidates_previous_contract).
- "only the current bead is remembered": claiming A, then B, rewriting A and
  re-claiming A adopts the rewritten oracle (test_reclaim_after_detour_cannot_launder_rewrite).
- "labels checked, command not": a forged contract that keeps bead_id and the
  acceptance hash but swaps the command still verifies
  (test_forged_command_with_genuine_labels_is_rejected).
- "a finished bead binds forever": after the claimed bead is closed, the agent
  cannot declare a contract for the unclaimed work that follows
  (test_closed_bead_releases_its_oracle).
- "closing is a release": closing a claimed bead whose oracle never went green
  lets the agent declare an easier contract (test_close_with_red_oracle_still_holds).
- "no way out of a rewritten bead": removing or trivialising the bead's verify
  block leaves --refreeze, init_contract and close all refusing, so the session is
  stuck forever (test_oracle_removed_after_claim_recovers_via_refreeze,
  test_closed_and_rewritten_bead_recovers_only_via_refreeze).
- "close-then-swap": close bead A while its oracle is red, claim a throwaway bead
  with no oracle, declare `test -d .` — Stop must not be released
  (test_close_red_then_claim_throwaway_cannot_swap_exam).
- "silent refreeze": the agent adopts a rewritten oracle and Stop says nothing
  (test_refreeze_is_reported_at_stop).
- "prose edits trap verify": a typo fix in acceptance prose, with the verify
  command unchanged, reads as a rewritten oracle (test_prose_edit_is_not_a_rewrite).
- "proof on request": `derive_contract.py --proven` marks a red oracle proven, then
  close + declare releases Stop (test_proven_cannot_be_asserted_without_a_green_run).
- "notice only the agent sees": a refreeze reported inside a block reason never
  reaches the human (test_refreeze_notice_reaches_human_on_block).
- "owed refreeze clobbers the active contract": retiring a non-active owed oracle
  replaces the active bead's contract or leaves the debt in place
  (test_owed_bead_retired_by_recorded_refreeze).
- "one bd outage unbinds the bead": the claim-time lookup fails, the freeze is
  never retried, and the agent declares its own exam
  (test_bd_down_at_claim_freezes_once_bd_recovers).
- "proof outlives a later red run": the oracle passes, then fails, and the bead is
  closed — the stale proof must not release it (test_red_run_after_proof_unproves).
- "proof outlives a stronger rewrite": the oracle is rewritten after it passed and
  the bead closed (test_rewrite_after_proof_is_not_released).
- "mark_proven is an API": calling it directly records proof without the on-disk
  contract's last run being green (test_mark_proven_requires_on_disk_green_run).
- "a pending freeze is dropped on switch": claim A while bd is down, claim a
  throwaway B, declare an easy exam — A's never-frozen oracle silently vanishes
  (test_switch_while_pending_keeps_the_debt[*]).
- "no contract.json, no gate": a claim-time freeze that failed leaves no
  contract.json, and Stop read that as a conversational allow
  (test_pending_freeze_without_contract_blocks_stop).
- "a late freeze is invisible": the oracle frozen after bd recovers was edited
  after the claim, and nobody is told (test_late_freeze_of_edited_bead_reaches_human).
- "a typo'd claim traps the session": bd positively says the bead does not
  exist, yet it is bound as pending forever (test_claim_of_missing_bead_does_not_bind).
- "bd's 'missing' retires a debt": bd answers from the cwd's database, so a bead
  is "missing" from any other repo; init_contract, Stop or a claim run there, or
  a deleted bead, must never clear a pending or frozen debt
  (test_missing_from_another_repo_never_releases[*],
  test_second_claim_cannot_replace_a_pending_debt, test_deleted_bead_is_held_until_retired).
- "late freeze of a bead left behind is silent": A pending, a claim of B, A edited,
  bd recovers — the human is told (test_late_freeze_after_switch_reaches_human).
- "partial id never matches": `l9lo` resolves to `proj-l9lo` in bd, but the binding
  keeps the typed id and rejects the bead's own oracle forever
  (test_partial_id_binds_the_canonical_bead).
- "a hanging bd stalls Stop": Stop must hold, and finish within ~15s
  (test_hanging_bd_holds_without_stalling_stop).
- "with bd down, any command passes": a forged command with the genuine labels
  verifies while the bead is unreadable (test_forged_command_rejected_while_bd_down).
- "proof from another checkout": the oracle passes in a different directory
  (test_oracle_run_outside_the_repo_is_not_proof).
- "whitespace-equal is equal": a forged command differing only by Unicode
  whitespace from the oracle verifies (test_unicode_whitespace_forgery_rejected).
- "a subagent's claim rebinds the parent": a subagent sharing the parent's
  thread dir claims a child bead and replaces the parent's contract
  (test_subagent_claim_does_not_rebind_parent).
- "ad hoc sessions regress": with no bead bound, an agent-declared contract must
  still verify and release Stop (test_unbound_session_keeps_agent_contract).
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import textwrap

import pytest

BIN = pathlib.Path(__file__).resolve().parents[1] / "bin"
SESSION = "l9lo-session"

FAKE_BD = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import json, os, pathlib, sys
    store = pathlib.Path(os.environ["FAKE_BD_STORE"])
    args = sys.argv[1:]
    if (store / "_hang").exists():
        import time
        time.sleep(60)
    if (store / "_down").exists():
        sys.stderr.write("bd: database unavailable\\n")
        sys.exit(1)
    repo = (store / "_repo").read_text() if (store / "_repo").exists() else None
    here = os.path.realpath(os.getcwd())
    in_repo = repo is None or here == repo or here.startswith(repo + os.sep)
    if args[:1] == ["show"] and len(args) >= 2:
        # Like real bd: the database is found from the cwd (another repo's has no
        # such bead), and a unique id suffix resolves to the full id.
        path = store / (args[1] + ".json")
        if not path.exists():
            hits = [p for p in store.glob("*.json") if p.stem.endswith("-" + args[1])]
            path = hits[0] if len(hits) == 1 else path
        if not in_repo or not path.exists():  # real bd: a JSON error on stdout, exit 1
            print(json.dumps({"error": "no issues found matching the provided IDs"}))
            sys.exit(1)
        print(json.dumps([json.loads(path.read_text())]))
        sys.exit(0)
    if args[:1] in (["ready"], ["list"]):
        print("[]")
        sys.exit(0)
    sys.exit(0)
    """
)


def _acceptance(command: str | None) -> str:
    prose = "The outcome is observable."
    if command is None:
        return prose
    return f"{prose}\n\n```verify\n{command}\n```\n"


class Session:
    """One isolated harness session driven through the real entrypoints."""

    def __init__(self, tmp: pathlib.Path) -> None:
        self.work = tmp / "work"
        self.work.mkdir()
        self.thread = tmp / "thread"
        self.thread.mkdir()
        self.store = tmp / "beads"
        self.store.mkdir()
        (self.store / "_repo").write_text(os.path.realpath(self.work))
        self.other = tmp / "other-repo"  # a different repository: bd knows none of these beads
        self.other.mkdir()
        fakebin = tmp / "fakebin"
        fakebin.mkdir()
        bd = fakebin / "bd"
        bd.write_text(FAKE_BD)
        bd.chmod(0o755)
        self.env = {
            **os.environ,
            "PATH": f"{fakebin}{os.pathsep}{os.environ.get('PATH', '')}",
            "FAKE_BD_STORE": str(self.store),
            "HARNESS_THREAD_DIR": str(self.thread),
            "HARNESS_ROOT": str(tmp / "harness"),
            "CONTINUATION_HARNESS_HOME": str(tmp / "harness"),
            "CLAUDE_CODE_SESSION_ID": SESSION,
        }
        self.env.pop("CLAUDE_AGENT_ID", None)

    def bead(self, bead_id: str, command: str | None) -> None:
        (self.store / f"{bead_id}.json").write_text(json.dumps({
            "id": bead_id,
            "title": f"Outcome of {bead_id}",
            "status": "in_progress",
            "acceptance_criteria": _acceptance(command),
        }))

    def close(self, bead_id: str) -> None:
        path = self.store / f"{bead_id}.json"
        path.write_text(json.dumps(dict(json.loads(path.read_text()), status="closed")))

    def _run(self, argv: list[str], stdin: str = "", cwd=None) -> subprocess.CompletedProcess:
        return subprocess.run(
            argv, input=stdin, capture_output=True, text=True,
            cwd=cwd or self.work, env=self.env, timeout=120,
        )

    def claim(self, bead_id: str, cwd=None, **payload_extra) -> subprocess.CompletedProcess:
        r = self._run([sys.executable, str(BIN / "task_mode_entry.py")], cwd=cwd, stdin=json.dumps({
            **payload_extra,
            "session_id": SESSION,
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": f"bd update {bead_id} --claim"},
            "tool_response": {"interrupted": False, "stdout": "", "stderr": ""},
        }))
        assert r.returncode == 0, r.stderr
        return r

    def declare(self, command: str, cwd=None) -> subprocess.CompletedProcess:
        return self._run([
            sys.executable, str(BIN / "init_contract.py"),
            "--goal", "agent goal", "--verify", command,
        ], cwd=cwd)

    def derive(self, bead_id: str, *extra: str) -> subprocess.CompletedProcess:
        return self._run([sys.executable, str(BIN / "derive_contract.py"), "--bead", bead_id, *extra])

    def verify(self, cwd=None) -> subprocess.CompletedProcess:
        return self._run(["bash", str(BIN / "verify")], cwd=cwd)

    def without_task_mode(self) -> None:
        """Drop the task-mode record so only the contract gate decides Stop (task
        mode's own root check would otherwise block first on an open bead)."""
        (self.thread / "session_mode.json").unlink(missing_ok=True)

    def bound(self) -> "str | None":
        path = self.thread / "active_bead.json"
        return json.loads(path.read_text()).get("bead_id") if path.exists() else None

    def stop(self, cwd=None) -> dict | None:
        r = self._run([sys.executable, str(BIN / "stop_hook.py")], cwd=cwd, stdin=json.dumps({
            "session_id": SESSION, "transcript_path": "", "stop_hook_active": False,
        }))
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout) if r.stdout.strip() else None

    def contract(self) -> dict:
        return json.loads((self.thread / "contract.json").read_text())


@pytest.fixture
def s(tmp_path: pathlib.Path) -> Session:
    return Session(tmp_path)


def _allowed(verdict: dict | None) -> bool:
    """Stop allowed: no output, or output with no decision (e.g. a systemMessage)."""
    return verdict is None or (isinstance(verdict, dict) and "decision" not in verdict)


def _blocked(verdict: dict | None) -> bool:
    return isinstance(verdict, dict) and verdict.get("decision") == "block"


def test_claim_freezes_bead_oracle_as_contract(s: Session) -> None:
    """Claiming a bead makes its ```verify block the contract — no hand-authoring."""
    s.declare("test -d .")  # earlier ad hoc contract, would pass
    s.bead("bd-a", "test -f done-a")
    s.claim("bd-a")

    assert s.contract()["verification_command"] == "test -f done-a"
    assert s.verify().returncode != 0, "the bead oracle is red until the outcome exists"
    assert _blocked(s.stop())

    (s.work / "done-a").write_text("x")
    s.close("bd-a")
    assert s.verify().returncode == 0
    assert _allowed(s.stop()), "a green bead oracle releases Stop"


def test_agent_contract_cannot_replace_bead_oracle(s: Session) -> None:
    """With a bead oracle bound, the agent may not swap in an easier exam."""
    s.bead("bd-a", "test -f done-a")
    s.claim("bd-a")

    r = s.declare("test -d .")
    assert r.returncode != 0, "init_contract.py must refuse to replace a bead oracle"
    assert "bd-a" in r.stderr
    assert s.contract()["verification_command"] == "test -f done-a"

    # Bypass the CLI: hand-write an agent contract straight into contract.json.
    forged = dict(s.contract(), verification_command="test -d .", source="agent-declared")
    forged.pop("bead_id", None)
    (s.thread / "contract.json").write_text(json.dumps(forged))
    v = s.verify()
    assert v.returncode != 0, "a hand-written contract must not verify while a bead oracle is bound"
    assert "bd-a" in (v.stdout + v.stderr)
    assert _blocked(s.stop())


def test_acceptance_rewritten_after_claim_is_reported(s: Session) -> None:
    """Rewriting the bead's oracle mid-work is surfaced, never silently adopted."""
    s.bead("bd-a", "test -f done-a")
    s.claim("bd-a")

    s.bead("bd-a", "test -d .")  # oracle rewritten to something already true
    v = s.verify()
    assert v.returncode != 0
    assert "changed" in (v.stdout + v.stderr).lower()
    assert _blocked(s.stop())

    # Re-deriving does not quietly adopt the new text...
    r = s.derive("bd-a")
    assert r.returncode != 0 and "--refreeze" in r.stderr
    assert s.verify().returncode != 0
    # ...a contract re-derived from the new text by hand is still caught...
    (s.thread / "contract.json").write_text(json.dumps(
        dict(s.contract(), verification_command="test -d .", acceptance_sha256="0" * 64)))
    assert s.verify().returncode != 0
    assert _blocked(s.stop())

    # ...and an explicit, recorded re-freeze is the escape (positive control).
    s.close("bd-a")
    r = s.derive("bd-a", "--refreeze")
    assert r.returncode == 0, r.stderr
    assert s.contract().get("refrozen_from")
    assert s.verify().returncode == 0
    assert _allowed(s.stop())


def test_bead_switch_invalidates_previous_contract(s: Session) -> None:
    """The l9lo defect: A's green contract must not stand in for bead B's work."""
    s.bead("bd-a", "test -f done-a")
    s.claim("bd-a")
    (s.work / "done-a").write_text("x")
    s.close("bd-a")
    assert s.verify().returncode == 0
    assert _allowed(s.stop())  # positive control: A really was done

    s.bead("bd-b", None)  # B declares no machine oracle
    s.claim("bd-b")
    assert _blocked(s.stop()), "A's fresh green run must not release Stop for B"
    v = s.verify()
    assert v.returncode != 0, "verify must not re-run A's oracle as proof for B"
    assert "bd-b" in (v.stdout + v.stderr)

    # Re-declaring for B (which has no bead oracle) is the escape.
    assert s.declare("test -f done-b").returncode == 0
    (s.work / "done-b").write_text("x")
    assert s.verify().returncode == 0
    assert _allowed(s.stop())

    # A third bead WITH an oracle replaces B's contract with its own.
    s.bead("bd-c", "test -f done-c")
    s.claim("bd-c")
    assert s.contract()["verification_command"] == "test -f done-c"
    assert _blocked(s.stop())


def test_unbound_session_keeps_agent_contract(s: Session) -> None:
    """No bead claimed: the agent-declared path is unchanged."""
    assert s.declare("test -f done").returncode == 0
    assert s.verify().returncode != 0
    assert _blocked(s.stop())
    (s.work / "done").write_text("x")
    assert s.verify().returncode == 0
    assert _allowed(s.stop())


def test_reclaim_after_detour_cannot_launder_rewrite(s: Session) -> None:
    """A -> B -> rewrite A -> A again: A's first freeze still governs."""
    s.bead("bd-a", "test -f done-a")
    s.claim("bd-a")
    s.bead("bd-b", None)
    s.claim("bd-b")
    s.bead("bd-a", "test -d .")
    s.claim("bd-a")

    v = s.verify()
    assert v.returncode != 0
    assert "changed" in (v.stdout + v.stderr).lower()
    assert _blocked(s.stop())


def test_forged_command_with_genuine_labels_is_rejected(s: Session) -> None:
    """Keeping bead_id and the hash does not make a different command the oracle."""
    s.bead("bd-a", "test -f done-a")
    s.claim("bd-a")
    forged = dict(s.contract(), verification_command="test -d .")
    (s.thread / "contract.json").write_text(json.dumps(forged))

    assert s.verify().returncode != 0
    assert _blocked(s.stop())


def test_closed_bead_releases_its_oracle(s: Session) -> None:
    """Once the claimed bead's oracle went green and it is closed, the next unclaimed
    work may be declared."""
    s.bead("bd-a", "test -f done-a")
    s.claim("bd-a")
    (s.work / "done-a").write_text("x")
    assert s.verify().returncode == 0
    s.close("bd-a")

    assert s.declare("test -f done-next").returncode == 0
    assert s.verify().returncode != 0, "the re-declared contract, not A's, is what runs"
    (s.work / "done-next").write_text("x")
    assert s.verify().returncode == 0
    assert _allowed(s.stop())


def test_close_with_red_oracle_still_holds(s: Session) -> None:
    """Closing a bead whose oracle never passed is not an escape from it."""
    s.bead("bd-a", "test -f done-a")
    s.claim("bd-a")
    assert s.verify().returncode != 0
    s.close("bd-a")  # no work done

    r = s.declare("test -d .")
    assert r.returncode != 0, "init_contract must still refuse while A's oracle is red"
    assert "bd-a" in r.stderr
    forged = dict(s.contract(), verification_command="test -d .", source="agent-declared")
    forged.pop("bead_id", None)
    forged.pop("acceptance_sha256", None)
    (s.thread / "contract.json").write_text(json.dumps(forged))
    assert s.verify().returncode != 0, "a hand-written contract must not verify"
    assert _blocked(s.stop())

    # Positive control: doing the work and verifying releases it.
    assert s.derive("bd-a").returncode == 0
    (s.work / "done-a").write_text("x")
    assert s.verify().returncode == 0
    assert _allowed(s.stop())
    assert s.declare("test -f done-next").returncode == 0


def _refreezes(s: Session) -> list:
    return json.loads((s.thread / "active_bead.json").read_text()).get("refreezes") or []


@pytest.mark.parametrize("rewritten", [None, "true"], ids=["removed", "trivial"])
def test_oracle_removed_after_claim_recovers_via_refreeze(s: Session, rewritten) -> None:
    """The bead's oracle is deleted or trivialised mid-work: --refreeze is the one
    recorded way out, and nothing else releases the session."""
    s.bead("bd-a", "test -f done-a")
    s.claim("bd-a")
    s.bead("bd-a", rewritten)

    v = s.verify()
    assert v.returncode != 0 and "changed" in (v.stdout + v.stderr).lower()
    assert s.declare("test -d .").returncode != 0
    assert s.derive("bd-a").returncode != 0, "plain re-derive must not adopt the rewrite"
    assert _blocked(s.stop())

    r = s.derive("bd-a", "--refreeze")
    assert r.returncode == 0, r.stderr
    log = _refreezes(s)
    assert log and log[-1]["from_command"] == "test -f done-a"
    assert log[-1]["to_command"] is None

    # The bead no longer declares an oracle, so the agent declares the outcome.
    assert s.declare("test -f done-a2").returncode == 0
    assert s.verify().returncode != 0
    (s.work / "done-a2").write_text("x")
    s.close("bd-a")
    assert s.verify().returncode == 0
    assert _allowed(s.stop())


def test_closed_and_rewritten_bead_recovers_only_via_refreeze(s: Session) -> None:
    """Closing a rewritten, never-green bead does not release it; --refreeze does."""
    s.bead("bd-a", "test -f done-a")
    s.claim("bd-a")
    s.bead("bd-a", "test -d .")
    s.close("bd-a")

    assert s.declare("test -d .").returncode != 0
    assert s.verify().returncode != 0
    assert _blocked(s.stop())

    r = s.derive("bd-a", "--refreeze")
    assert r.returncode == 0, r.stderr
    assert _refreezes(s)[-1]["to_command"] == "test -d ."
    assert s.contract()["verification_command"] == "test -d ."
    assert s.verify().returncode == 0
    assert _allowed(s.stop())


def test_subagent_claim_does_not_rebind_parent(s: Session) -> None:
    """A subagent on the parent's thread dir claiming a child leaves the parent bound."""
    s.bead("bd-a", "test -f done-a")
    s.claim("bd-a")
    s.bead("bd-child", "test -d .")
    s.claim("bd-child", agent_id="sub-1", agent_type="general-purpose")

    assert s.contract()["verification_command"] == "test -f done-a"
    assert s.verify().returncode != 0


def test_close_red_then_claim_throwaway_cannot_swap_exam(s: Session) -> None:
    """Review NO-SHIP repro: claiming a throwaway does not rebind away from an
    unproven oracle — A stays the contract."""
    s.bead("bd-a", "test -f done-a")
    s.claim("bd-a")
    assert s.verify().returncode != 0
    s.close("bd-a")
    s.bead("bd-throwaway", None)
    r = s.claim("bd-throwaway")
    assert "bd-a" in r.stderr and "not bound" in r.stderr, r.stderr
    s.close("bd-throwaway")
    assert s.declare("test -d .").returncode != 0
    assert s.bound() == "bd-a"
    assert s.verify().returncode != 0, "A's red oracle is still the contract"
    assert _blocked(s.stop())

    # Positive control: going back and actually proving A settles the debt.
    s.claim("bd-a")
    (s.work / "done-a").write_text("x")
    assert s.verify().returncode == 0
    assert _allowed(s.stop())


def test_refreeze_is_reported_at_stop(s: Session) -> None:
    """An adopted rewrite is visible at Stop, naming the old and new command."""
    s.bead("bd-a", "test -f done-a")
    s.claim("bd-a")
    s.bead("bd-a", "test -d .")
    assert s.derive("bd-a", "--refreeze").returncode == 0
    s.close("bd-a")
    assert s.verify().returncode == 0
    r = s._run([sys.executable, str(BIN / "stop_hook.py")], json.dumps({
        "session_id": SESSION, "transcript_path": "", "stop_hook_active": False}))
    out = json.loads(r.stdout)
    shown = out.get("systemMessage", "") + out.get("reason", "")
    assert "test -f done-a" in shown and "test -d ." in shown, out
    assert out.get("decision") != "block", "the report must not itself block"


def test_prose_edit_is_not_a_rewrite(s: Session) -> None:
    """Only the verify command is frozen; editing surrounding prose is fine."""
    s.bead("bd-a", "test -f done-a")
    s.claim("bd-a")
    path = s.store / "bd-a.json"
    bead = json.loads(path.read_text())
    bead["acceptance_criteria"] = "Typo fixed. " + bead["acceptance_criteria"]
    path.write_text(json.dumps(bead))
    (s.work / "done-a").write_text("x")
    s.close("bd-a")
    assert s.verify().returncode == 0
    assert _allowed(s.stop())


def _stop_raw(s: Session) -> dict:
    r = s._run([sys.executable, str(BIN / "stop_hook.py")], json.dumps({
        "session_id": SESSION, "transcript_path": "", "stop_hook_active": False}))
    return json.loads(r.stdout) if r.stdout.strip() else {}


def test_refreeze_notice_reaches_human_on_block(s: Session) -> None:
    """A refreeze notice on a blocked Stop goes to the human, not only the agent."""
    s.bead("bd-a", "test -f done-a")
    s.claim("bd-a")
    s.bead("bd-a", "test -f done-a-v2")
    assert s.derive("bd-a", "--refreeze").returncode == 0
    out = _stop_raw(s)                               # red: blocks
    assert out.get("decision") == "block"
    assert "test -f done-a-v2" in out.get("systemMessage", ""), out


def test_retire_is_the_recorded_exit(s: Session) -> None:
    """Moving to other work while A is unproven goes through --retire, which the
    human sees at Stop."""
    s.bead("bd-a", "test -f done-a")
    s.claim("bd-a")
    s.bead("bd-b", "test -f done-b")
    s.claim("bd-b")
    assert s.bound() == "bd-a"
    assert s.derive("bd-b").returncode != 0

    r = s._run([sys.executable, str(BIN / "derive_contract.py"), "--retire"])
    assert r.returncode == 0, r.stderr
    s.claim("bd-b")
    assert s.contract()["verification_command"] == "test -f done-b"
    (s.work / "done-b").write_text("x")
    s.close("bd-b")
    s.close("bd-a")  # task mode is rooted at the first claim
    assert s.verify().returncode == 0
    out = _stop_raw(s)
    assert "decision" not in out, out
    note = out.get("systemMessage", "")
    assert "bd-a" in note and "test -f done-a" in note and "never passed" in note, out


def test_bd_down_at_claim_freezes_once_bd_recovers(s: Session) -> None:
    """Re-review B1 repro: claim while bd is down, bd recovers, re-claim, declare."""
    s.bead("bd-a", "test -f done-a")
    (s.store / "_down").write_text("")
    r = s._run([sys.executable, str(BIN / "task_mode_entry.py")], json.dumps({
        "session_id": SESSION, "hook_event_name": "PostToolUse", "tool_name": "Bash",
        "tool_input": {"command": "bd update bd-a --claim"},
        "tool_response": {"interrupted": False, "stdout": "", "stderr": ""}}))
    assert "bd-a" in r.stderr, "a failed claim-time freeze must be visible"
    assert s.declare("test -d .").returncode != 0, "no self-declared exam while the oracle is unknown"
    held = s.stop()
    assert _blocked(held) and "could not be read" in held["reason"], held

    (s.store / "_down").unlink()
    s.claim("bd-a")
    assert s.contract()["verification_command"] == "test -f done-a"
    assert s.declare("test -d .").returncode != 0
    assert s.verify().returncode != 0
    s.close("bd-a")
    assert _blocked(s.stop())


def test_bd_recovery_freezes_lazily_without_reclaim(s: Session) -> None:
    """The freeze also happens on the next check once bd is readable."""
    s.bead("bd-a", "test -f done-a")
    (s.store / "_down").write_text("")
    s.claim("bd-a")
    (s.store / "_down").unlink()
    assert s.declare("test -d .").returncode != 0
    (s.thread / "contract.json").write_text(json.dumps({
        "goal": "g", "verification_command": "test -d .", "expected_exit": 0,
        "source": "agent-declared", "created_at": "2999-01-01T00:00:00+00:00"}))
    assert s.verify().returncode != 0
    s.close("bd-a")
    assert _blocked(s.stop())


def test_red_run_after_proof_unproves(s: Session) -> None:
    s.bead("bd-a", "test -f done-a")
    s.claim("bd-a")
    (s.work / "done-a").write_text("x")
    assert s.verify().returncode == 0
    (s.work / "done-a").unlink()
    assert s.verify().returncode != 0
    s.close("bd-a")
    assert s.declare("test -d .").returncode != 0
    assert _blocked(s.stop())


def test_rewrite_after_proof_is_not_released(s: Session) -> None:
    s.bead("bd-a", "test -f done-a")
    s.claim("bd-a")
    (s.work / "done-a").write_text("x")
    assert s.verify().returncode == 0
    s.bead("bd-a", "test -f done-a && test -f stronger")  # oracle tightened after proof
    s.close("bd-a")
    assert s.declare("test -d .").returncode != 0
    assert _blocked(s.stop())


def test_mark_proven_requires_on_disk_green_run(s: Session) -> None:
    """mark_proven requires the on-disk contract's last run to be green. (Editing the
    state files directly is the disclosed tamper class, not defended here.)"""
    s.bead("bd-a", "test -f done-a")
    s.claim("bd-a")
    assert s.verify().returncode != 0
    r = s._run([sys.executable, "-c", (
        "import sys; sys.path.insert(0, %r); import bead_binding as b; b.mark_proven(%r)"
    ) % (str(BIN), str(s.thread))])
    assert r.returncode == 0, r.stderr  # the call itself ran
    active = json.loads((s.thread / "active_bead.json").read_text())
    assert not active.get("proven"), active

    (s.work / "done-a").write_text("x")  # positive control: a real green run proves
    assert s.verify().returncode == 0
    assert json.loads((s.thread / "active_bead.json").read_text()).get("proven")


def test_unicode_whitespace_forgery_rejected(s: Session) -> None:
    """A command equal to the oracle only after .strip() is a different command."""
    s.bead("bd-a", "test -f done-a")
    s.claim("bd-a")
    forged = dict(s.contract(), verification_command="test -f done-a\u00a0")
    (s.thread / "contract.json").write_text(json.dumps(forged))
    (s.work / "done-a\u00a0").write_text("x")  # satisfies the forgery, not the outcome
    assert s.verify().returncode != 0
    s.close("bd-a")
    assert _blocked(s.stop())


def _down(s: Session, down: bool) -> None:
    flag = s.store / "_down"
    if down:
        flag.write_text("")
    elif flag.exists():
        flag.unlink()


@pytest.mark.parametrize("bd_down_at_switch", [False, True], ids=["bd-up", "bd-down"])
def test_switch_while_pending_keeps_the_debt(s: Session, bd_down_at_switch: bool) -> None:
    """Round-4 BLOCK-1: a never-frozen oracle holds the binding, so switching to a
    throwaway bead and declaring an easy exam cannot discharge it."""
    s.bead("bd-a", "test -f done-a")
    _down(s, True)
    s.claim("bd-a")
    _down(s, bd_down_at_switch)
    s.bead("bd-b", None)
    s.claim("bd-b")
    _down(s, False)
    assert s.declare("test -d .").returncode != 0
    s.close("bd-a")
    s.close("bd-b")
    assert s.bound() == "bd-a"
    assert s.verify().returncode != 0
    assert _blocked(s.stop())


def test_pending_freeze_without_contract_blocks_stop(s: Session) -> None:
    """Round-4 BLOCK-2: claim while bd is down, no contract.json is ever written, the
    bead is closed and bd stays down — Stop must still block on the pending freeze."""
    s.bead("bd-a", "test -f done-a")
    _down(s, True)
    s.claim("bd-a")
    s.close("bd-a")
    assert not (s.thread / "contract.json").exists()
    verdict = s.stop()
    assert _blocked(verdict), verdict
    assert "bd-a" in verdict["reason"] and "could not be read" in verdict["reason"], verdict

    _down(s, False)  # bd recovers: the oracle is frozen and is now the open debt
    verdict = s.stop()
    assert _blocked(verdict), verdict
    assert s.contract()["verification_command"] == "test -f done-a"


def test_late_freeze_of_edited_bead_reaches_human(s: Session) -> None:
    """Round-4 CONCERN-2: the oracle frozen after bd recovers came from text edited
    after the claim; the human is told, the same way as a refreeze."""
    s.bead("bd-a", "test -f done-a")
    _down(s, True)
    s.claim("bd-a")
    s.bead("bd-a", "test -f easier")
    path = s.store / "bd-a.json"
    path.write_text(json.dumps(dict(json.loads(path.read_text()),
                                    updated_at="2999-01-01T00:00:00Z")))
    _down(s, False)
    out = _stop_raw(s)
    note = out.get("systemMessage", "")
    assert "bd-a" in note and "late" in note.lower() and "test -f easier" in note, out
    record = json.loads((s.thread / "active_bead.json").read_text())
    assert record.get("frozen_at")


def test_late_freeze_of_unedited_bead_is_quiet(s: Session) -> None:
    """Negative control: a late freeze of text untouched since the claim is not news."""
    s.bead("bd-a", "test -f done-a")
    path = s.store / "bd-a.json"
    path.write_text(json.dumps(dict(json.loads(path.read_text()),
                                    updated_at="2000-01-01T00:00:00Z")))
    _down(s, True)
    s.claim("bd-a")
    _down(s, False)
    out = _stop_raw(s)
    assert "late" not in out.get("systemMessage", "").lower(), out
    assert s.contract()["verification_command"] == "test -f done-a"


def test_claim_of_missing_bead_does_not_bind(s: Session) -> None:
    """Round-4 CONCERN-3: bd positively reports the bead does not exist (a typo or a
    rejected claim) — nothing is bound, so nothing can trap the session."""
    s.claim("bd-typo")
    assert not (s.thread / "active_bead.json").exists()
    assert s.declare("test -f done").returncode == 0
    (s.work / "done").write_text("x")
    assert s.verify().returncode == 0


@pytest.mark.parametrize("action", ["declare", "stop", "verify"])
def test_missing_from_another_repo_never_releases(s: Session, action: str) -> None:
    """Round-5 r1/r7: from another repo bd reports the bead "missing". That is
    never proof of deletion: the pending debt holds, and freezes in its own repo.
    (A claim from another repo declines before touching the binding; r1b covers it.)"""
    s.declare("test -d .")  # an earlier ad hoc contract, so verify reaches the binding check
    s.bead("bd-a", "test -f done-a")
    _down(s, True)
    s.claim("bd-a")
    _down(s, False)
    if action == "declare":
        assert s.declare("test -d .", cwd=s.other).returncode != 0
    elif action == "stop":
        assert _blocked(s.stop(cwd=s.other))
    else:
        assert s.verify(cwd=s.other).returncode != 0
    assert s.bound() == "bd-a"
    # Had the debt been released, this easy exam would now verify and stop clean.
    s.close("bd-a")
    s.declare("test -d .")
    s.verify()
    assert _blocked(s.stop())
    assert s.contract()["verification_command"] == "test -f done-a"


def test_second_claim_cannot_replace_a_pending_debt(s: Session) -> None:
    """Round-5 r1b: further claims — in this repo while bd is down, or from another
    repo after it recovers — neither rebind nor erase a pending debt."""
    s.bead("bd-a", "test -f done-a")
    s.bead("bd-b", None)
    _down(s, True)
    s.claim("bd-a")
    s.claim("bd-b")
    _down(s, False)
    s.claim("bd-b", cwd=s.other)
    assert s.bound() == "bd-a"
    s.without_task_mode()
    verdict = s.stop(cwd=s.other)
    assert _blocked(verdict) and "bd-a" in verdict["reason"], verdict


def test_deleted_bead_is_held_until_retired(s: Session) -> None:
    """Round-5 C3: a pending bead deleted from bd stays owed; --retire is the exit."""
    s.bead("bd-a", "test -f done-a")
    _down(s, True)
    s.claim("bd-a")
    (s.store / "bd-a.json").unlink()
    _down(s, False)
    s.without_task_mode()
    verdict = s.stop()
    assert _blocked(verdict) and "bd-a" in verdict["reason"], verdict
    assert s.bound() == "bd-a"

    r = s._run([sys.executable, str(BIN / "derive_contract.py"), "--retire"])
    assert r.returncode == 0, r.stderr
    assert s.bound() is None
    assert s.declare("test -f done").returncode == 0


def test_late_freeze_after_switch_reaches_human(s: Session) -> None:
    """Round-5 r3: A pending, a claim of B (held off), A edited after its claim,
    bd recovers — the late freeze is shown to the human."""
    s.bead("bd-a", "test -f done-a")
    s.bead("bd-b", None)
    _down(s, True)
    s.claim("bd-a")
    s.claim("bd-b")
    s.bead("bd-a", "test -f easier")
    path = s.store / "bd-a.json"
    path.write_text(json.dumps(dict(json.loads(path.read_text()),
                                    updated_at="2999-01-01T00:00:00Z")))
    _down(s, False)
    note = _stop_raw(s).get("systemMessage", "")
    assert "bd-a" in note and "late freeze" in note and "test -f easier" in note, note


def test_partial_id_binds_the_canonical_bead(s: Session) -> None:
    """Round-5 C1: a claim by unique suffix binds bd's canonical id, and the bead's
    own oracle then proves it."""
    s.bead("proj-l9lo", "test -f done")
    s.claim("l9lo")
    assert s.bound() == "proj-l9lo"
    s.without_task_mode()
    (s.work / "done").write_text("x")
    s.close("proj-l9lo")
    assert s.verify().returncode == 0
    assert _allowed(s.stop())


def test_hanging_bd_holds_without_stalling_stop(s: Session) -> None:
    """Round-5 C2: with bd hanging, the binding's bd time is capped: Stop holds the
    pending debt and returns within ~15s (task-mode's own bd calls removed here)."""
    import time

    s.bead("bd-a", "test -f done-a")
    _down(s, True)
    s.claim("bd-a")
    _down(s, False)
    (s.store / "_hang").write_text("")
    s.without_task_mode()
    started = time.monotonic()
    verdict = s.stop()
    elapsed = time.monotonic() - started
    assert _blocked(verdict) and "bd-a" in verdict["reason"], verdict
    assert elapsed <= 15, f"Stop took {elapsed:.1f}s under a hanging bd"


def test_forged_command_rejected_while_bd_down(s: Session) -> None:
    """The frozen command is compared even when the bead cannot be read."""
    s.bead("bd-a", "test -f done-a")
    s.claim("bd-a")
    _down(s, True)
    forged = dict(s.contract(), verification_command="test -d .")
    (s.thread / "contract.json").write_text(json.dumps(forged))
    assert s.verify().returncode != 0
    assert _blocked(s.stop())


def test_oracle_run_outside_the_repo_is_not_proof(s: Session) -> None:
    """The frozen oracle proves the outcome only when it ran inside the bead's repo."""
    s.bead("bd-a", "test -f done-a")
    s.claim("bd-a")
    (s.other / "done-a").write_text("x")  # satisfied elsewhere, not here
    s.verify(cwd=s.other)
    assert not json.loads((s.thread / "active_bead.json").read_text()).get("proven")
    s.close("bd-a")
    assert _blocked(s.stop())
