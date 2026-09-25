"""context_burn_detector on Pi, driven through the rendered extension.

Business outcome: a Pi main thread that reads source file after source file is
told, once, to hand the research to a pi-subagents child (a scout), and the
count starts over when it does dispatch one. Pi agents also read files through
`bash` (`cat`), which counts the same as `read`. Targeted reads stay cheap.

Weights (the hook's contract): a full read of a source file costs 5, a ranged
read 1; the default threshold is 10. The notice is advisory: it arrives as a
steer message and never blocks the read. The only inputs are Pi events.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pi_extension_harness import Session, notices, pi_env, rendered_plugin, run

NUDGE = "Context-burn threshold crossed"


@pytest.fixture(scope="module")
def plugin(tmp_path_factory):
    return rendered_plugin(tmp_path_factory)


@pytest.fixture
def env(tmp_path):
    env = pi_env(tmp_path)
    env.pop("CONTEXT_BURN_THRESHOLD", None)
    return env


@pytest.fixture
def session(tmp_path):
    session = Session(tmp_path)
    yield session
    Path(f"/tmp/context_burn_{session.id}.json").unlink(missing_ok=True)
    Path(f"/tmp/claude-review-gate/{session.id}.json").unlink(missing_ok=True)


def _read(session: Session, name: str, **extra) -> dict:
    return session.tool_call("read", {"path": name, **extra})


def test_pi_full_source_reads_cross_the_threshold_once(plugin, env, session):
    outcomes = run(plugin, [_read(session, "a.py"), _read(session, "b.py"), _read(session, "c.py")], env)

    assert all(outcome["result"] is None for outcome in outcomes), "the nudge never blocks a read"
    first, crossing, after = (notices(outcome) for outcome in outcomes)
    assert NUDGE not in first
    assert NUDGE in crossing
    assert "subagent tool with a scout agent" in crossing
    assert "TeamCreate" not in crossing and "spawn_agent" not in crossing
    assert NUDGE not in after, "the notice fires once per crossing"


def test_pi_subagent_dispatch_resets_the_count(plugin, env, session):
    calls = [
        _read(session, "a.py"),
        _read(session, "b.py"),
        session.tool_call("subagent", {"agent": "scout", "task": "Map the config loader."}),
        _read(session, "c.py"),
        _read(session, "d.py"),
    ]
    outcomes = run(plugin, calls, env)
    texts = [notices(outcome) for outcome in outcomes]

    assert NUDGE in texts[1]
    assert NUDGE not in texts[3], "the dispatch started the count over"
    assert NUDGE in texts[4], "and re-armed the notice for the next crossing"


def test_pi_bash_cat_of_source_counts_as_a_read(plugin, env, session):
    calls = [session.tool_call("bash", {"command": f"cat {name}"}) for name in ("a.py", "b.py")]
    _, crossing = run(plugin, calls, env)

    assert NUDGE in notices(crossing)


def test_pi_targeted_reads_stay_under_the_threshold(plugin, env, session):
    calls = [_read(session, f"{name}.py", offset=1, limit=40) for name in "abcdefghi"]
    outcomes = run(plugin, calls, env)

    assert all(NUDGE not in notices(outcome) for outcome in outcomes)
