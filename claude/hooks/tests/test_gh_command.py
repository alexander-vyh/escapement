"""Unit tests for the shared _gh_command.is_gh_pr_command detector.

Oracle: fire on every real command-position invocation of `gh pr <verb>` (the shapes an
agent actually uses to ship, including the newline-compound cake shape that bypassed the
deployed merge gate), and NOT on a `gh pr <verb>` literal that does not invoke gh (quoted
echo string, commit message, inspection subcommand) — because the callers include a
BLOCKING gate that must not deny a command that never runs gh.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_HELPER = Path(__file__).resolve().parents[1] / "_gh_command.py"
_spec = importlib.util.spec_from_file_location("_gh_command", _HELPER)
mod = importlib.util.module_from_spec(_spec)
sys.modules["_gh_command"] = mod
assert _spec.loader is not None
_spec.loader.exec_module(mod)
is_gh_pr_command = mod.is_gh_pr_command


# --- MUST fire: real command-position ship invocations ---------------------------------

@pytest.mark.parametrize(
    "command",
    [
        "gh pr merge 1750 --auto --squash",
        "cd /wt && gh pr merge 1750",
        "cd /wt\ngh pr merge 1750 --auto --squash",   # newline compound — the cake shape
        "GH_TOKEN=ghp_x gh pr merge 262",             # inline-auth env prefix
        "FOO=1 BAR=2 gh pr merge 262",                # multiple env assignments
        "time gh pr merge 262",                       # exec wrapper
        "sudo gh pr merge 262",
        "(gh pr merge 262)",                          # subshell
        "$(gh pr merge 262)",                         # command substitution
        "echo hi; gh pr merge 262",                   # ; separator
        "true | gh pr merge 262",                     # pipe
        "gh   pr    merge   262",                     # irregular whitespace
    ],
)
def test_fires_on_real_merge_invocations(command):
    assert is_gh_pr_command(command, "merge") is True, command


def test_create_verb_and_multiverb():
    assert is_gh_pr_command("cd /wt && gh pr create --title X", "create") is True
    assert is_gh_pr_command("gh pr merge 1", "create", "merge") is True
    assert is_gh_pr_command("gh pr create --title X", "create", "merge") is True


# --- MUST NOT fire: literals / non-invocations / wrong verb ----------------------------

@pytest.mark.parametrize(
    "command",
    [
        'echo "run gh pr merge later"',               # quoted literal, not invoked
        'git commit -m "document gh pr merge flow"',  # commit message literal
        "gh pr view 262 --json state",                # inspection, wrong verb
        "gh pr checks 262",
        "gh pr list",
        "git push origin feat",                       # not gh
        "grep 'gh pr merge' notes.md",                # quoted search literal
        "gh pr merge-conflict-report",                # different subcommand: verb must be a whole token
    ],
)
def test_silent_on_non_invocations(command):
    assert is_gh_pr_command(command, "merge") is False, command


def test_wrong_verb_does_not_match():
    assert is_gh_pr_command("gh pr merge 1", "create") is False


def test_empty_and_bad_input_is_false():
    assert is_gh_pr_command("", "merge") is False
    assert is_gh_pr_command(None, "merge") is False  # type: ignore[arg-type]
    assert is_gh_pr_command("gh pr merge 1") is False  # no verbs given
