"""shell_write_gate attribution: whose write is it?

Many sessions share one checkout, so a dirty file is not proof that this
session's command wrote it. The hook pairs a snapshot taken just before the
command with one just after, by the host's tool-call id. Wrong implementations
these reject: blaming dirt that was there before, or that another session
wrote between calls; comparing against an earlier call's snapshot when this
call's before-half is missing; treating a failed git call as a clean tree;
naming files a pull, merge or reset brought in; missing a write the command
committed, or one followed by a non-zero exit.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import _shell_write_harness as harness
from _shell_write_harness import BRIEF, HEREDOC, HOOK, Shell, _feedback, _git, env, repo, signals  # noqa: F401


def test_dirt_from_before_the_session_is_not_blamed(repo, env):
    """Negative control: src/app.py was already dirty when this session started."""
    (repo / "src" / "app.py").write_text("VALUE = 7\n")
    (repo / "src" / "legacy.py").write_text("OLD = 1\n")
    shell = Shell(repo, env)
    assert shell.bash("ls") is None
    assert shell.bash("echo more >> docs/README.md") is None


def test_another_sessions_writes_are_not_blamed(repo, env):
    """Session B writes between session A's commands; A's next command is innocent."""
    a, b = Shell(repo, env), Shell(repo, env)
    assert a.bash("ls") is None
    assert "src/app.py" in _feedback(b.bash(HEREDOC)), "B wrote it, so B is told"
    assert a.bash("ls") is None, "A must not be blamed for B's shell write"
    (repo / "src" / "other.py").write_text("B = 1\n")  # B again, through its Edit tool
    assert a.bash("git status --short") is None, "nor for B's edit-tool write"


def test_this_sessions_heredoc_is_held_amid_foreign_dirt(repo, env):
    """Positive control: foreign dirt exists, and this session's own write still reports."""
    (repo / "src" / "legacy.py").write_text("OLD = 1\n")
    reason = _feedback(Shell(repo, env).bash("cat > src/pricing.py <<'EOF'\nRATE = 2\nEOF"))
    assert "src/pricing.py" in reason
    assert "legacy.py" not in reason, "only this session's write is named"


def test_dirty_before_then_changed_by_this_session_is_held(repo, env):
    (repo / "src" / "app.py").write_text("VALUE = 7\n")
    shell = Shell(repo, env)
    assert shell.bash("ls") is None
    reason = _feedback(shell.bash("echo 'VALUE = 8' > src/app.py"))
    assert "src/app.py" in reason


def test_without_its_pre_snapshot_a_call_names_nothing(repo, env):
    """A host that sends only the after-call half, or a before-half that was
    killed or skipped: there is nothing to compare this call with, so it stays
    silent -- for every call, not just the first -- rather than compare with an
    earlier call and inherit every foreign write made in between."""
    shell = Shell(repo, env, pre=False)
    assert shell.bash("ls") is None
    (repo / "src" / "foreign.py").write_text("THEIRS = 1\n")  # another session
    assert shell.bash(HEREDOC) is None
    assert shell.bash("echo 'RATE = 2' > src/pricing.py") is None


def test_a_skipped_pre_half_does_not_fall_back_to_an_older_snapshot(repo, env):
    shell = Shell(repo, env)
    assert shell.bash("ls") is None
    (repo / "src" / "foreign.py").write_text("THEIRS = 1\n")  # another session
    shell.pre = False  # this call's before-half was killed by the host
    assert shell.bash(HEREDOC) is None
    shell.pre = True
    reason = _feedback(shell.bash("echo 'RATE = 2' > src/pricing.py"))
    assert "src/pricing.py" in reason and "foreign.py" not in reason


def test_corrupt_session_state_fails_open(repo, env):
    shell = Shell(repo, env)
    assert shell.bash("ls") is None
    for path in Path(env["HARNESS_ROOT"]).rglob("*"):
        if path.is_file() and shell.session in str(path):
            path.write_text("{not json")
    shell.bash(HEREDOC)  # must not crash; the hook asserts exit 0
    assert shell.bash("ls") is None


def test_a_write_followed_by_a_failing_command_is_held(repo, env):
    """`cat > x.py ... && pytest` going red is the bypass itself: Claude reports a
    non-zero exit as PostToolUseFailure, and the plugin must be listening there."""
    hooks = json.loads((HOOK.parents[2] / "plugins" / "escapement-claude" / "hooks"
                        / "hooks.json").read_text())["hooks"]
    assert any(item["matcher"] == "Bash" and HOOK.name in hook["command"]
               for item in hooks.get("PostToolUseFailure", []) for hook in item["hooks"])
    shell = Shell(repo, env)
    assert "src/impl.py" in _feedback(shell.bash("echo 'IMPL = 1' > src/impl.py; false"))
    assert shell.bash("ls") is None


def _git_failing(tmp_path: Path, env: dict, subcommand: str) -> Path:
    """A `git` on PATH whose `subcommand` fails while the returned marker exists."""
    real = subprocess.run(["which", "git"], capture_output=True, text=True, check=True).stdout.strip()
    bin_dir, marker = tmp_path / f"fakebin-{subcommand}", tmp_path / f"git-{subcommand}-fails"
    bin_dir.mkdir()
    (bin_dir / "git").write_text(
        f'#!/bin/sh\nif [ "$1" = {subcommand} ] && [ -e "{marker}" ]; then exit 128; fi\n'
        f'exec "{real}" "$@"\n')
    (bin_dir / "git").chmod(0o755)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    return marker


def test_a_failed_snapshot_is_unknown_not_clean(repo, env, tmp_path):
    """git status failing before the call must not turn all existing dirt into
    this call's writes: the call is skipped, and the blindness is recorded."""
    (repo / "src" / "legacy.py").write_text("OLD = 1\n")
    marker = _git_failing(tmp_path, env, "status")
    marker.touch()
    shell = Shell(repo, env)
    assert shell.bash(f"rm {marker}") is None, "legacy.py is not this session's write"
    assert any(s.get("gate") == "shell_write_gate" and "unknown" in json.dumps(s)
               for s in signals(env)), signals(env)
    reason = _feedback(shell.bash("echo 'RATE = 2' > src/pricing.py"))
    assert "src/pricing.py" in reason and "legacy.py" not in reason


def test_no_repo_found_before_the_call_names_nothing_after(repo, env, tmp_path):
    """The before-half cannot find the repository (git rev-parse fails or times
    out): the after-half has nothing to compare with and stays silent."""
    (repo / "src" / "legacy.py").write_text("OLD = 1\n")
    marker = _git_failing(tmp_path, env, "rev-parse")
    shell = Shell(repo, env)
    assert shell.bash("ls") is None
    marker.touch()
    assert shell.bash(f"rm {marker} && echo 'X = 1' > src/x.py") is None
    reason = _feedback(shell.bash("echo 'RATE = 2' > src/pricing.py"))
    assert "src/pricing.py" in reason and "legacy.py" not in reason and "src/x.py" not in reason


def test_write_and_commit_in_one_call_is_held(repo, env):
    reason = _feedback(Shell(repo, env).bash(
        "echo 'RATE = 2' > src/pricing.py && git add src/pricing.py && "
        "git -c user.email=t@t -c user.name=t commit -qm pricing"))
    assert "src/pricing.py" in reason


def test_a_reset_does_not_blame_the_history_it_undoes(repo, env):
    """Someone else's commit, un-done by this session's reset, is not this session's write."""
    (repo / "src" / "app.py").write_text("VALUE = 5\n")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qam", "theirs")
    shell = Shell(repo, env)
    assert shell.bash("git reset -q --soft HEAD~1") is None
    assert shell.bash("ls") is None


def test_a_huge_dirty_tree_is_skipped_not_hashed(repo, env):
    """Past 2,000 dirty paths the hook stays silent rather than hash them all."""
    junk = repo / "junk"
    junk.mkdir()
    for index in range(2001):
        (junk / f"f{index}.txt").write_text("x")
    shell = Shell(repo, env)
    assert shell.bash("ls") is None
    assert shell.bash(HEREDOC) is None
    assert any(s.get("gate") == "shell_write_gate" and "too-many-dirty" in json.dumps(s)
               for s in signals(env)), "a blind gate must say so in telemetry"


def _upstream_commit(repo: Path, date: str | None = None) -> None:
    _git(repo, "checkout", "-q", "-b", "upstream")
    (repo / "src" / "app.py").write_text("VALUE = 6\n")
    extra = {"GIT_COMMITTER_DATE": date} if date else {}
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qam", "up"],
                   cwd=repo, check=True, capture_output=True, env={**os.environ, **extra})
    _git(repo, "checkout", "-q", "main")


def test_a_fast_forward_merge_is_not_this_sessions_write(repo, env):
    _upstream_commit(repo, "2020-01-01T00:00:00")
    assert Shell(repo, env).bash("git merge -q --ff-only upstream") is None


def test_a_pull_of_a_fresh_commit_is_not_this_sessions_write(repo, env):
    """A commit made moments ago elsewhere and pulled in: its date is no clue,
    the reflog says `pull`, so it is not named."""
    _upstream_commit(repo)
    shell = Shell(repo, env)
    assert shell.bash("git pull -q --ff-only . upstream") is None
    reason = _feedback(shell.bash(
        "echo 'RATE = 2' > src/pricing.py && git add src/pricing.py && "
        "git -c user.email=t@t -c user.name=t commit -qm pricing"))
    assert "src/pricing.py" in reason and "src/app.py" not in reason
