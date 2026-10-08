#!/usr/bin/env python3
"""The Stop gate's bd-queue check is scoped to beads THIS session claimed (escapement-xcbn).

Outcome: a session whose verify passed can stop when the only open/ready beads newer
than its watermark belong to other sessions or are unclaimed follow-ups it filed.
Measured cost of the old time-scoped rule (created_at >= watermark): 30.8% of Claude
tokens over 4 days were spent in turns opened by this block, 578 of them after a green
verify.

Business invariant
------------------
- A bead this session claimed that is still in_progress ⇒ BLOCK (negative control:
  claimed work is never abandoned).
- A fresh bead from another session (same account, so authorship can't separate them)
  ⇒ ALLOW.
- A follow-up this session FILED but never claimed (open, unclaimed by design) ⇒ ALLOW.
- A bead this session claimed but that has since been closed, or released back to
  open, is no longer held ⇒ ALLOW.
- bd failure ⇒ advisory ALLOW (unchanged fail-open).

Implementations these tests reject
----------------------------------
- the old time-scoped rule (any fresh open/ready bead blocks):
  test_other_sessions_fresh_beads_allow, test_own_unclaimed_followup_allows.
- "no claims recorded ⇒ fall back to the watermark rule": test_no_claims_allows.
- "allow everything" (an over-correction): test_claimed_in_progress_blocks,
  test_claim_from_ledger_blocks_end_to_end.
- dropping the l9lo single binding as a claim source: test_active_bead_counts_as_claim.

Run: uv run python -m pytest harness/tests/test_stop_bd_queue_scope.py -q
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "harness" / "bin"))

import stop_hook  # noqa: E402
import task_session_mode  # noqa: E402

FRESH = "2026-10-08T12:00:00+00:00"


def _item(id_: str, status: str = "open") -> dict:
    return {"id": id_, "created_at": FRESH, "status": status}


def _runner(in_progress=None, ready=None, open_=None, fail=False):
    ip, rd, op = in_progress or [], ready or [], open_ or []

    def run_bd(args):
        if fail:
            return None
        if "--status=in_progress" in args:
            return ip
        if args[:1] == ["ready"]:
            return rd
        if "--status=open" in args:
            return op
        return []

    return run_bd


def _check(run_bd, claimed=(), thread_dir=None):
    return stop_hook._check_bd_queue_implicit(
        "/repo", thread_dir=thread_dir, run_bd=run_bd, claimed=set(claimed),
    )


def test_other_sessions_fresh_beads_allow() -> None:
    """Cake shape: fresh beads created by other sessions sit open/ready/in_progress."""
    rb = _runner(
        in_progress=[_item("cake-other1", "in_progress")],
        ready=[_item("cake-other2")],
        open_=[_item("cake-other3")],
    )
    decision, reason = _check(rb, claimed={"cake-mine"})
    assert decision == "allow", f"other sessions' beads must not hold this Stop; got {reason}"


def test_own_unclaimed_followup_allows() -> None:
    """The session-completion protocol files follow-ups; filing one must not block its filer."""
    rb = _runner(ready=[_item("esc-followup")], open_=[_item("esc-followup")])
    decision, reason = _check(rb, claimed={"esc-done"})
    assert decision == "allow", f"an unclaimed follow-up must not block; got {reason}"


def test_no_claims_allows() -> None:
    rb = _runner(in_progress=[_item("x", "in_progress")], ready=[_item("y")])
    assert _check(rb, claimed=())[0] == "allow"


def test_claimed_in_progress_blocks() -> None:
    """Negative control: claimed work this session still holds is never abandoned."""
    rb = _runner(in_progress=[_item("esc-mine", "in_progress"), _item("esc-other", "in_progress")])
    decision, reason = _check(rb, claimed={"esc-mine"})
    assert (decision, reason) == ("block", "implicit_queue_claimed")
    assert stop_hook._queue_hold() == ["esc-mine"], "the block must name the bead holding it"


def test_claimed_then_closed_or_released_allows() -> None:
    """A claimed bead that is closed (absent) or back in `open` is no longer held."""
    rb = _runner(in_progress=[], open_=[_item("esc-mine")])
    assert _check(rb, claimed={"esc-mine"})[0] == "allow"


def test_bd_failure_allows() -> None:
    assert _check(_runner(fail=True), claimed={"esc-mine"})[0] == "allow"


def test_worktree_no_beads_dir_still_checks_via_bd() -> None:
    """858.4 / E-1 (kept from the superseded watermark suite): a worktree has no literal
    .beads/ dir but bd resolves via redirect, so the check must not short-circuit on it."""
    rb = _runner(in_progress=[_item("esc-mine", "in_progress")])
    decision, _ = stop_hook._check_bd_queue_implicit(
        "/tmp/worktree-no-beads", run_bd=rb, claimed={"esc-mine"},
    )
    assert decision == "block"


def test_claim_from_ledger_blocks_end_to_end(tmp_path) -> None:
    """The claim hook's recorder feeds the Stop check via the thread dir — no injection."""
    task_session_mode.record_session_claim(tmp_path, "esc-a")
    task_session_mode.record_session_claim(tmp_path, "esc-b")
    task_session_mode.record_session_claim(tmp_path, "esc-a")
    assert task_session_mode.load_session_claims(tmp_path) == {"esc-a", "esc-b"}
    rb = _runner(in_progress=[_item("esc-b", "in_progress")], ready=[_item("esc-other")])
    decision, _ = stop_hook._check_bd_queue_implicit("/repo", thread_dir=tmp_path, run_bd=rb)
    assert decision == "block"
    rb_done = _runner(ready=[_item("esc-other")])
    assert stop_hook._check_bd_queue_implicit("/repo", thread_dir=tmp_path, run_bd=rb_done)[0] == "allow"


def test_active_bead_counts_as_claim(tmp_path) -> None:
    """The l9lo binding (active_bead.json) is a claim even without a ledger entry."""
    (tmp_path / "active_bead.json").write_text(json.dumps({"bead_id": "esc-bound"}))
    rb = _runner(in_progress=[_item("esc-bound", "in_progress")])
    assert stop_hook._check_bd_queue_implicit("/repo", thread_dir=tmp_path, run_bd=rb)[0] == "block"


def test_block_gate_signal_names_held_beads(tmp_path, monkeypatch) -> None:
    """Fix step 3: the gate signal for a queue block lists the bead ids that held it."""
    (tmp_path / ".beads").mkdir()
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("BEADS_DIR", raising=False)
    monkeypatch.setattr(stop_hook, "incidents_log", lambda: tmp_path / "incidents.jsonl")
    _check(_runner(in_progress=[_item("esc-mine", "in_progress")]), claimed={"esc-mine"})
    stop_hook._log_incident({
        "decision": "block", "reason": "implicit_queue_claimed", "session_id": "s",
        "notes": stop_hook._queue_notes("implicit_queue_claimed"),
    })
    line = json.loads((tmp_path / ".beads" / ".gate-signal.jsonl").read_text().splitlines()[-1])
    assert line["reason"] == "implicit_queue_claimed"
    assert "esc-mine" in line["extras"]["notes"]


def test_claim_hook_records_every_claim(tmp_path) -> None:
    """The real PostToolUse claim hook writes each claim, so a second claimed bead held
    while the l9lo binding is busy still holds Stop (the binding keeps only one)."""
    thread = tmp_path / "thread"
    thread.mkdir()
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    (fakebin / "bd").write_text("#!/bin/sh\necho '[]'\n")
    (fakebin / "bd").chmod(0o755)
    env = {**os.environ, "PATH": f"{fakebin}{os.pathsep}{os.environ['PATH']}",
           "HARNESS_THREAD_DIR": str(thread), "HARNESS_ROOT": str(tmp_path / "h"),
           "CONTINUATION_HARNESS_HOME": str(tmp_path / "h"), "CLAUDE_CODE_SESSION_ID": "s1"}
    env.pop("CLAUDE_AGENT_ID", None)
    for bead in ("esc-a", "esc-b"):
        r = subprocess.run(
            [sys.executable, str(REPO / "harness" / "bin" / "task_mode_entry.py")],
            input=json.dumps({
                "session_id": "s1", "hook_event_name": "PostToolUse", "tool_name": "Bash",
                "tool_input": {"command": f"bd update {bead} --claim"},
                "tool_response": {"interrupted": False, "stdout": "", "stderr": ""},
            }),
            capture_output=True, text=True, env=env, cwd=tmp_path, timeout=60,
        )
        assert r.returncode == 0, r.stderr
    assert task_session_mode.load_session_claims(thread) == {"esc-a", "esc-b"}


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
