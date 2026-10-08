"""omp's blocking `ask`, judged through the rendered Pi extension (escapement-fo4v).

Evidence: omp session 01a1183c (cake) spawned 16 background agents, then
called `ask` at 23:21Z. Every agent finished within ~40 minutes, but their
completion notices queued behind the open question for ~5h until the owner
answered. A blocking question must wait until the lead's in-flight lanes have
reported back, and must say what the lead will do if nobody answers.

Every input is a Pi event in the shape omp emits it: `task` results announce
spawned jobs, `async-result` custom messages deliver them, and the `ask` call
carries omp's `questions` list. Nothing here imports the gate.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))

from pi_extension_harness import Session, git_repo, pi_env, rendered_plugin, run  # noqa: E402

SPAWNED = (
    "Spawned 2 background agents using test-quality-reviewer, reviewer.\n"
    "- `AuditOracleReview` (job `AuditOracleReview`)\n"
    "- `AmendmentQualityReview` (job `AmendmentQualityReview`)\n\n"
    "Results auto-deliver; NEVER poll. Completely blocked? Call `wait` to receive "
    "the first settled job you started."
)


def delivered(*jobs: str) -> str:
    blocks = "\n".join(
        f"── Job {job} ({job}) ──\n<task-result id=\"{job}\" agent=\"reviewer\" status=\"completed\">"
        f"\n<output>{{}}</output>\n</task-result>"
        for job in jobs
    )
    return f"<system-notice>\n{len(jobs)} background jobs have completed.\n\n{blocks}\n</system-notice>"


def ask(question: str, recommended: int | None = 1) -> dict:
    entry = {
        "id": "okta_profile_control",
        "question": question,
        "options": [
            {"label": "Your account", "description": "Temporarily change two fields on your profile."},
            {"label": "Existing test account", "description": "Use the dedicated test account."},
        ],
        "header": "Okta test",
        "multi": False,
    }
    if recommended is not None:
        entry["recommended"] = recommended
    return {"i": "Choosing bounded production profile test account", "questions": [entry]}


WITH_DEFAULT = (
    "Which account may receive the temporary TEST-SERIAL value? "
    "If unanswered, I will use the existing test account and keep working."
)


@pytest.fixture(scope="module")
def plugin(tmp_path_factory):
    return rendered_plugin(tmp_path_factory)


def lead(tmp_path: Path) -> Session:
    session = Session(git_repo(tmp_path / "repo", {"README.md": "x\n", ".beads/.keep": ""}))
    session.user("Deliver items 2, 4, 5 and 6 to production.")
    task = {"i": "Reviewing", "tasks": [{"name": "AuditOracleReview"}, {"name": "AmendmentQualityReview"}]}
    session.tool_call("task", task)
    session.tool_result("task", task, SPAWNED)
    return session


def test_ask_is_denied_while_dispatched_lanes_are_still_running(plugin, tmp_path):
    session = lead(tmp_path)
    [outcome] = run(plugin, [session.tool_call("ask", ask(WITH_DEFAULT))], pi_env(tmp_path))

    result = outcome["result"]
    assert result and result["block"] is True, outcome
    reason = result["reason"]
    # Transparent: names the lanes the question would freeze.
    assert "AuditOracleReview" in reason and "AmendmentQualityReview" in reason
    # Repair: take their results first, or ask without blocking.
    assert "`wait`" in reason
    # Escape: the waiver, invokable from the ask itself.
    assert '--ask-gate-waiver "' in reason


def test_negative_control_ask_runs_once_every_lane_has_reported(plugin, tmp_path):
    session = lead(tmp_path)
    session.notice("async-result", delivered("AuditOracleReview", "AmendmentQualityReview"))
    [outcome] = run(plugin, [session.tool_call("ask", ask(WITH_DEFAULT))], pi_env(tmp_path))

    assert outcome["result"] is None, outcome


def test_one_unreported_lane_still_blocks_and_only_it_is_named(plugin, tmp_path):
    session = lead(tmp_path)
    session.notice("async-result", delivered("AuditOracleReview"))
    [outcome] = run(plugin, [session.tool_call("ask", ask(WITH_DEFAULT))], pi_env(tmp_path))

    result = outcome["result"]
    assert result and result["block"] is True, outcome
    assert "AmendmentQualityReview" in result["reason"]
    assert "AuditOracleReview" not in result["reason"]


def test_a_revived_parked_agent_is_running_again(plugin, tmp_path):
    session = lead(tmp_path)
    session.notice("async-result", delivered("AuditOracleReview", "AmendmentQualityReview"))
    steer = {"i": "Steering", "path": "agent://AuditOracleReview", "content": "Resume phase 1"}
    session.tool_call("write", steer)
    session.tool_result("write", steer, "Queued for AuditOracleReview (was parked; revived).")
    [outcome] = run(plugin, [session.tool_call("ask", ask(WITH_DEFAULT))], pi_env(tmp_path))

    result = outcome["result"]
    assert result and result["block"] is True, outcome
    assert "AuditOracleReview" in result["reason"]


@pytest.mark.parametrize(
    ("question", "recommended"),
    [
        # The evidence ask: a recommended option, but no word on what happens unanswered.
        ("Which account may receive the temporary TEST-SERIAL value?", 1),
        # Says it, but omp's own ask.timeout has no option to fall back to.
        (WITH_DEFAULT, None),
    ],
    ids=["unstated-default", "no-recommended-option"],
)
def test_ask_without_a_stated_default_is_denied_with_the_repair(plugin, tmp_path, question, recommended):
    session = Session(git_repo(tmp_path / "repo", {"README.md": "x\n"}))
    [outcome] = run(plugin, [session.tool_call("ask", ask(question, recommended))], pi_env(tmp_path))

    result = outcome["result"]
    assert result and result["block"] is True, outcome
    assert "If unanswered, I will" in result["reason"]
    assert "`recommended`" in result["reason"]


def test_negative_control_lone_lead_with_a_stated_default_may_ask(plugin, tmp_path):
    session = Session(git_repo(tmp_path / "repo", {"README.md": "x\n"}))
    [outcome] = run(plugin, [session.tool_call("ask", ask(WITH_DEFAULT))], pi_env(tmp_path))

    assert outcome["result"] is None, outcome


def test_reasoned_waiver_lets_the_ask_through_and_is_recorded(plugin, tmp_path):
    session = lead(tmp_path)
    waived = WITH_DEFAULT + ' --ask-gate-waiver "both reviewers wait on this same account choice"'
    shrugged = WITH_DEFAULT + ' --ask-gate-waiver "tbd"'
    outcomes = run(plugin, [
        session.tool_call("ask", ask(shrugged)),
        session.tool_call("ask", ask(waived)),
    ], pi_env(tmp_path))

    assert outcomes[0]["result"] and outcomes[0]["result"]["block"] is True, outcomes
    assert outcomes[1]["result"] is None, outcomes
    signal = Path(session.cwd) / ".beads" / ".gate-signal.jsonl"
    rows = [json.loads(line) for line in signal.read_text().splitlines()]
    waivers = [row for row in rows if row["gate"] == "pi_ask_gate" and row["decision"] == "waiver-accepted"]
    assert waivers and "both reviewers wait" in waivers[-1]["reason"], rows


def test_unreadable_ask_fails_open(plugin, tmp_path):
    session = lead(tmp_path)
    [outcome] = run(plugin, [session.tool_call("ask", {"questions": "not a list"})], pi_env(tmp_path))

    assert outcome["result"] is None, outcome
