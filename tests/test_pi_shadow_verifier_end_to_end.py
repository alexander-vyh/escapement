"""shadow_verifier on Pi, driven through the rendered extension.

Business outcome: after a Pi agent successfully closes a bead, the gate-signal
log gains a `shadow_verifier` verdict from the bead's own verify oracle run on
the landed commit; a close whose tool result is an error gets nothing; and the
verifier adds nothing to the result the model reads. The only inputs are Pi
events (`tool_result`, Pi's PostToolUse).
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import pytest

from pi_extension_harness import Session, git, git_repo, pi_env, rendered_plugin, run

ACCEPTANCE = "Answer is 42.\n\n```verify\npython3 -c \"import app; raise SystemExit(app.answer() != 42)\"\n```\n"
CLOSE = {"command": "bd close proj-a1"}


@pytest.fixture(scope="module")
def plugin(tmp_path_factory):
    return rendered_plugin(tmp_path_factory)


@pytest.fixture
def repo(tmp_path):
    """A feature branch off a real remote default that changes behaviour (app.py)."""
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    work = git_repo(tmp_path / "work", {"app.py": "def answer():\n    return 41\n"})
    git(work, "remote", "add", "origin", str(origin))
    git(work, "push", "-q", "origin", "main")
    git(work, "remote", "set-head", "origin", "main")
    git(work, "checkout", "-q", "-b", "feature")
    (work / "app.py").write_text("def answer():\n    return 42\n", encoding="utf-8")
    git(work, "commit", "-qam", "answer")
    return work


@pytest.fixture
def env(tmp_path):
    shims = tmp_path / "bin"
    shims.mkdir()
    # Closed, and assigned to the repo's git user -- the actor bd defaults to:
    # the hook only runs the oracles of beads this actor owns.
    bead = {"id": "proj-a1", "title": "Answer", "status": "closed",
            "acceptance_criteria": ACCEPTANCE, "assignee": "Pi Test"}
    bd = shims / "bd"
    bd.write_text(
        "#!/bin/sh\n"
        f"if [ \"$1\" = show ] && [ \"$2\" = proj-a1 ]; then printf '%s\\n' '{json.dumps([bead])}'; exit 0; fi\n"
        "exit 1\n",
        encoding="utf-8",
    )
    bd.chmod(0o755)
    env = pi_env(tmp_path)
    env["PATH"] = f"{shims}:{env['PATH']}"
    return env


def _shadow_records(env, *, wait_for_final: bool) -> list[dict]:
    path = Path(env["GATE_SIGNAL_FALLBACK_DIR"]) / "gate-signal-fallback.jsonl"
    deadline = time.monotonic() + (40.0 if wait_for_final else 0.0)
    while True:
        lines = path.read_text().splitlines() if path.is_file() else []
        found = [r for r in map(json.loads, lines) if r.get("gate") == "shadow_verifier"]
        if not wait_for_final or any(r["decision"] != "provisional" for r in found) \
                or time.monotonic() > deadline:
            return found
        time.sleep(0.1)


def test_pi_successful_close_gets_a_verdict_and_the_result_is_untouched(plugin, env, repo):
    session = Session(repo)
    challenger = session.tool_call("subagent", {"agent": "mutation-challenger",
                                                "task": "Invent bad implementations."})
    session.tool_call("bash", CLOSE)
    _, outcome = run(plugin, [challenger, session.tool_result("bash", CLOSE, text="✓ Closed proj-a1")], env)

    assert outcome["result"] is None, "the verifier added to what the model reads"
    (rec,) = [r for r in _shadow_records(env, wait_for_final=True) if r["decision"] != "provisional"]
    assert rec["decision"] == "would-pass", rec
    assert rec["extras"]["host"] == "pi"
    assert rec["extras"]["beads"][0]["verify"] == "pass"


def test_pi_close_that_errored_gets_nothing(plugin, env, repo):
    session = Session(repo)
    session.tool_call("bash", CLOSE)
    event = session.tool_result("bash", CLOSE, text="Error: bead not found")
    event["payload"]["isError"] = True

    run(plugin, [event], env)

    time.sleep(1)
    assert _shadow_records(env, wait_for_final=False) == []
