"""shadow_verifier: what makes a landing would-block, for closes and for PR merges.

Business outcome (escapement-obwo acceptance)
---------------------------------------------
When a non-trivial behaviour change lands without proof, the gate-signal log
says a blocking verifier WOULD have stopped it. Each reason is its own code,
so the promotion review can count them apart:
  - oracle-failed   a closed bead's oracle failed on the landed commit;
  - no-oracle       the landing has no oracle to be judged by;
  - no-challenger   no mutation challenger / outcome verifier was dispatched
                    in the session (a code reviewer is not one).
`no-oracle` and `no-challenger` apply only when the landed diff touches
behaviour files (the TDD gate's classification). A docs, tests and config
landing is `not-applicable`. A PR merge is recorded with its number and head;
its oracle is NOT run, because CI already ran the tests at that head.

Independent source of truth
---------------------------
The records the real hook and its detached runner write; the file the oracle
writes when it runs; a fake `gh` that knows each PR's head, state and files.

Rejects
-------
- counting any review-word dispatch, or a role named only in a prompt, as a challenger;
- a missing oracle or challenger read as "can't tell", or charged to a docs change;
- one undifferentiated reason where oracle-failed and no-oracle must be counted apart;
- running an oracle for a merge, or a verdict for a PR that is not merged.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _codex_host as codex  # noqa: E402
from _shadow_world import assert_silent, git, verify_acceptance, world  # noqa: E402,F401


def _codes(rec: dict) -> list[str]:
    return rec["extras"]["reason_codes"]


# --- bead closes: (c) the challenger ------------------------------------------------


def test_a_behaviour_close_without_a_challenger_would_block(world):
    world.answer(42)
    world.add_bead("proj-a1")

    assert_silent(world.land("bd close proj-a1"))

    (rec,) = world.wait_final()
    assert rec["decision"] == "would-block", rec
    assert _codes(rec) == ["no-challenger"]
    assert rec["extras"]["beads"][0]["verify"] == "pass", "the oracle verdict is still recorded"
    assert "app.py" in rec["extras"]["behaviour_files"]


def test_positive_control_a_challenged_close_with_a_passing_oracle_would_pass(world):
    world.answer(42)
    world.add_bead("proj-a1")
    world.challenge()

    world.land("bd close proj-a1")

    (rec,) = world.wait_final()
    assert rec["decision"] == "would-pass", rec
    assert _codes(rec) == []
    assert [c["name"] for c in rec["extras"]["challengers"]] == ["mutation-challenger"]


@pytest.mark.parametrize("agent", [
    {"name": "rev", "subagent_type": "code-reviewer", "description": "Review the diff"},
    {"name": "rev", "subagent_type": "adversarial-reviewer"},
    {"name": "helper", "subagent_type": "general-purpose",
     "prompt": "Act as the mutation challenger and the outcome verifier."},
    {"name": "rev", "subagent_type": "code-reviewer", "description": "Review the challenger's tests"},
    {"name": "no-challenger-needed", "subagent_type": "general-purpose"},
    {"name": "outcome-verifier", "subagent_type": "adversarial-reviewer",
     "description": "act as outcome verifier"},
    {"name": "helper", "subagent_type": "general-purpose", "description": "Outcome verifier for obwo"},
], ids=["code-reviewer", "adversarial-reviewer", "role-only-in-the-prompt",
        "reviewer-describing-the-challenger", "negated-name", "reviewer-named-as-verifier",
        "role-only-in-the-description"])
def test_a_dispatch_that_is_not_a_challenger_does_not_count(world, agent):
    world.answer(42)
    world.add_bead("proj-a1")
    world.dispatch(**agent)

    world.land("bd close proj-a1")

    (rec,) = world.wait_final()
    assert rec["decision"] == "would-block", rec
    assert _codes(rec) == ["no-challenger"]


@pytest.mark.parametrize("agent", [
    {"name": "outcome-verifier", "subagent_type": "general-purpose"},
    {"name": "x", "subagent_type": "mutation-challenger"},
    {"name": "challenger-obwo", "subagent_type": "general-purpose"},
    {"name": "obwo_outcome_verifier"},
], ids=["verifier-name", "challenger-type", "challenger-name-with-suffix", "snake-case-verifier"])
def test_a_challenger_or_outcome_verifier_role_counts(world, agent):
    world.answer(42)
    world.add_bead("proj-a1")
    world.dispatch(**agent)

    world.land("bd close proj-a1")

    (rec,) = world.wait_final()
    assert rec["decision"] == "would-pass", rec


def test_what_the_challenger_said_is_recorded(world):
    world.answer(42)
    world.add_bead("proj-a1")
    world.challenge(output="Bad implementations:\n1. returns a constant 42\n2. reads a cached answer")

    world.land("bd close proj-a1")

    (rec,) = world.wait_final()
    (challenger,) = rec["extras"]["challengers"]
    assert challenger["names_bad_implementations"] is True


def test_a_codex_spawn_named_for_the_role_counts(world):
    world.answer(42)
    world.add_bead("proj-a1")
    spawn = {"hook_event_name": "PreToolUse", "tool_name": "collaborationspawn_agent",
             "tool_input": {"task_name": "outcome_verifier", "message": "ENCRYPTEDBLOB"},
             "session_id": world.session, "turn_id": "t-1", "cwd": str(world.repo)}

    # Through the generated Codex registration, as Codex runs it.
    output = codex.run("PreToolUse", "shadow_verifier.py", spawn, world.env)
    assert output is None or not output.get("hookSpecificOutput"), output

    world.land("bd close proj-a1")

    (rec,) = world.wait_final()
    assert rec["decision"] == "would-pass", rec


# --- bead closes: (b) the oracle -------------------------------------------------------


@pytest.mark.parametrize("acceptance", ["Looks right.", verify_acceptance("true")],
                         ids=["no-verify-block", "trivial-oracle"])
def test_a_behaviour_close_with_no_oracle_would_block_as_no_oracle(world, acceptance):
    world.answer(42)
    world.add_bead("proj-a1", acceptance)
    world.challenge()

    world.land("bd close proj-a1")

    (rec,) = world.wait_final()
    assert rec["decision"] == "would-block", rec
    assert _codes(rec) == ["no-oracle"]
    assert rec["extras"]["beads"][0]["verify"] == "no-oracle"


def test_a_failing_oracle_is_counted_apart_from_a_missing_one(world):
    world.answer(40)
    world.add_bead("proj-a1")
    world.challenge()

    world.land("bd close proj-a1")

    (rec,) = world.wait_final()
    assert rec["decision"] == "would-block", rec
    assert _codes(rec) == ["oracle-failed"]


@pytest.mark.parametrize("path", ["docs/guide.md", "tests/test_app.py", "config.yaml"],
                         ids=["docs", "tests", "config"])
def test_a_close_that_changes_no_behaviour_is_not_applicable(world, path):
    world.fresh_branch()
    world.change(path, "x = 1\n")
    world.add_bead("proj-a1", "Looks right.")  # no oracle, no challenger: neither is owed

    world.land("bd close proj-a1")

    (rec,) = world.wait_final()
    assert rec["decision"] == "not-applicable", rec
    assert rec["extras"]["behaviour_files"] == []
    assert world.oracle_ran() is None


# --- PR merges: (a) --------------------------------------------------------------------


def _merged_pr(world, files=("app.py",), **pr) -> str:
    world.answer(42)
    head = git(world.repo, "rev-parse", "HEAD")
    git(world.repo, "checkout", "-q", "main")
    world.add_pr("12", head, files=files, **pr)
    return head


def test_positive_control_a_challenged_merge_with_an_oracle_would_pass(world):
    head = _merged_pr(world)
    world.add_bead("proj-a1", status="in_progress")
    world.bind_session_contract("proj-a1")
    world.challenge()

    assert_silent(world.land("GH_TOKEN=x gh pr merge 12 -R o/r --squash"))

    (rec,) = world.wait_final()
    assert rec["decision"] == "would-pass", rec
    assert rec["extras"]["kind"] == "merge"
    assert rec["extras"]["pr_number"] == 12
    assert rec["extras"]["head_sha"] == head
    assert rec["extras"]["beads"][0]["verify"] == "declared"
    assert world.oracle_ran() is None, "a merge's oracle is CI's to run, not this hook's"


def test_a_merge_without_a_challenger_would_block(world):
    _merged_pr(world)
    world.add_bead("proj-a1", status="in_progress")
    world.bind_session_contract("proj-a1")

    world.land("gh pr merge 12")

    (rec,) = world.wait_final()
    assert rec["decision"] == "would-block", rec
    assert _codes(rec) == ["no-challenger"]


@pytest.mark.parametrize("bound", ["no-contract", "bead-without-oracle"])
def test_a_merge_with_no_oracle_would_block(world, bound):
    _merged_pr(world)
    world.challenge()
    if bound == "bead-without-oracle":
        world.add_bead("proj-a1", "Looks right.", status="in_progress")
        world.bind_session_contract("proj-a1")

    world.land("gh pr merge 12")

    (rec,) = world.wait_final()
    assert rec["decision"] == "would-block", rec
    assert _codes(rec) == ["no-oracle"]


def test_a_docs_only_merge_is_not_applicable(world):
    _merged_pr(world, files=("docs/guide.md", "README.md"))

    world.land("gh pr merge 12")

    (rec,) = world.wait_final()
    assert rec["decision"] == "not-applicable", rec


def test_a_pr_that_is_not_merged_is_not_a_landing(world):
    _merged_pr(world, state="OPEN")
    world.challenge()

    world.land("gh pr merge 12 --auto")

    (rec,) = world.wait_final()
    assert rec["decision"] == "not-landed", rec


def test_a_pr_gh_cannot_resolve_is_inconclusive(world):
    world.challenge()

    world.land("gh pr merge 99")

    (rec,) = world.wait_final()
    assert rec["decision"] == "inconclusive", rec
    assert "pull request could not be resolved" in rec["reason"]


# --- one verdict per landing -------------------------------------------------------------


def test_a_repeated_close_of_the_same_landing_is_recorded_once(world):
    world.answer(42)
    world.add_bead("proj-a1")
    world.challenge()

    world.land("bd close proj-a1")
    world.wait_final()
    world.land("bd close proj-a1")

    first, second = world.wait_final(count=2)
    assert first["decision"] == "would-pass", first
    assert second["decision"] == "duplicate", second
    assert second["extras"]["duplicate_of"] == first["extras"]["landing_id"]


def test_positive_control_a_close_at_a_new_head_is_a_new_landing(world):
    world.answer(42)
    world.add_bead("proj-a1")
    world.challenge()

    world.land("bd close proj-a1")
    world.wait_final()
    world.change("lib.py", "def helper():\n    return 2\n")
    world.land("bd close proj-a1")

    decisions = [r["decision"] for r in world.wait_final(count=2)]
    assert decisions == ["would-pass", "would-pass"], decisions


def test_a_merge_records_where_its_evidence_came_from(world):
    _merged_pr(world)
    world.add_bead("proj-a1", status="in_progress")
    world.bind_session_contract("proj-a1")
    world.challenge()

    world.land("gh pr merge 12")

    (rec,) = world.wait_final()
    extras = rec["extras"]
    assert extras["pr_number"] == 12
    assert extras["evidence_scope"] == "session"
    assert [b["id"] for b in extras["beads"]] == ["proj-a1"]
    assert extras["challengers"][0]["tool_use_id"]


def test_parallel_challenger_dispatches_are_all_kept(world):
    """Twelve dispatches at once (a fan-out) must leave twelve entries."""
    import json
    import subprocess

    from _shadow_world import HOOK

    events = [json.dumps({"hook_event_name": "PreToolUse", "tool_name": "Agent",
                          "tool_input": {"name": f"challenger-{n}", "subagent_type": "general-purpose"},
                          "session_id": world.session, "tool_use_id": f"toolu_{n}", "cwd": str(world.repo)})
              for n in range(12)]
    procs = [subprocess.Popen([sys.executable, "-B", str(HOOK)], stdin=subprocess.PIPE,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=world.env,
                              cwd=world.repo) for _ in events]
    for proc, event in zip(procs, events):
        proc.stdin.write(event.encode())
        proc.stdin.close()
    for proc in procs:
        proc.wait(timeout=60)
    world.answer(42)
    world.add_bead("proj-a1")

    world.land("bd close proj-a1")

    (rec,) = world.wait_final()
    assert len(rec["extras"]["challengers"]) == 12, [c["name"] for c in rec["extras"]["challengers"]]
