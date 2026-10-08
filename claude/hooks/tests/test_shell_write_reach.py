"""shell_write_gate reach: writes outside the cwd's own working tree, a real
Claude failure payload, big trees, and orphaned snapshots (escapement-chfw).

Wrong implementations these reject:
  - snapshotting only the cwd's repository: a session rooted at the main
    checkout that runs `sed -i` into a gitignored .worktrees/<name> checkout,
    or writes an absolute path in another repository, is never reported;
  - reading a duration key Claude does not send, or requiring the success
    payload's tool_response: a real PostToolUseFailure goes `no-duration` blind;
  - forcing `--untracked-files=all` on any tree, however large;
  - sweeping orphaned pending snapshots only inside the calling session, so a
    session's last orphans are kept forever.
"""

from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import _shell_snapshot as snap
from _shell_write_harness import HOOK, Shell, _feedback, _git, env, repo, signals  # noqa: F401

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "claude_bash_hook_payloads.json").read_text())


def _blind(env: dict, reason: str) -> bool:
    return any(s.get("gate") == "shell_write_gate" and s.get("decision") == "blind"
               and s.get("reason") == reason for s in signals(env))


# --- writes outside the cwd's working tree ----------------------------------


def _with_worktree(repo: Path) -> Path:
    """A gitignored .worktrees/feat checkout of `repo`, as Escapement makes them."""
    (repo / ".gitignore").write_text(".worktrees/\n")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "add", ".gitignore")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "ignore")
    _git(repo, "worktree", "add", "-q", ".worktrees/feat", "-b", "feat")
    return repo / ".worktrees" / "feat"


def test_root_session_sed_into_a_gitignored_worktree_is_reported(repo, env):
    _with_worktree(repo)
    reason = _feedback(Shell(repo, env).bash(
        "sed -i.bak 's/1/2/' .worktrees/feat/src/app.py && rm .worktrees/feat/src/app.py.bak"))
    assert "TDD" in reason and ".worktrees/feat/src/app.py" in reason


def test_root_session_docs_write_into_a_worktree_is_silent(repo, env):
    """Positive control: the other checkout's exempt file owes nothing."""
    _with_worktree(repo)
    assert Shell(repo, env).bash("echo more >> .worktrees/feat/docs/README.md") is None


def test_a_foreign_write_in_the_named_worktree_between_calls_is_not_blamed(repo, env):
    feat = _with_worktree(repo)
    shell = Shell(repo, env)
    assert shell.bash("ls .worktrees/feat") is None
    (feat / "src" / "app.py").write_text("VALUE = 'another session'\n")
    assert shell.bash("ls .worktrees/feat/src") is None


def test_an_absolute_write_into_another_repository_is_reported(repo, env, tmp_path):
    other = tmp_path / "other"
    (other / "src").mkdir(parents=True)
    (other / "pyproject.toml").write_text("[project]\nname = 'other'\n")
    (other / "src" / "x.py").write_text("X = 0\n")
    _git(other, "init", "-q", "-b", "main")
    _git(other, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    _git(other, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")
    reason = _feedback(Shell(repo, env).bash(f"echo 'X = 1' > {other}/src/x.py"))
    assert "src/x.py" in reason and str(other.resolve()) in reason


# --- a real Claude PostToolUseFailure payload --------------------------------


def _replay(name: str, **overrides) -> dict:
    payload = copy.deepcopy(FIXTURE["payloads"][name])
    payload.update(overrides)
    return payload


def _hook(payload: dict, env: dict) -> dict | None:
    proc = subprocess.run([sys.executable, "-B", str(HOOK)], input=json.dumps(payload),
                          capture_output=True, text=True, env=env, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def test_a_real_failure_payload_is_not_duration_blind(repo, env):
    """Replays the captured Claude 2.1.293 halves around the captured command."""
    command = FIXTURE["payloads"]["pre_tool_use_bash"]["tool_input"]["command"]
    common = {"session_id": f"s-{uuid.uuid4()}", "cwd": str(repo)}
    pre = _replay("pre_tool_use_bash", **common)
    assert _hook(pre, env) is None
    subprocess.run(["bash", "-c", command], cwd=repo)
    failure = _replay("post_tool_use_failure_bash", **common)
    assert failure["hook_event_name"] == "PostToolUseFailure" and "tool_response" not in failure
    output = _hook(failure, env)
    assert not _blind(env, "no-duration"), signals(env)
    assert "impl.py" in output["hookSpecificOutput"]["additionalContext"]


# --- big trees ---------------------------------------------------------------


def test_a_large_tree_is_not_scanned_with_all_untracked_files(repo, env, monkeypatch):
    """Past the index-size threshold, an untracked directory is reported as one
    entry; files inside it are not named, and the blindness is recorded."""
    monkeypatch.setattr(snap, "LARGE_INDEX", 1)
    monkeypatch.setenv("HARNESS_ROOT", env["HARNESS_ROOT"])
    monkeypatch.setenv("BEADS_DIR", env["BEADS_DIR"])
    before = snap.take(snap.Budget(), repo)
    (repo / "newpkg").mkdir()
    (repo / "newpkg" / "mod.py").write_text("M = 1\n")
    (repo / "src" / "app.py").write_text("VALUE = 2\n")
    after = snap.take(snap.Budget(), repo, before)
    assert after["untracked_dirs"] == ["newpkg/"]
    named, *_ = snap.written(snap.Budget(), repo, before, after, [])
    assert named == ["src/app.py"], "tracked changes are still seen in a large tree"


def test_a_small_tree_still_lists_every_untracked_file(repo):
    """Negative control: under the threshold, a new file in a new directory is named."""
    before = snap.take(snap.Budget(), repo)
    (repo / "newpkg").mkdir()
    (repo / "newpkg" / "mod.py").write_text("M = 1\n")
    after = snap.take(snap.Budget(), repo, before)
    assert not after.get("untracked_dirs")
    named, *_ = snap.written(snap.Budget(), repo, before, after, [])
    assert named == ["newpkg/mod.py"]


def test_the_gate_records_a_large_tree_blind(repo, env):
    """The gate path: a call that leaves a new untracked directory in a large
    tree records `untracked-dirs`, so the gap shows in telemetry."""
    env = dict(env, ESCAPEMENT_SHELL_WRITE_LARGE_INDEX="1")
    assert Shell(repo, env).bash("mkdir newpkg && echo 'M = 1' > newpkg/mod.py") is None
    assert _blind(env, "untracked-dirs")


# --- orphaned pending snapshots ----------------------------------------------


def test_orphaned_snapshots_of_other_sessions_are_swept(repo, env):
    threads = Path(env["HARNESS_ROOT"]) / "threads"
    stale = threads / "gone-session" / "shell_write_gate" / "pending-old.json"
    fresh = threads / "live-session" / "shell_write_gate" / "pending-new.json"
    for path in (stale, fresh):
        path.parent.mkdir(parents=True)
        path.write_text("{}")
    two_hours_ago = time.time() - 7200
    os.utime(stale, (two_hours_ago, two_hours_ago))
    Shell(repo, env).bash("ls")
    assert not stale.exists(), "a dead session's orphan must not be kept forever"
    assert fresh.exists(), "a live session's pending snapshot must survive"


# --- concurrent writers -------------------------------------------------------


def test_the_report_says_another_session_may_have_written(repo, env):
    reason = _feedback(Shell(repo, env).bash("echo 'X = 1' >> src/app.py"))
    assert "another session" in reason
