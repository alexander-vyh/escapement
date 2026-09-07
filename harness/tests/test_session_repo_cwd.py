"""Oracle for session_repo_cwd() repository resolution.

Regression guard for escapement-bu6a: the waker refused every scheduled spawn
from an ordinary interactive session because session_repo_cwd() read only
session_mode.json (mode == "task"). Interactive sessions write checkout.json
instead, so repo_cwd resolved None and wakeup_waker.py printed
"scheduled spawn lacks trusted repository context" — 24,501 consecutive times,
stranding real wakeups from 2026-09-02, -03 and -05.

The positive case below fails before the fix. The negative controls exist so the
fix cannot be "return any path we can find": an unresolvable, untrusted,
mismatched or non-existent binding must still refuse.
"""

import importlib.util
import json
import pathlib
import sys

BIN = pathlib.Path(__file__).resolve().parent.parent / "bin"
sys.path.insert(0, str(BIN))


def _load():
    spec = importlib.util.spec_from_file_location(
        "task_session_mode", BIN / "task_session_mode.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load harness/bin/task_session_mode.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


tsm = _load()

SID = "e49d4034-b512-4e66-9c8b-d6d02fccc99e"


def _checkout(thread_dir, repo, session_id=SID, **kw):
    payload = {
        "session_id": session_id,
        "worktree_root": str(repo),
        "git_common_dir": str(repo / ".git"),
        "is_linked_worktree": False,
        "heartbeat": "2026-09-05T07:08:48.841527+00:00",
    }
    payload.update(kw)
    (thread_dir / "checkout.json").write_text(json.dumps(payload))


def _task_mode(thread_dir, repo, session_id=SID):
    (thread_dir / "session_mode.json").write_text(
        json.dumps({"mode": "task", "repo_cwd": str(repo), "session_id": session_id})
    )


# --- positive: the bug ----------------------------------------------------


def test_interactive_session_resolves_repo_from_checkout(tmp_path):
    """An ordinary interactive session has checkout.json and no session_mode.json."""
    thread = tmp_path / "thread"
    thread.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    _checkout(thread, repo)

    assert tsm.session_repo_cwd(thread, SID) == repo.resolve()


def test_task_mode_binding_still_wins(tmp_path):
    """Pre-existing task-mode resolution is unchanged and takes precedence."""
    thread = tmp_path / "thread"
    thread.mkdir()
    task_repo = tmp_path / "task_repo"
    task_repo.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    _task_mode(thread, task_repo)
    _checkout(thread, other)

    assert tsm.session_repo_cwd(thread, SID) == task_repo.resolve()


# --- negative controls: each must still refuse ----------------------------


def test_no_binding_at_all_refuses(tmp_path):
    thread = tmp_path / "thread"
    thread.mkdir()
    assert tsm.session_repo_cwd(thread, SID) is None


def test_checkout_for_a_different_session_refuses(tmp_path):
    thread = tmp_path / "thread"
    thread.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    _checkout(thread, repo, session_id="00000000-0000-0000-0000-000000000000")
    assert tsm.session_repo_cwd(thread, SID) is None


def test_checkout_naming_a_missing_directory_refuses(tmp_path):
    thread = tmp_path / "thread"
    thread.mkdir()
    _checkout(thread, tmp_path / "does_not_exist")
    assert tsm.session_repo_cwd(thread, SID) is None


def test_relative_worktree_root_refuses(tmp_path):
    thread = tmp_path / "thread"
    thread.mkdir()
    (thread / "checkout.json").write_text(
        json.dumps({"session_id": SID, "worktree_root": "relative/path"})
    )
    assert tsm.session_repo_cwd(thread, SID) is None


def test_symlinked_checkout_refuses(tmp_path):
    """Untrusted (symlinked) state must not bind a repository."""
    thread = tmp_path / "thread"
    thread.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    real = tmp_path / "real_checkout.json"
    real.write_text(json.dumps({"session_id": SID, "worktree_root": str(repo)}))
    (thread / "checkout.json").symlink_to(real)
    assert tsm.session_repo_cwd(thread, SID) is None


def test_malformed_checkout_refuses(tmp_path):
    thread = tmp_path / "thread"
    thread.mkdir()
    (thread / "checkout.json").write_text("{not json")
    assert tsm.session_repo_cwd(thread, SID) is None


def test_task_mode_with_unusable_repo_does_not_fall_back(tmp_path):
    """A declared task binding that is broken must refuse, not silently widen.

    Falling through to checkout.json here would spawn delegated work in the
    interactive repository instead of the narrower one task mode named.
    """
    thread = tmp_path / "thread"
    thread.mkdir()
    interactive = tmp_path / "interactive"
    interactive.mkdir()
    _task_mode(thread, tmp_path / "task_repo_deleted")
    _checkout(thread, interactive)

    assert tsm.session_repo_cwd(thread, SID) is None
