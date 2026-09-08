"""`verify` must keep a history of runs, not just the last one (escapement-5xlj).

Business outcome
----------------
Someone auditing the harness — the operator, a later session, the review that
decides whether a gate is earning its place — must be able to ask "did this
oracle ever actually fail?" and get an answer.

Today they cannot. `harness/bin/verify` overwrites `contract.last_run` on every
run, so a fail → fix → pass cycle leaves only the pass. That makes the observed
179/181 green rate across live contracts a tautology rather than evidence: it
measures that agents stop verifying once green, which is what any working loop
does. The failures are only visible in `incidents.jsonl`, where 760 blocks against
677 passes conflate "verify ran red" with "agent had not run verify yet" — a split
nothing currently records.

This also supplies the named trigger `escapement-v3mj` needs: the red rate among
`pip5`-compelled contracts, measured against the 46–59% voluntary baseline.

Independent source of truth
---------------------------
The real `harness/bin/verify` script, executed as a subprocess against a real
contract, with an oracle whose result is flipped between runs. Not a mock of the
write path — the write path is the thing under test.

Invalid solution classes rejected here
--------------------------------------
- Recording only failures, or only the first run: the bite RATE needs both.
- Changing what `last_run` means: the Stop gate reads it, so it must still be the
  most recent run. A history that silently changed gate behaviour would trade one
  measurement problem for a correctness one.
- Unbounded growth: a long-lived contract must not accumulate runs forever.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
VERIFY = REPO / "harness" / "bin" / "verify"
BIN = REPO / "harness" / "bin"
sys.path.insert(0, str(BIN))


def _contract(thread_dir: pathlib.Path, command: str) -> pathlib.Path:
    thread_dir.mkdir(parents=True, exist_ok=True)
    path = thread_dir / "contract.json"
    path.write_text(
        json.dumps(
            {
                "goal": "the oracle's history is recorded",
                "verification_command": command,
                "expected_exit": 0,
                "source": "agent-declared",
                "thread_id": "history-test",
                "created_at": "2026-09-08T00:00:00+00:00",
                "last_run": None,
            }
        ),
        encoding="utf-8",
    )
    return path


def _run_verify(thread_dir: pathlib.Path) -> int:
    proc = subprocess.run(
        ["bash", str(VERIFY)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        env={**os.environ, "HARNESS_THREAD_DIR": str(thread_dir)},
    )
    return proc.returncode


def test_a_failed_run_survives_the_next_successful_one(tmp_path):
    """THE DEFECT. Red then green must leave BOTH runs on record.

    Fragile implementation this rejects: overwriting `last_run`, which makes the
    red invisible the moment the work is fixed — exactly the case an auditor
    cares about.
    """
    thread_dir = tmp_path / "thread"
    sentinel = tmp_path / "done.flag"
    contract = _contract(thread_dir, f"test -f {sentinel}")

    assert _run_verify(thread_dir) == 1, "oracle should be red while the flag is absent"
    sentinel.write_text("", encoding="utf-8")
    assert _run_verify(thread_dir) == 0, "oracle should be green once the flag exists"

    written = json.loads(contract.read_text())
    runs = written.get("runs")
    assert isinstance(runs, list), "verify recorded no run history"
    assert [r["exit_code"] for r in runs] == [1, 0], (
        f"both runs must survive in order; got {runs!r}"
    )


def test_last_run_still_reflects_the_most_recent_run(tmp_path):
    """CONTROL: the Stop gate reads `last_run`. Adding history must not move it.

    Guards the plausible-but-wrong fix of replacing `last_run` with `runs`, which
    would silently change what the gate sees.
    """
    thread_dir = tmp_path / "thread"
    sentinel = tmp_path / "done.flag"
    contract = _contract(thread_dir, f"test -f {sentinel}")

    _run_verify(thread_dir)
    sentinel.write_text("", encoding="utf-8")
    _run_verify(thread_dir)

    written = json.loads(contract.read_text())
    assert written["last_run"]["exit_code"] == 0
    assert written["last_run"]["timestamp"] == written["runs"][-1]["timestamp"]

    from would_block_stop import would_block_stop

    decision, reason = would_block_stop(
        {"contract": written, "scheduled": None, "recent_user_message": None}
    )
    assert (decision, reason) == ("allow", "verification_passed"), (
        "the gate must still release on a fresh green — history is measurement, "
        "not policy"
    )


def test_history_is_bounded(tmp_path):
    """CONTROL: a long-lived contract must not grow without limit."""
    thread_dir = tmp_path / "thread"
    contract = _contract(thread_dir, "true")

    for _ in range(12):
        _run_verify(thread_dir)

    runs = json.loads(contract.read_text())["runs"]
    assert len(runs) <= 50, f"run history is unbounded ({len(runs)} entries)"
    assert len(runs) == 12, "under the cap, every run should be kept"


def test_history_survives_a_contract_that_never_had_one(tmp_path):
    """A contract written before this change has no `runs` key. verify must add
    one rather than crash — the installed base is 191 such contracts."""
    thread_dir = tmp_path / "thread"
    contract = _contract(thread_dir, "true")
    data = json.loads(contract.read_text())
    data.pop("runs", None)
    contract.write_text(json.dumps(data), encoding="utf-8")

    assert _run_verify(thread_dir) == 0
    assert len(json.loads(contract.read_text())["runs"]) == 1
