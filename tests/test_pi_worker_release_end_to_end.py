"""A delegated omp/Pi worker can stop once its work is handed back (escapement-by3e).

Replays the 2026-10-07 cake session: workers whose session header names a
parent were re-opened forever with no_completion_or_resumption_proof, because
(1) the parent's "stop" arrives over IRC as a custom_message the transcript
dropped, (2) their contract's verify is the parent's production outcome, which
the worker is not authorized to run, and (3) nothing bounded the loop.

The rendered Pi extension is driven with Pi-shaped events; it runs the real
pi_stop_hook.py through the dispatcher. Each `run` is a fresh Pi process, so
every agent_end here is a first stop (stop_hook_active false), as each new
IRC-triggered run of a worker was.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
import shutil

import pytest

from pi_extension_harness import Session, follow_ups, git_repo, pi_env, rendered_plugin, run

GATE = "Escapement stop gate"
LEAD_FILE = "/sessions/-GitHub-cake/2026-10-07T21-19-19-623Z_lead.jsonl"


@pytest.fixture(scope="module")
def plugin(tmp_path_factory) -> Path:
    target = rendered_plugin(tmp_path_factory)
    # Exercise the authored host boundary against the installed gates before
    # the landing step regenerates packaged copies.
    canonical = Path(__file__).resolve().parents[1] / "agent-surfaces/hosts/pi/extensions"
    for source in canonical.glob("*.ts"):
        shutil.copyfile(source, target / "extensions" / source.name)
    return target


def _gate(outcome: dict) -> list[str]:
    return [item["text"] for item in follow_ups(outcome) if GATE in item["text"]]


def _session(tmp_path: Path, parent: str | None) -> tuple[Path, Session, dict]:
    """A session that changed code under a declared contract whose verify is
    the parent's production oracle and has never passed."""
    repo = git_repo(tmp_path / "project", {"src/app.py": "VALUE = 1\n", ".beads/.gitkeep": ""})
    session = Session(repo, parent_session=parent)
    env = pi_env(tmp_path)
    thread = Path(env["HARNESS_ROOT"]) / "threads" / session.id
    thread.mkdir(parents=True)
    (thread / "contract.json").write_text(json.dumps({
        "goal": "physical lifecycle readiness is live in production",
        "verification_command": "pytest tests/production -q",
        "expected_exit": 0,
        "created_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    }))
    session.user("Write the phase-1 test definitions only; do not run checks.")
    write = {"path": str(repo / "src" / "app.py"), "content": "VALUE = 2\n"}
    session.tool_call("write", write)
    (repo / "src" / "app.py").write_text(write["content"], encoding="utf-8")
    session.tool_result("write", write, "Wrote src/app.py")
    return repo, session, env


def _signal(repo: Path) -> list[dict]:
    path = repo / ".beads" / ".gate-signal.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    return [row for row in rows if row.get("gate") == "continuation-harness"]


# --- defect 1: the parent's stop over IRC is the worker's user releasing it ---

def test_parent_stop_over_irc_releases_the_worker(plugin, tmp_path):
    _repo, session, env = _session(tmp_path, parent=LEAD_FILE)
    session.irc("Main", "stop", from_parent=True)

    (outcome,) = run(plugin, [session.agent_end()], env)

    assert _gate(outcome) == []


@pytest.mark.parametrize("sender, from_parent", [("PhysicalOracleReview", False), ("Main", False)])
def test_irc_stop_not_from_the_parent_does_not_release(plugin, tmp_path, sender, from_parent):
    """Negative control: a sibling's "stop", or any IRC not marked fromParent,
    is not the worker's user speaking."""
    _repo, session, env = _session(tmp_path, parent=LEAD_FILE)
    session.irc(sender, "stop", from_parent=from_parent)

    (outcome,) = run(plugin, [session.agent_end()], env)

    assert len(_gate(outcome)) == 1


def test_extension_notice_saying_stop_does_not_release(plugin, tmp_path):
    """Negative control: a non-IRC custom_message is a notice, not speech."""
    _repo, session, env = _session(tmp_path, parent=LEAD_FILE)
    session.branch.append({
        "type": "custom_message", "customType": "escapement", "content": "stop",
        "display": True, "details": {"message": "stop", "fromParent": True},
        "timestamp": "2026-10-07T23:19:24.493Z",
    })

    (outcome,) = run(plugin, [session.agent_end()], env)

    assert len(_gate(outcome)) == 1


# --- defect 2: a worker is held to its delegated scope, not the parent outcome ---

def test_worker_that_handed_back_its_work_may_stop(plugin, tmp_path):
    repo, session, env = _session(tmp_path, parent=LEAD_FILE)
    session.say("Definitions written to src/app.py; no checks run, per the phase-1 barrier.")

    (outcome,) = run(plugin, [session.agent_end()], env)

    assert _gate(outcome) == []
    assert {"decision": "allow", "reason": "worker_handed_off"}.items() <= _signal(repo)[-1].items()


@pytest.mark.parametrize("event_messages", [[], None])
def test_yielded_worker_recovers_saved_final_response(plugin, tmp_path, event_messages):
    """Native OMP yield ends with an empty run after saving the final answer.
    That handoff must not be replaced by another synthetic continuation."""
    repo, session, env = _session(tmp_path, parent=LEAD_FILE)
    session.say("Committed definitions; report: 02-ingestion-oracle.md. Direct handoff delivered to Main.")
    session.notice("task-result", "Worker payload delivered to parent")
    event = session.agent_end()
    if event_messages is None:
        event["payload"].pop("messages")
    else:
        event["payload"]["messages"] = event_messages

    (outcome,) = run(plugin, [event], env)

    assert _gate(outcome) == []
    assert {"decision": "allow", "reason": "worker_handed_off"}.items() <= _signal(repo)[-1].items()


@pytest.mark.parametrize("newer", ["user", "parent", "tool_call", "text_and_tool_call", "aborted"])
def test_saved_assistant_is_not_handoff_for_unfinished_work(plugin, tmp_path, newer):
    repo, session, env = _session(tmp_path, parent=LEAD_FILE)
    session.say("Previous assignment handed off.")
    if newer == "user":
        session.user("Now write the remaining definitions.")
    elif newer == "parent":
        session.irc("Main", "Now write the remaining definitions.", from_parent=True)
    elif newer in {"tool_call", "text_and_tool_call"}:
        session.tool_call("read", {"path": "src/app.py"})
        if newer == "text_and_tool_call":
            session.branch[-1]["content"].insert(0, {"type": "text", "text": "Still investigating."})
    else:
        session.say("The operation was interrupted.")["stopReason"] = "aborted"
    event = session.agent_end()
    event["payload"]["messages"] = []

    (outcome,) = run(plugin, [event], env)

    assert len(_gate(outcome)) == 1
    assert {"decision": "block", "reason": "worker_no_handoff"}.items() <= _signal(repo)[-1].items()


def test_lead_saved_final_does_not_release_unverified_outcome(plugin, tmp_path):
    _repo, session, env = _session(tmp_path, parent=None)
    session.say("Definitions written; production outcome still unverified.")
    event = session.agent_end()
    event["payload"]["messages"] = []

    (outcome,) = run(plugin, [event], env)

    (text,) = _gate(outcome)
    assert "no_completion_or_resumption_proof" in text


def test_lead_with_unverified_contract_still_blocks(plugin, tmp_path):
    """Negative control: the same session with no parent is the outcome owner."""
    _repo, session, env = _session(tmp_path, parent=None)
    session.say("Definitions written to src/app.py; no checks run.")

    (outcome,) = run(plugin, [session.agent_end()], env)

    (text,) = _gate(outcome)
    assert "no_completion_or_resumption_proof" in text


# --- defect 3: a bounded backstop, never an unbounded loop ---

def test_worker_with_no_handoff_blocks_until_the_livelock_backstop(plugin, tmp_path):
    """A worker that changed code and ends with nothing for its parent to read
    is held -- but only for a bounded number of identical blocks; then it is
    let go and the livelock is recorded for half-life review."""
    repo, session, env = _session(tmp_path, parent=LEAD_FILE)

    blocked = run(plugin, [session.agent_end()], env) + run(plugin, [session.agent_end()], env) \
        + run(plugin, [session.agent_end()], env)
    for outcome in blocked:
        (text,) = _gate(outcome)
        assert "worker_no_handoff" in text
    (released,) = run(plugin, [session.agent_end()], env)

    assert _gate(released) == []
    assert {"decision": "allow", "reason": "worker_livelock_backstop"}.items() <= _signal(repo)[-1].items()


def test_lead_is_not_released_by_the_worker_backstop(plugin, tmp_path):
    """Negative control: the backstop is scoped to workers; a lead keeps its gate."""
    _repo, session, env = _session(tmp_path, parent=None)

    outcomes = [run(plugin, [session.agent_end()], env)[0] for _ in range(4)]

    assert all(len(_gate(outcome)) == 1 for outcome in outcomes)
