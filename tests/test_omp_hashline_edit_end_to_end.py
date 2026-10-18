"""omp's edit tool is judged like a write (escapement-5cw1).

omp's default edit tool sends one string, `{"input": "[path#TAG]\\nPUT ..."}`,
that may change several files. The extension read edits only in Pi's
`{path, edits}` shape, so an omp edit reached no file gate and the Stop gate's
code-touch scan never saw it: in five Escapement runs on omp, every gate
denial came from a write and none from the 8-17 edits each run made.

The rendered extension is driven with the call shape omp sends (captured from
11,092 edit calls in local omp sessions), and the real gates judge it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pi_extension_harness import Session, git_repo, pi_env, rendered_plugin, run

PRIMARY = "targets the primary checkout"


@pytest.fixture(scope="module")
def plugin(tmp_path_factory) -> Path:
    return rendered_plugin(tmp_path_factory)


def _primary(tmp_path: Path) -> Path:
    """A beads-managed primary checkout: a .git directory beside .beads."""
    return git_repo(tmp_path / "project", {"src/app.py": "VALUE = 1\n", ".beads/.gitkeep": ""})


def _edit(*sections: str) -> dict:
    return {"input": "*** Begin Patch\n" + "".join(sections) + "*** End Patch\n"}


def _reason(outcome: dict) -> str | None:
    result = outcome["result"]
    return result["reason"] if result and result.get("block") is True else None


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("write", {"path": "src/app.py", "content": "VALUE = 2\n"}),
        ("edit", _edit("[src/app.py#1A2B]\nPUT 1.=1:\n+VALUE = 2\n")),
    ],
)
def test_an_edit_in_the_primary_checkout_is_denied_like_a_write(plugin, tmp_path, tool, arguments):
    repo = _primary(tmp_path)

    (outcome,) = run(plugin, [Session(repo).tool_call(tool, arguments)], pi_env(tmp_path))

    reason = _reason(outcome)
    assert reason and PRIMARY in reason and str(repo / "src" / "app.py") in reason, outcome


def test_every_file_of_a_multi_file_edit_is_judged(plugin, tmp_path):
    repo = _primary(tmp_path)
    elsewhere = tmp_path / "scratch" / "notes.txt"
    elsewhere.parent.mkdir()
    elsewhere.write_text("one\n", encoding="utf-8")
    edit = _edit(f"[{elsewhere}#AAAA]\nPUT >1:\n+two\n", "[src/app.py#BBBB]\nPUT 1.=1:\n+VALUE = 2\n")

    (outcome,) = run(plugin, [Session(repo).tool_call("edit", edit)], pi_env(tmp_path))

    reason = _reason(outcome)
    assert reason and PRIMARY in reason and str(repo / "src" / "app.py") in reason, outcome


@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        ("write", {"path": "~/notes.md", "content": "a note\n"}),
        ("edit", _edit("[~/notes.md#0000]\nPUT >$:\n+a note\n")),
    ],
)
def test_a_home_path_is_not_judged_as_the_session_checkout(plugin, tmp_path, tool, arguments):
    """Negative control: Pi and omp write `~/notes.md` in the home directory,
    so a session in the primary checkout may write it."""
    repo = _primary(tmp_path)

    (outcome,) = run(plugin, [Session(repo).tool_call(tool, arguments)], pi_env(tmp_path))

    assert outcome["result"] is None, outcome


def test_an_edit_of_implementation_code_gets_the_tdd_question(plugin, tmp_path):
    repo = git_repo(tmp_path / "project", {"pyproject.toml": "[project]\nname = 'demo'\n", "src/app.py": "VALUE = 1\n"})
    edit = _edit("[src/app.py#1A2B]\nPUT 1.=1:\n+VALUE = 3\n")

    (outcome,) = run(plugin, [Session(repo).tool_call("edit", edit)], pi_env(tmp_path))

    reason = _reason(outcome)
    assert reason and "TDD" in reason and "src/app.py" in reason, outcome


@pytest.mark.parametrize(
    ("operation", "blocked"),
    [
        # 990 lines plus 20 inserted is past the hard limit of 1000.
        ("PUT >990:\n", True),
        # The same 20 rows replacing lines 1-20 leave the file at 990.
        ("PUT 1.=20:\n", False),
    ],
)
def test_an_edit_is_held_to_the_file_size_limit_by_its_net_growth(plugin, tmp_path, operation, blocked):
    (tmp_path / "grown.py").write_text("".join(f"line {i}\n" for i in range(990)), encoding="utf-8")
    edit = _edit("[grown.py#C0DE]\n" + operation + "".join(f"+added {i}\n" for i in range(20)))

    (outcome,) = run(plugin, [Session(tmp_path).tool_call("edit", edit)], pi_env(tmp_path))

    reason = _reason(outcome)
    if blocked:
        assert reason and "grown.py" in reason and "1000" in reason, outcome
    else:
        assert outcome["result"] is None, outcome


def test_a_session_that_edited_code_must_declare_an_outcome_before_stopping(plugin, tmp_path):
    repo = _primary(tmp_path)
    session = Session(repo)
    session.user("make VALUE configurable")
    # The code file is the second of two: every file of the call counts.
    edit = _edit("[local://plan.md#AAAA]\nPUT >$:\n+- configurable VALUE\n", "[src/app.py#1A2B]\nPUT 1.=1:\n+VALUE = 2\n")
    session.tool_call("edit", edit)
    (repo / "src" / "app.py").write_text("VALUE = 2\n", encoding="utf-8")
    session.tool_result("edit", edit, "Updated src/app.py")
    session.say("VALUE now reads 2.")

    (stop,) = run(plugin, [session.session_stop()], pi_env(tmp_path))

    result = stop["result"]
    assert result and result.get("decision") == "block" and "no_declaration" in result["reason"], stop


def test_a_session_that_edited_only_its_notes_stops_freely(plugin, tmp_path):
    """Negative control: omp's local:// files are session notes, not code."""
    repo = _primary(tmp_path)
    session = Session(repo)
    session.user("plan the change")
    edit = _edit("[local://plan.md#AAAA]\nPUT >$:\n+- configurable VALUE\n")
    session.tool_call("edit", edit)
    session.tool_result("edit", edit, "Updated local://plan.md")
    session.say("Plan written.")

    (stop,) = run(plugin, [session.session_stop()], pi_env(tmp_path))

    assert stop["result"] is None, stop
