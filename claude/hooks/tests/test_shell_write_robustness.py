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
    assert snap.written(repo, before, after, []) == []


def test_a_repositorys_first_commit_is_seen(tmp_path, env):
    root = tmp_path / "fresh"
    (root / "src").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname = 'demo'\n")
    _git(root, "init", "-q", "-b", "main")
    reason = _feedback(Shell(root, env).bash(
        "echo 'VALUE = 1' > src/app.py && git add -A && "
        "git -c user.email=t@t -c user.name=t commit -qm first"))
    assert "src/app.py" in reason and "pyproject.toml" not in reason
