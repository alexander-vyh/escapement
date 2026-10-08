"""_bd_command: which bead ids a shell command actually closes.

Business outcome: every bd-triggered hook (the shadow verifier, the discovery
close gate, the verify-oracle nudge) reacts to a bead close the shell will
really run, and never to the words `bd close` inside a commit message, an echo,
a PR body or a heredoc -- one shared reading of the command.

Source of truth: POSIX shell grammar -- quotes and heredoc bodies are data;
`;` `&&` `||` `|` `&` newlines and parens separate commands.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from _bd_command import pr_merges, subcommand_bead_ids  # noqa: E402


@pytest.mark.parametrize("command", [
    'git commit -m "fix && bd close es-1"',
    'echo "a; bd close es-1; b"',
    'gh pr create --title t --body "gh pr merge 12; bd close es-1"',
    "git commit -F - <<'EOF'\nfix\nbd close es-1\nEOF",
    "git commit -m \"$(cat <<'EOF'\nsummary\nbd close es-1\nEOF\n)\"",
    'eval "$(pyenv init -)" && pytest -q',
    "printf '%s\\n' 'bd close es-1' | cat",
    "cat <<-EOF\n\tbd close es-1\n\tEOF",
    'echo "x && bd close a1 && y"',
    'git commit -m "land it; bd close a1"',
], ids=["quoted-and", "echo-semicolons", "pr-body", "heredoc", "heredoc-in-substitution",
        "eval", "quoted-pipe", "tab-heredoc", "echo-and-chain", "commit-message"])
def test_text_that_mentions_a_close_closes_nothing(command):
    assert subcommand_bead_ids(command, "close") == []


@pytest.mark.parametrize("command, expected", [
    ("cd /x && bd close es-1", ["es-1"]),
    ("cd /x\nbd close es-1 es-2", ["es-1", "es-2"]),
    ("bd close es-1 -r done", ["es-1"]),
    # `fixed-it` is shaped like a bead id: only the value flag keeps it out.
    ("bd close es-7 -r fixed-it", ["es-7"]),
    ("bd close --session s-9 es-1", ["es-1"]),
    ("bd close --reason-file notes-1 es-1", ["es-1"]),
    ("bd close es-1 # merge-authorization-waiver: x-2", ["es-1"]),
    ("bd close es-1 2>&1 | tail -1", ["es-1"]),
    ("bd show x-1 # note\nbd close es-3", ["es-3"]),
    ("git commit -F - <<'EOF'\nmsg\nEOF\nbd close es-4", ["es-4"]),
    ("BEADS_ACTOR=me bd close es-5", ["es-5"]),
    ("(cd /x && bd close es-8)", ["es-8"]),
    # A quoted `#` is data, not a comment: the close after it is real.
    ('git commit -m "#1 fix"; bd close es-9', ["es-9"]),
    ("echo 'see #4' && bd close es-10", ["es-10"]),
], ids=["and", "newline", "short-reason", "reason-value-shaped-like-an-id", "session", "reason-file", "comment", "redirect",
        "after-comment", "after-heredoc", "env-prefix", "subshell", "quoted-hash-message",
        "quoted-hash-echo"])
def test_a_real_close_is_read_with_its_ids(command, expected):
    assert subcommand_bead_ids(command, "close") == expected


def test_unbalanced_quotes_read_as_no_command():
    assert subcommand_bead_ids('bd close es-1 --reason "unterminated', "close") == []


@pytest.mark.parametrize("command, expected", [
    ("gh pr merge 12 --squash", [("12", None)]),
    ("GH_TOKEN=x gh pr merge 12 -R o/r --squash", [("12", "o/r")]),
    ("gh pr merge --repo=o/r https://github.com/o/r/pull/7", [("https://github.com/o/r/pull/7", "o/r")]),
    ("gh pr merge -b 'body 99' -t subj --auto", [(None, None)]),
    ("cd /x && gh pr merge 3 && bd close es-1", [("3", None)]),
    ('gh pr merge --subject "#12 fix" 34', [("34", None)]),
    ("gh pr merge 5 # not 6", [("5", None)]),
], ids=["number", "token-and-repo", "repo-equals-url", "value-flags-bare", "chained",
        "quoted-hash-subject", "trailing-comment"])
def test_a_real_merge_is_read_with_its_pull_request(command, expected):
    assert pr_merges(command) == expected


@pytest.mark.parametrize("command", [
    'git commit -m "then gh pr merge 12"',
    "gh pr create --body \"$(cat <<'EOF'\ngh pr merge 12\nEOF\n)\"",
    "gh pr view 12",
], ids=["commit-message", "heredoc-body", "view"])
def test_text_that_mentions_a_merge_merges_nothing(command):
    assert pr_merges(command) == []
