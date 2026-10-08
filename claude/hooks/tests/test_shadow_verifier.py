"""shadow_verifier: did a closed bead's frozen oracle pass on the commit that landed?

Business outcome
----------------
After an agent successfully closes a bead (`bd close <id>`), the gate-signal log
gains a `shadow_verifier` verdict: would a blocking verifier have stopped the
close, judged by the bead's own ```verify oracle run against the exact commit
the close landed on -- not the live tree the agent keeps editing. The close is
never touched, so the user can measure catches against false would-blocks
before deciding to enforce.

Independent source of truth
---------------------------
The `.gate-signal.jsonl` lines the real hook and its detached runner write, the
hook's stdout (empty = no decision on every host) and exit code, and the file
the oracle itself writes: which directory and commit it actually ran against.

Rejects
-------
- a verdict for a close that did not happen (failed command, bead still open);
- recording a pass without running the oracle, or running it on the live tree;
- treating a failing oracle as anything but would-block, or a missing one as a block;
- judging a close made with uncommitted changes as if the commit were the work;
- any output a host could read as a decision, on any input.

Budget, process, error and ownership bounds: test_shadow_verifier_bounds.py.
Which commands count as a close: test_bd_command_parsing.py.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _codex_host as codex  # noqa: E402
from _shadow_world import (  # noqa: E402,F401  (world is a fixture)
    HOOK,
    ROOT,
    assert_silent,
    git,
    verify_acceptance,
    world,
)


def test_passing_oracle_on_the_landed_commit_would_pass(world):
    world.answer(42)
    world.add_bead("proj-a1")
    world.challenge()
    payload = world.payload("bd close proj-a1 --reason done")

    proc = subprocess.run([sys.executable, "-B", str(HOOK)], input=json.dumps(payload),
                          capture_output=True, text=True, env=world.env, cwd=world.repo)

    assert_silent(proc)
    (rec,) = world.wait_final()
    head = git(world.repo, "rev-parse", "HEAD")
    assert rec["decision"] == "would-pass", rec
    assert rec["extras"]["beads"][0]["verify"] == "pass"
    ran = world.oracle_ran()
    assert ran is not None, "verify was recorded, not run"
    assert ran["head"] == head and Path(ran["cwd"]) != world.repo, "judged the live tree"
    (early,) = world.provisional()
    assert early["extras"]["landing_id"] == rec["extras"]["landing_id"]
    assert early["extras"]["head_sha"] == head
    assert early["extras"]["session_id"] == world.session
    assert early["extras"]["tool_use_id"] == payload["tool_use_id"]
    assert world.worktrees() == [str(world.repo.resolve())], "the judging checkout was left behind"


def test_failing_oracle_would_block(world):
    world.add_bead("proj-a1")

    assert_silent(world.land("bd close proj-a1"))

    (rec,) = world.wait_final()
    assert rec["decision"] == "would-block", rec
    assert rec["extras"]["beads"][0]["verify"] == "fail"
    assert rec["extras"]["beads"][0]["exit_code"] == 1
    assert "proj-a1: verify failed" in rec["reason"]


@pytest.mark.parametrize("later, expected", [(41, "would-pass"), (42, "would-block")],
                         ids=["breaks-after-close", "fixed-after-close"])
def test_the_verdict_is_about_the_landed_commit_not_what_came_after(world, later, expected):
    world.answer(42 if expected == "would-pass" else 41)
    landed = git(world.repo, "rev-parse", "HEAD")
    world.add_bead("proj-a1")
    world.challenge()

    world.land("bd close proj-a1")
    git(world.repo, "checkout", "-q", "-b", "after-close")
    world.answer(later)

    (rec,) = world.wait_final()
    assert rec["decision"] == expected, rec
    assert world.oracle_ran()["head"] == landed


def test_uncommitted_changes_at_close_are_inconclusive_and_run_nothing(world):
    world.answer(42)
    (world.repo / "app.py").write_text("def answer():\n    return 43\n")
    world.add_bead("proj-a1")

    assert_silent(world.land("bd close proj-a1"))

    (rec,) = world.wait_final()
    assert rec["decision"] == "inconclusive", rec
    assert "uncommitted changes at close" in rec["reason"]
    assert world.oracle_ran() is None


def test_tracker_export_churn_is_not_uncommitted_work(world):
    world.answer(42)
    world.change(".beads/issues.jsonl", "{}\n")
    (world.repo / ".beads" / "issues.jsonl").write_text('{"closed": true}\n')
    world.add_bead("proj-a1")
    world.challenge()

    world.land("bd close proj-a1")

    (rec,) = world.wait_final()
    assert rec["decision"] == "would-pass", rec


def test_a_close_that_did_not_close_the_bead_gets_no_verdict(world):
    """A denied, failed or typo'd close leaves the bead open; nothing landed."""
    world.answer(42)
    world.add_bead("proj-a1", status="open")

    world.land("bd close proj-a1")

    (rec,) = world.wait_final()
    assert rec["decision"] == "not-landed", rec
    assert world.oracle_ran() is None


def test_an_interrupted_command_is_not_a_close(world):
    world.add_bead("proj-a1")

    assert_silent(world.land("bd close proj-a1",
                             tool_response={"stdout": "", "stderr": "", "interrupted": True}))

    assert world.all_records() == []


def test_claude_registers_the_hook_only_after_successful_calls():
    """PostToolUseFailure is where Claude sends failed calls; this hook must not be there,
    and must not judge Bash before the call (PreToolUse), when it may still be denied.
    Agent dispatches are observed on PreToolUse (the dispatch) and PostToolUse (its reply)."""
    hooks = json.loads((ROOT / "plugins" / "escapement-claude" / "hooks" / "hooks.json").read_text())["hooks"]
    events = {(event, item.get("matcher")) for event, items in hooks.items() for item in items
              for hook in item["hooks"] if "shadow_verifier.py" in hook["command"]}
    assert events == {("PostToolUse", "Bash"), ("PreToolUse", "Agent"), ("PostToolUse", "Agent")}


@pytest.mark.parametrize("command", [
    "git status",
    'git commit -m "fix && bd close proj-a1"',
    'echo "a; bd close proj-a1; b"',
    "git commit -F - <<'EOF'\nmsg\nbd close proj-a1\nEOF",
    'git commit -m "then gh pr merge 12"',
])
def test_commands_that_close_nothing_record_nothing(world, command):
    world.add_bead("proj-a1")

    assert_silent(world.land(command))

    assert world.all_records() == []
    assert world.oracle_ran() is None


def test_a_close_from_outside_any_checkout_is_still_recorded(world, tmp_path):
    world.add_bead("proj-a1")
    gone = tmp_path / "gone"
    gone.mkdir()
    payload = world.payload("bd close proj-a1", cwd=str(gone))
    gone.rmdir()

    proc = subprocess.run([sys.executable, "-B", str(HOOK)], input=json.dumps(payload),
                          capture_output=True, text=True, env=world.env, cwd=tmp_path)

    assert_silent(proc)
    (rec,) = world.wait_final()
    assert rec["decision"] == "inconclusive", rec
    assert "no git checkout at close" in rec["reason"]


@pytest.mark.parametrize(
    "stdin",
    ["not json", "[]", json.dumps({"tool_name": "Bash", "tool_input": "bd close x"})],
)
def test_malformed_input_never_produces_a_decision(world, stdin):
    proc = subprocess.run([sys.executable, "-B", str(HOOK)], input=stdin,
                          capture_output=True, text=True, env=world.env, cwd=world.repo)
    assert_silent(proc)


def test_an_unwritable_signal_store_never_blocks_and_says_the_record_was_lost(world):
    world.add_bead("proj-a1")
    world.env["BEADS_DIR"] = str(world.tmp / "missing")
    world.env["GATE_SIGNAL_FALLBACK_DIR"] = "/dev/null/nope"

    proc = world.land("bd close proj-a1")

    assert_silent(proc)
    assert "shadow_verifier" in proc.stderr and "not recorded" in proc.stderr, proc.stderr


def test_codex_close_is_recorded_and_left_alone(world):
    world.add_bead("proj-a1")
    data = codex.payload("post_tool_use_bash_with_workdir", cwd=str(world.repo),
                         session_id=world.session, tool_input={"command": "bd close proj-a1"},
                         tool_response="✓ Closed proj-a1\n")

    output = codex.run("PostToolUse", "shadow_verifier.py", data, world.env)

    assert output is None or not output.get("hookSpecificOutput"), output
    (rec,) = world.wait_final()
    assert rec["decision"] == "would-block"
    assert rec["extras"]["host"] == "codex"


def test_a_worktree_close_records_into_the_root_checkouts_beads(world, tmp_path):
    root_beads = world.repo / ".beads"
    root_beads.mkdir()
    linked = tmp_path / "linked"
    git(world.repo, "worktree", "add", "-q", "-b", "other", str(linked))
    world.add_bead("proj-a1", "Looks right.")
    del world.env["BEADS_DIR"]

    assert_silent(world.land("bd close proj-a1", cwd=str(linked)))

    store = root_beads / ".gate-signal.jsonl"
    assert _wait(lambda: store.is_file() and len(_shadow_lines(store)) >= 2), "records stranded"
    assert {r["decision"] for r in _shadow_lines(store)} == {"provisional", "would-block"}


def _shadow_lines(path: Path) -> list[dict]:
    return [r for r in map(json.loads, path.read_text().splitlines()) if r.get("gate") == "shadow_verifier"]


def _wait(predicate, seconds: float = 30.0) -> bool:
    import time

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return predicate()
