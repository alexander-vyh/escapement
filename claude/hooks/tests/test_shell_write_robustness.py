"""shell_write_gate under real-world conditions: odd call ids, concurrent git,
permission prompts, hash budgets, a repository's first commit.

Wrong implementations these reject: a call-id filter that turns the gate off
for a provider's id shape without a word; a `git status` that takes the index
lock and fails another session's `git add`; blaming writes made while a
permission prompt waited; a hash-or-stat choice remade after the call, which
makes an untouched file look changed; a first commit nobody sees.
"""

from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path

import _shell_snapshot as snap
from _shell_write_harness import HEREDOC, Shell, _feedback, _git, env, repo, signals  # noqa: F401


def _blind(env: dict, reason: str) -> bool:
    return any(s.get("gate") == "shell_write_gate" and s.get("decision") == "blind"
               and s.get("reason") == reason for s in signals(env))


def test_an_openai_responses_call_id_is_paired(repo, env):
    """Pi's openai-codex provider names calls `call_…|fc_…`."""
    ids = iter(f"call_{n}x|fc_{n}y" for n in range(100))
    shell = Shell(repo, env, call_id=lambda: next(ids))
    assert "src/app.py" in _feedback(shell.bash(HEREDOC))


def test_a_call_with_no_id_is_blind_and_says_so(repo, env):
    shell = Shell(repo, env, call_id=lambda: "")
    assert shell.bash(HEREDOC) is None
    assert _blind(env, "no-call-id")


def test_the_snapshot_does_not_take_the_index_lock(repo, tmp_path):
    """Another session's `git add` must not fail because this hook ran `git status`."""
    stop = threading.Event()

    def snapshots() -> None:
        root = Path(repo)
        while not stop.is_set():
            snap.take(snap.Budget(), root)

    worker = threading.Thread(target=snapshots)
    worker.start()
    failures = []
    try:
        for index in range(150):
            (repo / "src" / "busy.py").write_text(f"N = {index}\n")
            (repo / "src" / "app.py").write_text(f"VALUE = {index}\n")
            result = subprocess.run(["git", "add", "-A"], cwd=repo, capture_output=True, text=True)
            if result.returncode != 0:
                failures.append(result.stderr.strip())
    finally:
        stop.set()
        worker.join()
    assert failures == [], failures[:3]


def test_writes_made_while_a_permission_prompt_waits_are_not_blamed(repo, env):
    shell = Shell(repo, env)

    def another_session_writes_meanwhile() -> None:
        (repo / "src" / "theirs.py").write_text("THEIRS = 1\n")
        time.sleep(3)

    assert shell.bash("echo 'RATE = 2' > src/pricing.py",
                      while_prompting=another_session_writes_meanwhile) is None
    assert _blind(env, "prompt-wait")
    reason = _feedback(shell.bash("echo 'RATE = 3' > src/pricing.py"))
    assert "src/pricing.py" in reason and "theirs.py" not in reason


def test_the_hash_or_stat_choice_is_made_before_the_call(repo, monkeypatch):
    """With the hash budget spent on a.py, b.py is fingerprinted by stat. If the
    call then reverts a.py, b.py must not be re-decided as hashed after the call
    and so look changed."""
    (repo / "src" / "a.py").write_text("A = 1\n" * 20)
    (repo / "src" / "b.py").write_text("B = 1\n" * 20)
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "ab")
    (repo / "src" / "a.py").write_text("A = 2\n" * 20)
    (repo / "src" / "b.py").write_text("B = 2\n" * 20)
    monkeypatch.setattr(snap, "HASH_BUDGET", 150)
    before = snap.take(snap.Budget(), repo)
    assert before["files"]["src/b.py"].startswith("stat:")
    _git(repo, "checkout", "--", "src/a.py")  # the call
    after = snap.take(snap.Budget(), repo, before)
    assert snap.written(snap.Budget(), repo, before, after, []) == ([], [])


def test_a_repositorys_first_commit_is_seen(tmp_path, env):
    root = tmp_path / "fresh"
    (root / "src").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname = 'demo'\n")
    _git(root, "init", "-q", "-b", "main")
    reason = _feedback(Shell(root, env).bash(
        "echo 'VALUE = 1' > src/app.py && git add -A && "
        "git -c user.email=t@t -c user.name=t commit -qm first"))
    assert "src/app.py" in reason and "pyproject.toml" not in reason


def _slow_head_lookup(tmp_path: Path, env: dict, seconds: float) -> None:
    """A `git` whose `rev-parse --verify` (the HEAD lookup, after `git status`) is slow."""
    real = subprocess.run(["which", "git"], capture_output=True, text=True, check=True).stdout.strip()
    bin_dir = tmp_path / "slowbin"
    bin_dir.mkdir()
    (bin_dir / "git").write_text(
        '#!/bin/sh\ncase " $* " in *" rev-parse --verify "*) sleep ' + str(seconds) + ';; esac\n'
        f'exec "{real}" "$@"\n')
    (bin_dir / "git").chmod(0o755)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"


def test_a_foreign_write_during_a_slow_pre_half_and_a_prompt_is_not_blamed(repo, env, tmp_path):
    """The before-half takes ~2s after its `git status`; another session writes
    1s in, then a 1.5s permission prompt. Measured from the end of the
    before-half the window looks like the command alone; from its start it does not."""
    _slow_head_lookup(tmp_path, env, 2)
    writer = threading.Timer(1.0, lambda: (repo / "src" / "theirs.py").write_text("THEIRS = 1\n"))
    writer.start()
    try:
        assert Shell(repo, env).bash("ls", while_prompting=lambda: time.sleep(1.5)) is None
    finally:
        writer.join()
    assert _blind(env, "prompt-wait")


def test_claude_without_a_duration_is_blind(repo, env):
    """Claude always sends duration_ms after a call; without it the prompt check
    cannot be made, so the call names nothing rather than risk the prompt's writes."""
    shell = Shell(repo, env)
    shell.send_duration = False
    assert shell.bash(HEREDOC) is None
    assert _blind(env, "no-duration")


def test_commit_all_does_not_name_a_foreign_file_it_swept_in(repo, env):
    (repo / "src" / "theirs.py").write_text("THEIRS = 1\n")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "theirs")
    (repo / "src" / "theirs.py").write_text("THEIRS = 2\n")  # another session's edit, uncommitted
    reason = _feedback(Shell(repo, env).bash(
        "echo 'RATE = 2' > src/pricing.py && git add src/pricing.py && "
        "git -c user.email=t@t -c user.name=t commit -qam both"))
    assert "src/pricing.py" in reason
    assert "theirs.py" not in reason, "committed exactly as it was before the call"


def test_a_hashed_file_left_unhashed_when_time_runs_out_is_not_named(repo):
    (repo / "src" / "app.py").write_text("VALUE = 3\n")
    before = snap.take(snap.Budget(), repo)
    assert not before["files"]["src/app.py"].startswith("stat:")

    class SpentAfterGit(snap.Budget):
        """Git still answers; the time for hashing is gone."""

        def git(self, cwd, *args):
            return snap.Budget().git(cwd, *args)

        def left(self) -> float:
            return 0.0

    after = snap.take(SpentAfterGit(), repo, before)
    assert snap.written(snap.Budget(), repo, before, after, []) == ([], [])


def test_a_worktree_rename_is_parsed_as_one_path(repo):
    """` R new\\0old\\0` (an intent-to-add rename): the source is not a second entry."""
    (repo / "xx" / "src").mkdir(parents=True)
    (repo / "xx" / "src" / "app.py").write_text("MOVED = 1\n")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "xx")
    (repo / "xx" / "src" / "app.py").rename(repo / "src" / "moved.py")
    _git(repo, "add", "-N", "src/moved.py")
    assert set(snap.take(snap.Budget(), repo)["files"]) == {"src/moved.py"}


def test_an_mtime_only_change_on_a_large_file_is_not_named(repo, env):
    """Past 1MB a file is fingerprinted by size and mtime. A new mtime alone does
    not prove its content changed: silent, and the blindness is recorded. A new
    size does prove it, so that is still named."""
    (repo / "src" / "big.py").write_text("# pad\n" * 200_000)  # ~1.2MB, another session's
    shell = Shell(repo, env)
    assert shell.bash("sleep 0.01 && touch src/big.py") is None
    assert _blind(env, "stat-only")
    assert "src/big.py" in _feedback(shell.bash("echo 'X = 1' >> src/big.py"))
