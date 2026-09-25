"""Drive the rendered Pi extension to the end of a run that weakened a test,
and see oracle_downgrade_stop act on Pi: the advisory reaches the session
without continuing the run (it never blocks on any host), and a run that
strengthened the test hears nothing from it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pi_extension_harness import Session, follow_ups, git_repo, pi_env, rendered_plugin, run

ADVISORY = "Oracle-downgrade advisory"
STRONG = "def test_total():\n    assert total() == 42\n    assert count() == 7\n"
WEAK = "def test_total():\n    assert total()\n"


@pytest.fixture(scope="module")
def plugin(tmp_path_factory) -> Path:
    return rendered_plugin(tmp_path_factory)


def _run_rewriting_the_test(plugin: Path, tmp_path: Path, text: str) -> dict:
    repo = git_repo(tmp_path / "project", {"tests/test_total.py": STRONG})
    session = Session(repo)
    session.user("tidy the total test")
    edit = {"path": "tests/test_total.py", "edits": [{"oldText": STRONG, "newText": text}]}
    session.tool_call("edit", edit)
    (repo / "tests" / "test_total.py").write_text(text, encoding="utf-8")
    session.tool_result("edit", edit, "Edited tests/test_total.py")
    session.say("Tidied the test.")
    (outcome,) = run(plugin, [session.agent_end()], pi_env(tmp_path))
    return outcome


def _advisories(outcome: dict) -> list[dict]:
    return [item for item in outcome["sent"] if ADVISORY in item["text"]]


def test_pi_weakened_test_is_shown_without_continuing_the_run(plugin, tmp_path):
    outcome = _run_rewriting_the_test(plugin, tmp_path, WEAK)

    (advisory,) = _advisories(outcome)
    assert advisory["kind"] == "message", "the advisory is a session message, not a user turn"
    assert "tests/test_total.py" in advisory["text"] and "test_total" in advisory["text"]
    assert advisory["options"] == {"triggerTurn": False}, "an advisory must not continue the Pi run"
    assert not any(ADVISORY in item["text"] for item in follow_ups(outcome))


def test_pi_strengthened_test_is_silent(plugin, tmp_path):
    """Negative control: adding an assertion is not a downgrade."""
    outcome = _run_rewriting_the_test(plugin, tmp_path, STRONG + "    assert extra() == 1\n")

    assert _advisories(outcome) == []
