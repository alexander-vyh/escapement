#!/usr/bin/env python3
"""Stop-hook block messages must DRIVE CONTINUATION, not invite park-and-ask.

Source / oracle: 2026-06-01 incident + user directive — "the behavioral issue
has to be solved in code for all sessions, not just you remembering it." The
recurring premature-stop failure was the agent responding to a correct Stop
block by summarizing remaining work and asking the user what to do, instead of
continuing. The Stop-hook block message is the agent's LAST input before the
turn ends, so it is the all-sessions code lever: if it offers "ask the user to
release" as a co-equal exit, the model takes that easy door and parks.

Business invariant
------------------
Every agent-facing Stop-hook BLOCK message must (a) NOT present soliciting a
user release ("ask the user to release") as an agent action, (b) explicitly
forbid the wind-down (summarizing / asking-what-to-do-next), and (c) point at a
forward action — continue the work, or (when nothing is ready) ScheduleWakeup.

Fragile implementations these tests REJECT
-------------------------------------------
- The shipped soft-nag messages ("...(3) ask the user to release with 'stop'...")
  -> fail test_no_park_and_ask_door + test_forbids_winddown_explicitly.
- A message that drops the park-and-ask door but says nothing forward
  -> fails the continuation / wakeup assertions.

NOTE on the oracle: the ULTIMATE proof is observational (does the cross-session
premature-stop rate drop — bead 858 observe phase). These are property tests on
the message text, the strongest mechanical guard available pre-deploy; they lock
the regression (re-introducing the park-and-ask door) but cannot prove the model
obeys. That is named, not hidden.

Run: python3 -m pytest harness/tests/test_stop_messages.py -q
"""

from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "harness" / "bin"))

import stop_hook  # noqa: E402

# Every agent-facing BLOCK message, by name.
RESUMPTION = stop_hook.RESUMPTION_PROMPT.format(reason="no_completion_or_resumption_proof")
TASKS_REMAIN = stop_hook._TASK_MODE_DISPLAY["tasks_remain_in_queue"]
ALL_BLOCKED = stop_hook._TASK_MODE_DISPLAY["all_remaining_tasks_blocked"]
IMPLICIT = stop_hook._IMPLICIT_QUEUE_DISPLAY

ALL_MESSAGES = {
    "resumption": RESUMPTION,
    "tasks_remain": TASKS_REMAIN,
    "all_blocked": ALL_BLOCKED,
    "implicit": IMPLICIT,
}

# Messages where in-scope work plausibly exists -> must tell the agent to continue.
WORK_MESSAGES = ("resumption", "tasks_remain", "implicit")

_CONTINUE_VERBS = ("continue", "keep working", "keep going", "next concrete",
                   "do the next", "next ready")
_WINDDOWN_NOUNS = ("summariz", "what to do next", "hand off", "wind down")


def test_no_park_and_ask_door() -> None:
    """The exact door the agent keeps taking must be gone from every block message."""
    for name, msg in ALL_MESSAGES.items():
        assert "ask the user to release" not in msg.lower(), (
            f"{name} still offers park-and-ask ('ask the user to release') as an agent "
            "exit — that is the wind-down door agents take instead of continuing."
        )


def test_forbids_winddown_explicitly() -> None:
    """Each block message must explicitly prohibit the wind-down it guards against."""
    for name, msg in ALL_MESSAGES.items():
        low = msg.lower()
        assert "do not" in low or "don't" in low, (
            f"{name} lacks an explicit prohibition; a soft nag is what agents ignore."
        )
        assert any(n in low for n in _WINDDOWN_NOUNS), (
            f"{name} prohibits nothing nameable — it must forbid summarizing / "
            f"asking-what-to-do-next, got: {msg!r}"
        )


def test_work_messages_demand_continuation() -> None:
    """When in-scope work exists, the message must steer to the next action."""
    for name in WORK_MESSAGES:
        low = ALL_MESSAGES[name].lower()
        assert any(v in low for v in _CONTINUE_VERBS), (
            f"{name} blocks the stop but gives no forward push; agents need an explicit "
            f"continue-imperative, got: {ALL_MESSAGES[name]!r}"
        )


def test_blocked_message_points_to_wakeup() -> None:
    """With nothing ready (deps-blocked), the forward action is ScheduleWakeup, not asking."""
    low = ALL_BLOCKED.lower().replace(" ", "")
    assert "schedulewakeup" in low or "wakeup" in low, (
        "all_remaining_tasks_blocked must route to ScheduleWakeup as the forward exit."
    )


def test_legit_exits_preserved() -> None:
    """The genuine non-stop exits (verify, ScheduleWakeup) must remain discoverable."""
    low = RESUMPTION.lower()
    assert "verify" in low and ("schedulewakeup" in low.replace(" ", "") or "wakeup" in low), (
        "the general resumption prompt must still name verify + ScheduleWakeup as the real exits."
    )


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
