"""Tests for wakeup_dispatch.py — poll-until-ready routing.

Load-bearing invariants:
  - a cheap poll NEVER spawns Claude (not-ready → "reschedule", no resume/handoff);
  - the eventual wake is a FRESH-session "handoff" on a CHEAP model, never a big-context
    "--resume" — regardless of how long (minutes/hours) the wait lasted;
  - a job that never finishes escalates ONCE at its deadline, not polls forever.
"""
import datetime as dt
import json
import pathlib
import sys

BIN = pathlib.Path(__file__).resolve().parent.parent / "bin"
sys.path.insert(0, str(BIN))

import wakeup_dispatch as wd


def _runner(code, out=""):
    return lambda command: (code, out)


# --- resume / back-compat (same-session, small context only) --------------

def test_resume_kind_resumes_with_prompt():
    a = wd.dispatch({"kind": "resume", "prompt": "continue the migration"})
    assert a == {"action": "resume", "prompt": "continue the migration"}


def test_missing_kind_is_resume_backcompat():
    a = wd.dispatch({"prompt": "pick up where you left off"})
    assert a["action"] == "resume"


# --- check: NOT ready → cheap reschedule, NO Claude (the GCP-wait core) ----

def test_not_ready_reschedules_without_spawning_claude():
    a = wd.dispatch(
        {"kind": "check", "command": "gh pr view 5 -q .state | grep -q MERGED",
         "poll_interval": 600, "escalate_prompt": "PR merged — finish release notes."},
        run_cmd=_runner(1),  # non-zero = not merged yet
    )
    assert a["action"] == "reschedule"
    assert a["reason"] == "not_ready"
    assert a["poll_interval"] == 600  # polls again later, no resume/handoff


def test_runner_error_reschedules_transiently():
    def boom(command):
        raise OSError("gh hiccup")
    a = wd.dispatch({"kind": "check", "command": "x"}, run_cmd=boom)
    assert a["action"] == "reschedule"  # transient errors keep polling cheaply


def test_invalid_poll_interval_defaults_instead_of_crashing_or_spinning():
    for bad in ("not-an-int", 0, -30):
        a = wd.dispatch({"kind": "check", "command": "x", "poll_interval": bad},
                        run_cmd=_runner(1))
        assert a["action"] == "reschedule"
        assert a["poll_interval"] == wd.DEFAULT_POLL_INTERVAL


# --- check: READY → fresh handoff on a cheap model, NEVER resume ----------

def test_ready_hands_off_fresh_on_cheap_model():
    a = wd.dispatch(
        {"kind": "check", "command": "true", "escalate_prompt": "PR #5 merged — finish up."},
        run_cmd=_runner(0),  # exit 0 = condition met
    )
    assert a["action"] == "handoff"
    assert a["prompt"] == "PR #5 merged — finish up."
    assert a["model"] == wd.DEFAULT_HANDOFF_MODEL  # #5: cheap by default, not Opus 1M


def test_handoff_model_overridable():
    a = wd.dispatch({"kind": "check", "command": "true", "escalate_prompt": "go",
                     "model": "sonnet"}, run_cmd=_runner(0))
    assert a["model"] == "sonnet"


# --- check: deadline → escalate ONCE, don't poll forever ------------------

def test_past_deadline_escalates_via_handoff():
    past = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)).isoformat()
    a = wd.dispatch(
        {"kind": "check", "command": "false", "deadline": past, "escalate_prompt": "check the job"},
        run_cmd=_runner(1),  # still not ready, but past deadline
    )
    assert a["action"] == "handoff"
    assert a["reason"] == "poll_deadline"
    assert "did not complete" in a["prompt"].lower()


def test_before_deadline_still_reschedules():
    future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2)).isoformat()
    a = wd.dispatch({"kind": "check", "command": "false", "deadline": future},
                    run_cmd=_runner(1))
    assert a["action"] == "reschedule"


# --- fail-safe + the hard invariant ---------------------------------------

def test_check_no_command_is_noop():
    assert wd.dispatch({"kind": "check"}, run_cmd=_runner(0))["action"] == "noop"


def test_unknown_kind_is_noop():
    assert wd.dispatch({"kind": "banana"}, run_cmd=_runner(0))["action"] == "noop"


def test_check_NEVER_yields_resume_action():
    # Locks the invariant: a check (poll) must never trigger a big-context --resume.
    for runner in (_runner(0), _runner(1), _runner(137)):
        a = wd.dispatch({"kind": "check", "command": "x", "escalate_prompt": "go"},
                        run_cmd=runner)
        assert a["action"] != "resume"


def test_scheduled_schema_declares_check_contract():
    schema = json.loads(
        (pathlib.Path(__file__).resolve().parent.parent / "schemas" / "scheduled.schema.json").read_text()
    )
    props = schema["items"]["properties"]
    for key in ("kind", "command", "escalate_prompt", "poll_interval", "deadline", "model"):
        assert key in props
    assert props["kind"]["enum"] == ["check", "resume"]
    assert props["poll_interval"]["minimum"] == wd.MIN_POLL_INTERVAL
    assert props["poll_interval"]["maximum"] == wd.MAX_POLL_INTERVAL
    assert "condition met" in props["command"]["description"].lower()
    assert "handoff" in props["escalate_prompt"]["description"].lower()
    check_requirements = [
        branch.get("then", {}).get("required", [])
        for branch in schema["items"].get("allOf", [])
    ]
    assert ["command"] in check_requirements
