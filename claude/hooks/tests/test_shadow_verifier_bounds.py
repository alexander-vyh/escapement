"""shadow_verifier under pressure: budgets, stuck processes, errors, ownership.

Business outcome
----------------
Closing a bead never waits on its oracle: the hook does at most ~2s of local
work and hands off to a detached runner, which owns the budget, the oracle's
process group, the throwaway checkout and the final record. Every close leaves
a final record the promotion review can count -- even when the oracle hangs,
git hangs, the runner is told to stop, or too many runners are busy -- and an
unjudgeable close is never counted as a would-block. Another actor's oracle
never runs.

Independent source of truth
---------------------------
The gate-signal lines written by the real hook process and its runner,
wall-clock time, the liveness of the oracle's own process, and `git worktree
list` (no judging checkout left behind).

Rejects
-------
- a hook that waits for the oracle, or for a hung git;
- an oracle or a judging checkout left behind past the budget or a SIGTERM;
- a timeout or a stopped runner counted as a would-block;
- cleanup that waits on a pipe an escaped descendant holds open;
- unbounded concurrent runners on one repository;
- an error record that discards the evidence already collected;
- a NaN/inf budget that silently disables the bound;
- running the oracle of a bead this actor and session do not own.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _shadow_world import (  # noqa: E402,F401  (world is a fixture)
    ELAPSED_BOUND,
    ROOT,
    TEST_BUDGET,
    assert_silent,
    verify_acceptance,
    world,
)

# Compound, so the shell cannot exec the sleeper: killing only the shell would
# leave the sleeper holding the output pipe and the runner waiting on it. The
# sleeper records its pid and its shell's pid (the runner's child) outside the repo.
SLEEPER = verify_acceptance(
    "python3 -c \"import os, pathlib, time; pathlib.Path(os.environ['SHADOW_TEST_MARKER'] + '.pid')"
    ".write_text(f'{os.getpid()} {os.getppid()}'); time.sleep(30)\"; true")


def _timed(fn):
    started = time.monotonic()
    result = fn()
    return result, time.monotonic() - started


def _wait_for(predicate, seconds: float = 15.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return predicate()


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _sleeper(world) -> tuple[int, int]:
    pid_file = Path(str(world.marker) + ".pid")
    assert _wait_for(pid_file.exists), "the runner never started the oracle"
    oracle, shell = map(int, pid_file.read_text().split())
    return oracle, shell


def _parent(pid: int) -> int:
    return int(subprocess.run(["ps", "-o", "ppid=", "-p", str(pid)], capture_output=True, text=True).stdout)


def _kill_group(pid: int) -> None:
    try:
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    except OSError:
        pass


def test_the_hook_returns_while_the_oracle_is_still_running(world):
    """A hook that waited would take the whole 30s budget. The wall-clock bound is
    far below that rather than tight (this suite shares loaded machines); the
    load-independent proof is that the oracle is alive and unjudged after return."""
    world.add_bead("proj-a1", SLEEPER)
    world.env["SHADOW_VERIFIER_BUDGET_SECONDS"] = "30"

    proc, elapsed = _timed(lambda: world.land("bd close proj-a1"))

    oracle, _ = _sleeper(world)
    try:
        assert_silent(proc)
        assert elapsed < 10, f"the hook waited on the check ({elapsed:.2f}s)"
        assert world.records() == [], "a verdict before the oracle finished: the hook waited"
        assert world.provisional(), "the hook wrote nothing before returning"
        assert _alive(oracle), "the oracle should still be running"
    finally:
        _kill_group(oracle)


@pytest.mark.parametrize("setting, bound", [(None, 8), ("600", 16)], ids=["2s-default", "capped-at-10s"])
def test_a_hung_git_cannot_hold_the_close(world, setting, bound):
    world.add_bead("proj-a1")
    world.slow_git("status", 30)
    del world.env["SHADOW_VERIFIER_SYNC_SECONDS"]
    if setting is not None:
        world.env["SHADOW_VERIFIER_SYNC_SECONDS"] = setting

    proc, elapsed = _timed(lambda: world.land("bd close proj-a1"))

    assert_silent(proc)
    assert elapsed < bound, f"the hook's synchronous work ran past its limit ({elapsed:.1f}s)"
    (rec,) = world.wait_final()
    assert rec["decision"] == "inconclusive", rec
    assert "working tree state unknown" in rec["reason"]


def test_the_sync_limit_is_honoured_when_raised(world):
    """A loaded machine gets the room it is given: a 4s `git status` under an 8s
    limit still yields a known tree state (the 2s default would not)."""
    world.add_bead("proj-a1")
    world.slow_git("status", 4)
    world.env["SHADOW_VERIFIER_SYNC_SECONDS"] = "8"

    world.land("bd close proj-a1")

    (rec,) = world.wait_final()
    assert "working tree state unknown" not in rec["reason"], rec
    assert rec["extras"]["dirty"] is False


def test_the_runner_kills_the_oracle_group_at_budget_and_records_inconclusive(world):
    world.add_bead("proj-a1", SLEEPER)
    world.challenge()
    world.env["SHADOW_VERIFIER_BUDGET_SECONDS"] = TEST_BUDGET

    (_, elapsed) = _timed(lambda: (world.land("bd close proj-a1"), world.wait_final()))

    (rec,) = world.records()
    oracle, _ = _sleeper(world)
    assert elapsed < ELAPSED_BOUND, f"the verdict came after the budget ({elapsed:.1f}s)"
    assert rec["decision"] == "inconclusive", rec
    assert rec["extras"]["beads"][0]["verify"] == "timeout"
    assert _wait_for(lambda: not _alive(oracle), 5), "the oracle outlived the budget"
    assert _wait_for(lambda: len(world.worktrees()) == 1, 5), "the judging checkout was left behind"


def test_sigterm_to_the_runner_kills_the_oracle_and_still_records(world):
    world.add_bead("proj-a1", SLEEPER)
    world.env["SHADOW_VERIFIER_BUDGET_SECONDS"] = "30"
    world.land("bd close proj-a1")
    oracle, shell = _sleeper(world)
    runner = _parent(shell)

    try:
        os.kill(runner, signal.SIGTERM)
        (rec,) = world.wait_final(seconds=15)
    finally:
        _kill_group(oracle)

    assert rec["decision"] == "inconclusive", rec
    assert "runner terminated" in rec["reason"]
    assert _wait_for(lambda: not _alive(oracle), 5), "the oracle outlived its runner"
    assert _wait_for(lambda: len(world.worktrees()) == 1, 5), "the judging checkout was left behind"


def test_runners_per_repository_are_capped(world):
    for bead in ("proj-a1", "proj-a2", "proj-a3"):
        world.add_bead(bead, SLEEPER)
    world.env["SHADOW_VERIFIER_BUDGET_SECONDS"] = TEST_BUDGET

    for bead in ("proj-a1", "proj-a2", "proj-a3"):
        world.land(f"bd close {bead}")

    finals = world.wait_final(count=3)
    busy = [r for r in finals if "runner busy" in r["reason"]]
    assert len(busy) == 1 and busy[0]["decision"] == "inconclusive", finals
    assert sorted(r["extras"]["beads"][0]["verify"] for r in finals if r not in busy) == ["timeout", "timeout"]


def test_one_budget_covers_every_bead(world):
    for bead in ("proj-a1", "proj-a2", "proj-a3"):
        world.add_bead(bead, verify_acceptance("python3 -c \"import time; time.sleep(30)\"; true"))
    world.challenge()
    world.env["SHADOW_VERIFIER_BUDGET_SECONDS"] = TEST_BUDGET

    (_, elapsed) = _timed(lambda: (world.land("bd close proj-a1 proj-a2 proj-a3"), world.wait_final()))

    (rec,) = world.records()
    assert elapsed < ELAPSED_BOUND, f"budget is per bead, not per close ({elapsed:.1f}s)"
    assert [b["verify"] for b in rec["extras"]["beads"]] == ["timeout", "budget-exhausted", "budget-exhausted"]
    assert rec["decision"] == "inconclusive"


def test_escaped_grandchild_holding_the_pipe_cannot_stall_the_record(world):
    world.add_bead("proj-a1", verify_acceptance(
        "python3 -c \"import os, time; os.setsid(); time.sleep(60)\"; true"))
    world.env["SHADOW_VERIFIER_BUDGET_SECONDS"] = TEST_BUDGET

    (_, elapsed) = _timed(lambda: (world.land("bd close proj-a1"), world.wait_final(seconds=70)))

    (rec,) = world.records()
    # A runner that waited on the escaped holder's pipe would take the full 60s;
    # the bound sits far below that and far above budget + drain under load.
    assert elapsed < 30, f"cleanup waited on an escaped pipe holder ({elapsed:.1f}s)"
    assert rec["extras"]["beads"][0]["verify"] == "timeout"


def test_oracle_that_passes_but_leaves_a_background_child_is_a_pass(world):
    world.answer(42)
    world.add_bead("proj-a1", verify_acceptance("python3 check.py && (sleep 20 &)"))
    world.challenge()
    world.env["SHADOW_VERIFIER_BUDGET_SECONDS"] = TEST_BUDGET

    (_, elapsed) = _timed(lambda: (world.land("bd close proj-a1"), world.wait_final()))

    (rec,) = world.records()
    assert elapsed < ELAPSED_BOUND, f"waited on the pipe, not the oracle's exit ({elapsed:.1f}s)"
    assert rec["decision"] == "would-pass", rec


def test_output_and_command_are_kept_bounded(world):
    world.answer(42)
    long_tail = " ".join(["--verbose"] * 60)
    world.add_bead("proj-a1", verify_acceptance(
        f"python3 -c \"print('x' * 5000000); print('END')\" && python3 check.py {long_tail}"))

    world.land("bd close proj-a1")

    (rec,) = world.wait_final()
    bead = rec["extras"]["beads"][0]
    assert bead["verify"] == "pass", rec
    assert 0 < len(bead["output_tail"]) <= 400 and bead["output_tail"].rstrip().endswith("END")
    assert len(bead["command"]) <= 200


def test_a_runner_failure_is_an_error_that_keeps_its_evidence(world, tmp_path):
    """A broken install (no contract reader) must not masquerade as a verdict."""
    vendored = tmp_path / "plugin" / "claude" / "hooks"
    shutil.copytree(ROOT / "claude" / "hooks", vendored, ignore=shutil.ignore_patterns("tests"))
    (tmp_path / "plugin" / "harness" / "bin").mkdir(parents=True)
    for name in ("derive_contract.py", "init_contract.py"):
        shutil.copy(ROOT / "harness" / "bin" / name, tmp_path / "plugin" / "harness" / "bin" / name)
    world.add_bead("proj-a1")

    proc = subprocess.run([sys.executable, "-B", str(vendored / "shadow_verifier.py")],
                          input=json.dumps(world.payload("bd close proj-a1")), capture_output=True,
                          text=True, env=world.env, cwd=world.repo, timeout=60)

    assert_silent(proc)
    (rec,) = world.wait_final()
    assert rec["decision"] == "error", rec
    assert "ModuleNotFoundError" in rec["reason"]
    assert rec["extras"]["head_sha"], "the evidence before the failure was dropped"
    assert rec["extras"]["landing_id"] == world.provisional()[0]["extras"]["landing_id"]


@pytest.mark.parametrize("budget", ["nan", "inf", "-inf"])
def test_a_non_finite_budget_falls_back_to_the_default(world, budget):
    from _shadow_run import DEFAULT_BUDGET_SECONDS

    world.answer(42)
    world.add_bead("proj-a1")
    world.challenge()
    world.env["SHADOW_VERIFIER_BUDGET_SECONDS"] = budget

    world.land("bd close proj-a1")

    (rec,) = world.wait_final()
    assert rec["extras"]["budget_seconds"] == DEFAULT_BUDGET_SECONDS
    assert rec["decision"] == "would-pass", rec


def test_a_foreign_beads_oracle_is_not_run(world):
    world.answer(42)
    world.add_bead("proj-a1", assignee="someone-else")
    world.challenge()

    world.land("bd close proj-a1")

    (rec,) = world.wait_final()
    bead = rec["extras"]["beads"][0]
    assert bead["verify"] == "not-run" and "foreign bead" in bead["detail"], bead
    assert world.oracle_ran() is None
    assert rec["decision"] == "inconclusive", rec


@pytest.mark.parametrize("ownership", ["actor", "session-claim"])
def test_an_owned_beads_oracle_runs(world, ownership):
    world.answer(42)
    world.add_bead("proj-a1", assignee="someone-else")
    world.challenge()
    if ownership == "actor":
        world.env["BEADS_ACTOR"] = "someone-else"
    else:
        world.bind_session_contract("proj-a1")

    world.land("bd close proj-a1")

    (rec,) = world.wait_final()
    assert rec["decision"] == "would-pass", rec
    assert world.oracle_ran() is not None


@pytest.mark.parametrize("assignee", ["", "someone-else"], ids=["unassigned", "foreign"])
def test_a_missing_oracle_is_reported_whoever_owns_the_bead(world, assignee):
    """Ownership gates RUNNING an oracle, not reading one: a bead with no
    oracle is `no-oracle` even when its oracle would not have been run."""
    world.answer(42)
    world.add_bead("proj-a1", acceptance="Looks right.", assignee=assignee)

    world.land("bd close proj-a1")

    (rec,) = world.wait_final()
    assert rec["extras"]["beads"][0]["verify"] == "no-oracle", rec
    assert world.oracle_ran() is None
