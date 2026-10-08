"""shell_write_gate follow-ups from the #271 delta review (escapement-chfw).

Wrong implementations these reject:
  - a committed file the call changed, skipped because the time budget ran
    out, vanishing without a word: it must be reported as blind `out-of-time`;
  - re-hashing a committed file with no time left (the budget check removed):
    it would be named from a hash the budget never paid for;
  - a before-half that finds no repository, or goes blind, leaving an older
    snapshot filed under the same call id for the after-half to compare with.
"""

from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path

import _shell_snapshot as snap
from _shell_write_harness import Shell, _git, env, repo, signals  # noqa: F401
from test_shell_write_attribution import _git_failing


_RealBudget = snap.Budget


class SpentAfterGit(_RealBudget):
    """Git still answers; the time for hashing is gone."""

    def git(self, cwd, *args):
        return _RealBudget().git(cwd, *args)

    def left(self) -> float:
        return 0.0


COMMIT_THEIRS = ("echo 'THEIRS = 3' > src/theirs.py && "
                 "git -c user.email=t@t -c user.name=t commit -qam mine")


def _theirs_dirty(repo: Path) -> None:
    """src/theirs.py tracked, and dirty before the call."""
    (repo / "src" / "theirs.py").write_text("THEIRS = 1\n")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "theirs")
    (repo / "src" / "theirs.py").write_text("THEIRS = 2\n")


def _blind(env: dict, reason: str) -> bool:
    return any(s.get("gate") == "shell_write_gate" and s.get("decision") == "blind"
               and s.get("reason") == reason for s in signals(env))


def test_a_committed_file_skipped_for_time_is_reported_not_named(repo):
    _theirs_dirty(repo)
    before = snap.take(snap.Budget(), repo)
    subprocess.run(["bash", "-c", COMMIT_THEIRS], cwd=repo, check=True)  # the call
    after = snap.take(snap.Budget(), repo, before)
    committed = snap.commits_during(snap.Budget(), repo, before["head"], after["head"])
    assert committed == ["src/theirs.py"]

    names, unproven, out_of_time = snap.written(SpentAfterGit(), repo, before, after, committed)
    assert names == [], "no time to re-hash it: it cannot be named"
    assert out_of_time == ["src/theirs.py"], "and it must not vanish silently"
    assert unproven == []
    # With time, the same comparison names it: the skip above was the budget's doing.
    assert snap.written(snap.Budget(), repo, before, after, committed)[0] == ["src/theirs.py"]


def _gate_call(repo: Path, env: dict, monkeypatch, command: str, *, spent: bool) -> str | None:
    """One Bash call through the gate in-process; `spent` leaves the after-half
    no time to hash (git still answers)."""
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.syspath_prepend(str(Path(snap.__file__).parent))
    import shell_write_gate as gate

    payload = {"session_id": "s-out-of-time", "tool_use_id": f"toolu_{uuid.uuid4().hex}",
               "cwd": str(repo), "tool_name": "Bash", "tool_input": {"command": command}}
    assert gate.run({**payload, "hook_event_name": "PreToolUse"}) is None
    subprocess.run(["bash", "-c", command], cwd=repo, check=True)
    if spent:
        monkeypatch.setattr(gate.snap, "Budget", SpentAfterGit)
    return gate.run({**payload, "hook_event_name": "PostToolUse", "duration_ms": 50})


def test_the_gate_records_out_of_time_for_it(repo, env, monkeypatch):
    _theirs_dirty(repo)
    assert _gate_call(repo, env, monkeypatch, COMMIT_THEIRS, spent=True) is None
    assert _blind(env, "out-of-time")


def test_with_time_left_no_out_of_time_is_recorded(repo, env, monkeypatch):
    """Negative control: the same committed change, with time to check it, is
    named and records no out-of-time blindness."""
    _theirs_dirty(repo)
    report = _gate_call(repo, env, monkeypatch, COMMIT_THEIRS, spent=False)
    assert report is not None and "src/theirs.py" in report
    assert not _blind(env, "out-of-time")


CHANGE_THEIRS = "echo 'THEIRS = 3' > src/theirs.py"


def test_an_uncommitted_file_left_unhashed_is_reported_not_named(repo, env, monkeypatch):
    """A pre-dirty file this call changed, left unhashed after the call because
    time ran out: it cannot be named, and it must not vanish silently."""
    _theirs_dirty(repo)
    assert _gate_call(repo, env, monkeypatch, CHANGE_THEIRS, spent=True) is None
    assert _blind(env, "out-of-time")


def test_an_uncommitted_change_with_time_left_is_named_without_blindness(repo, env, monkeypatch):
    _theirs_dirty(repo)
    report = _gate_call(repo, env, monkeypatch, CHANGE_THEIRS, spent=False)
    assert report is not None and "src/theirs.py" in report
    assert not _blind(env, "out-of-time")


def _pending_then(repo: Path, env: dict, second_pre) -> dict | None:
    """Pre for one call id in the repo, then `second_pre` re-runs Pre for the
    same id, then another session writes, then that id's Post."""
    shell = Shell(repo, env)
    shell.call = "toolu_same"
    assert shell._hook("PreToolUse", "ls") is None
    second_pre(shell)
    (repo / "src" / "foreign.py").write_text("THEIRS = 1\n")
    shell.duration_ms = 5000  # wide enough that the window is never the reason for silence
    return shell._hook("PostToolUse", "ls")


def test_a_pre_half_finding_no_repo_drops_an_older_pending_snapshot(repo, env, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()

    def outside_any_repo(shell: Shell) -> None:
        shell.repo, inside = plain, shell.repo
        assert shell._hook("PreToolUse", "ls") is None
        shell.repo = inside

    assert _pending_then(repo, env, outside_any_repo) is None


def test_a_blind_pre_half_drops_an_older_pending_snapshot(repo, env, tmp_path):
    marker = _git_failing(tmp_path, env, "status")

    def status_fails(shell: Shell) -> None:
        marker.touch()
        assert shell._hook("PreToolUse", "ls") is None
        marker.unlink()

    assert _pending_then(repo, env, status_fails) is None
    assert _blind(env, "unknown")


def test_positive_control_the_pending_snapshot_is_used_when_nothing_drops_it(repo, env):
    """Without a second before-half, the same sequence does name the foreign write:
    the two tests above are silent because the snapshot was dropped, not by accident."""
    output = _pending_then(repo, env, lambda shell: None)
    assert output is not None and "foreign.py" in json.dumps(output)


def test_a_never_readable_file_is_not_out_of_time(repo, env):
    """A dirty dangling symlink and a permission-denied file are unreadable before
    and after every call. That is not the budget running out: no `out-of-time`,
    at most one `unreadable` signal per call, and never named."""
    (repo / "src" / "gone.py").symlink_to(repo / "src" / "nowhere.py")
    locked = repo / "src" / "locked.py"
    locked.write_text("SECRET = 1\n")
    locked.chmod(0o000)
    try:
        shell = Shell(repo, env)
        assert shell.bash("ls") is None
        assert shell.bash("echo more >> docs/README.md") is None
    finally:
        locked.chmod(0o644)
    blind = [s.get("reason") for s in signals(env)
             if s.get("gate") == "shell_write_gate" and s.get("decision") == "blind"]
    assert "out-of-time" not in blind, blind
    assert blind.count("unreadable") <= 2, blind
