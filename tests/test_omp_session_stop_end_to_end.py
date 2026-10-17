"""omp judges a main session's stop at its awaited session_stop (escapement-b35y).

omp does not await an extension's agent_end, so a stop gate there raced the
session's shutdown and could not continue the run: in five headless runs that
changed code it never held one. omp awaits session_stop and continues the run
with a block's reason itself. It also clears stop_hook_active whenever a stop
is allowed, so each new prompt or background-job wake starts a fresh chain;
the gate, not omp, keeps an unchanged session from being held again.

The rendered extension is driven with omp-shaped events and runs the real stop
gates through the dispatcher. Each `run` is a fresh extension process, as each
omp run end is for the gate: its only memory is the harness state on disk.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pi_extension_harness import Session, follow_ups, git_repo, pi_env, rendered_plugin, run

GATE = "Escapement stop gate"
LEAD = "/sessions/-GitHub-cake/2026-10-07T21-19-19-623Z_lead.jsonl"


@pytest.fixture(scope="module")
def plugin(tmp_path_factory) -> Path:
    return rendered_plugin(tmp_path_factory)


def _write(repo: Path, session: Session, text: str) -> None:
    write = {"path": str(repo / "src" / "app.py"), "content": text}
    session.tool_call("write", write)
    (repo / "src" / "app.py").write_text(text, encoding="utf-8")
    session.tool_result("write", write, "Wrote src/app.py")


def _changed_code(tmp_path: Path, parent: str | None = None) -> tuple[Path, Session]:
    """A session that changed source code and declared nothing. The repository
    tracks beads, so gate signal lands in its .beads/."""
    repo = git_repo(tmp_path / "project", {"src/app.py": "VALUE = 1\n", ".beads/.gitkeep": ""})
    session = Session(repo, parent_session=parent)
    session.user("make VALUE configurable")
    _write(repo, session, "VALUE = 2\n")
    session.say("VALUE now reads 2.")
    return repo, session


def _held(outcome: dict) -> str | None:
    """The reason omp is handed to continue the run, if the stop was held."""
    result = outcome["result"]
    return result["reason"] if result and result.get("decision") == "block" else None


def _decisions(repo: Path) -> list[tuple[str, str]]:
    path = repo / ".beads" / ".gate-signal.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    return [(row["decision"], row["reason"]) for row in rows if row.get("gate") == "continuation-harness"]


def _last_incident(env: dict[str, str]) -> dict:
    return json.loads((Path(env["HARNESS_ROOT"]) / "incidents.jsonl").read_text().splitlines()[-1])


def test_session_stop_holds_an_undeclared_change_once_and_omp_continues_it(plugin, tmp_path):
    repo, session = _changed_code(tmp_path)
    env = pi_env(tmp_path)

    stop, ended = run(plugin, [session.session_stop(), session.omp_agent_end()], env)

    reason = _held(stop)
    assert reason and "no_declaration" in reason and "You are not done" in reason
    assert follow_ups(stop) == [], "omp continues the run itself; a follow-up would queue a second turn"
    assert [item["text"] for item in stop["sent"] if item["kind"] == "notify"] == [reason], (
        "omp's continuation turn is hidden, so the user must be shown why the run went on"
    )
    assert ended == {"result": None, "sent": []}, "omp's unawaited agent_end must not judge the same stop again"

    session.say("Still no declaration; stopping.")
    (continued,) = run(plugin, [session.session_stop(stop_hook_active=True)], env)

    assert _held(continued) is None, "the run the gate continued may stop: no loop"
    assert _decisions(repo) == [("block", "no_declaration")]


@pytest.mark.parametrize("source", ["new prompt", "background wake"])
def test_a_new_chain_over_unchanged_state_is_not_held_again(plugin, tmp_path, source):
    repo, session = _changed_code(tmp_path)
    env = pi_env(tmp_path)
    first, continued = run(plugin, [session.session_stop(), session.session_stop(stop_hook_active=True)], env)
    assert _held(first) and _held(continued) is None
    if source == "new prompt":
        session.user("what does VALUE control?")
    else:
        session.notice("async-result", "<system-notice>\n1 background job has completed.\n</system-notice>")
    session.say("VALUE sets the app's value.")

    # omp cleared stop_hook_active when it allowed the last stop.
    (again,) = run(plugin, [session.session_stop()], env)

    assert _held(again) is None
    (notice,) = [item for item in again["sent"] if item["kind"] == "message"]
    assert "no_declaration" in notice["text"], "the allowed stop still names what is unresolved"
    assert notice["options"] == {"deliverAs": "nextTurn"}, "a notice that triggered a turn would be the loop again"
    assert _decisions(repo) == [("block", "no_declaration"), ("allow", "stop_livelock_backstop")]
    assert {"held_for": "no_declaration", "budget": "unchanged"}.items() <= _last_incident(env).items()


def test_each_changed_state_is_held_until_the_session_ceiling(plugin, tmp_path):
    """Positive control: the bound is per state, not one block per session --
    a session that keeps changing code is held again, up to a ceiling."""
    repo, session = _changed_code(tmp_path)
    env = pi_env(tmp_path)

    held = []
    for value in (2, 3, 4, 5):
        if value > 2:
            session.user(f"now make it {value}")
            _write(repo, session, f"VALUE = {value}\n")
            session.say(f"VALUE now reads {value}.")
        stop, continued = run(plugin, [session.session_stop(), session.session_stop(stop_hook_active=True)], env)
        held.append(_held(stop) is not None)
        assert _held(continued) is None

    assert held == [True, True, True, False]
    assert _decisions(repo)[-1] == ("allow", "stop_livelock_backstop")
    assert {"held_for": "no_declaration", "budget": "ceiling"}.items() <= _last_incident(env).items()


@pytest.mark.parametrize("parent", [None, LEAD], ids=["main session", "worker"])
def test_omp_agent_end_runs_no_stop_gate(plugin, tmp_path, parent):
    """omp emits no session_stop for a subagent, and its agent_end is not
    awaited. A worker that changed code and ended with nothing for its parent
    is not continued from here: omp reminds it to yield and warns the parent."""
    repo, session = _changed_code(tmp_path, parent)
    session.branch.pop()  # no final message: an empty handoff

    (ended,) = run(plugin, [session.omp_agent_end()], pi_env(tmp_path))

    assert ended == {"result": None, "sent": []}
    assert _decisions(repo) == []


def test_pi_agent_end_holds_the_same_session_once_per_state(plugin, tmp_path):
    """Control for the routing: Pi has no session_stop, so its agent_end judges,
    under the same bound."""
    repo, session = _changed_code(tmp_path)
    env = pi_env(tmp_path)

    (ended,) = run(plugin, [session.agent_end()], env)
    session.user("what does VALUE control?")
    session.say("VALUE sets the app's value.")
    (again,) = run(plugin, [session.agent_end()], env)

    assert len([item for item in follow_ups(ended) if GATE in item["text"]]) == 1
    assert follow_ups(again) == []
    assert _decisions(repo) == [("block", "no_declaration"), ("allow", "stop_livelock_backstop")]
