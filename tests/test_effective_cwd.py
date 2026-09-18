"""Which directory a hook payload is about, resolved from the command itself.

Business outcome
----------------
A gate judges the repository the command touches. On 2026-09-18 a push of a
branch in one repository was blocked by an advisory whose finding was about
uncommitted test edits in a *different* repository — correct about a tree the
command never touched. Every false finding of that kind spends the reader's
attention and teaches them to dismiss the true ones.

Independent source of truth
---------------------------
Real directories on disk. A resolution that does not land on an existing
directory is not a resolution, so these tests create the trees they name
instead of asserting against string manipulation.

Invalid solution classes this suite rejects
-------------------------------------------
- trusting a declared or `cd`-named directory that does not exist
- reading a `cd` from anywhere other than leading position, where its effect
  on the rest of the command is no longer unambiguous
- rewriting a payload that names no command
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parents[1] / "claude" / "hooks"
spec = importlib.util.spec_from_file_location("effective_cwd", HOOKS / "_effective_cwd.py")
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def payload(command: str, session_cwd: Path, declared: str | None = None) -> dict:
    tool_input: dict[str, object] = {"command": command}
    if declared is not None:
        tool_input["cwd"] = declared
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": tool_input,
        "cwd": str(session_cwd),
    }


@pytest.fixture
def repos(tmp_path: Path) -> tuple[Path, Path]:
    session = tmp_path / "session-repo"
    other = tmp_path / "other-repo"
    session.mkdir()
    other.mkdir()
    return session, other


def test_a_call_that_names_its_own_directory_is_judged_there(repos):
    session, other = repos
    resolved = module.normalized(payload("git push", session, declared=str(other)))
    assert resolved["cwd"] == str(other.resolve())


def test_a_leading_cd_moves_the_judgment_with_the_command(repos):
    session, other = repos
    resolved = module.normalized(payload(f"cd {other} && git push", session))
    assert resolved["cwd"] == str(other.resolve())


def test_a_relative_cd_resolves_against_the_session_directory(repos):
    session, _ = repos
    (session / "nested").mkdir()
    resolved = module.normalized(payload("cd nested && git status", session))
    assert resolved["cwd"] == str((session / "nested").resolve())


def test_a_quoted_path_with_spaces_resolves(repos):
    session, _ = repos
    spaced = session / "two words"
    spaced.mkdir()
    resolved = module.normalized(payload("cd 'two words' && git status", session))
    assert resolved["cwd"] == str(spaced.resolve())


@pytest.mark.parametrize(
    "command",
    [
        "git push",                        # no cd at all
        "make && cd build && ./run",       # not leading: effect is ambiguous
        "cd",                              # bare cd (home) is not the named form
        "cd /nonexistent-xyz && git push",  # target does not exist
        "cd one two && git push",          # not the unambiguous single-arg form
        "cd 'unterminated && git push",    # unparseable segment
    ],
)
def test_the_session_directory_stands_when_nothing_unambiguous_is_named(command, repos):
    session, _ = repos
    resolved = module.normalized(payload(command, session))
    assert resolved["cwd"] == str(session)


def test_a_declared_directory_that_does_not_exist_falls_back_to_the_command(repos):
    """A bad declaration must not win over a good `cd`, nor invent a tree."""
    session, other = repos
    resolved = module.normalized(
        payload(f"cd {other} && git push", session, declared=str(session / "gone"))
    )
    assert resolved["cwd"] == str(other.resolve())


def test_a_payload_without_a_command_is_returned_unchanged(repos):
    session, _ = repos
    original = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(session)}
    assert module.normalized(original) is original
