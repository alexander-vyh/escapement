"""Tests for wakeup_waker.plan() — due-selection, prune-after-fire, cheap reschedule.

The prune-after-fire assertions are the direct regression guard for the observed
25× resume / 45× block storms: a one-shot wake must NOT survive in the schedule to
re-fire; only a not-ready poll is re-armed.
"""

import datetime as dt
import fcntl
import importlib.util
import json
import pathlib
import shlex
import sys

BIN = pathlib.Path(__file__).resolve().parent.parent / "bin"
sys.path.insert(0, str(BIN))


def _load_wakeup_waker():
    spec = importlib.util.spec_from_file_location(
        "wakeup_waker", BIN / "wakeup_waker.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load harness/bin/wakeup_waker.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ww = _load_wakeup_waker()


NOW = dt.datetime(2026, 6, 4, 9, 0, 0, tzinfo=dt.timezone.utc)
PAST = (NOW - dt.timedelta(minutes=1)).isoformat()
FUTURE = (NOW + dt.timedelta(hours=1)).isoformat()
CLI_PAST = "2000-01-01T00:00:00+00:00"
CLI_FUTURE = "2999-01-01T00:00:00+00:00"


def _entry(**kw):
    base = {
        "wake_at": PAST,
        "prompt": "p",
        "thread_id": "T",
        "created_by": "x",
        "crash_count": 0,
    }
    base.update(kw)
    return base


def _runner(code):
    return lambda command: (code, "")


def _write_session_repo_context(thread_dir: pathlib.Path, session_id: str) -> None:
    (thread_dir / "session_mode.json").write_text(
        json.dumps(
            {
                "mode": "task",
                "repo_cwd": str(thread_dir),
                "task_id": "escapement-test-child",
                "parent_id": "escapement-test-parent",
                "session_id": session_id,
            }
        )
    )


# --- due-selection --------------------------------------------------------


def test_not_due_entry_untouched_no_spawn():
    e = _entry(wake_at=FUTURE, kind="check", command="x")
    kept, spawns = ww.plan([e], NOW, run_cmd=_runner(0))
    assert kept == [e] and spawns == []  # future entry never dispatched


# --- the GCP-wait core: not ready → cheap reschedule, NO spawn ------------


def test_not_ready_poll_rearmed_no_claude():
    e = _entry(kind="check", command="poll", poll_interval=600)
    kept, spawns = ww.plan([e], NOW, run_cmd=_runner(1))  # non-zero = not ready
    assert spawns == []  # NO Claude spawned (the whole point)
    assert len(kept) == 1  # re-armed, not dropped
    assert kept[0]["wake_at"] == (NOW + dt.timedelta(seconds=600)).isoformat()


# --- ready → fresh cheap handoff, AND pruned (no re-fire) -----------------


def test_ready_poll_spawns_handoff_and_prunes():
    e = _entry(
        kind="check", command="poll", escalate_prompt="PR #5 merged — finish up."
    )
    kept, spawns = ww.plan([e], NOW, run_cmd=_runner(0))  # exit 0 = ready
    assert kept == []  # PRUNED — cannot re-fire
    assert len(spawns) == 1
    assert spawns[0]["type"] == "handoff"
    assert spawns[0]["model"] == ww.wd.DEFAULT_HANDOFF_MODEL
    assert spawns[0]["prompt"] == "PR #5 merged — finish up."


def test_resume_kind_spawns_resume_and_prunes():
    # one-shot resume fires once then is pruned (regression guard for the 25× storm).
    e = _entry(kind="resume", prompt="continue")
    kept, spawns = ww.plan([e], NOW, run_cmd=_runner(0))
    assert kept == []
    assert spawns[0]["type"] == "resume" and spawns[0]["prompt"] == "continue"


def test_past_deadline_escalates_once_and_prunes():
    e = _entry(kind="check", command="poll", deadline=PAST, escalate_prompt="look")
    kept, spawns = ww.plan([e], NOW, run_cmd=_runner(1))  # not ready, but past deadline
    assert kept == []
    assert len(spawns) == 1 and spawns[0]["type"] == "handoff"


# --- fail-safe ------------------------------------------------------------


def test_malformed_and_bad_wake_at_dropped_no_spawn():
    kept, spawns = ww.plan(
        ["not-a-dict", {"wake_at": "garbage", "kind": "check", "command": "x"}],
        NOW,
        run_cmd=_runner(0),
    )
    assert kept == [] and spawns == []


def test_empty_schedule():
    assert ww.plan([], NOW, run_cmd=_runner(0)) == ([], [])


def test_capability_probe_names_cross_host_continuation(capsys):
    assert ww.main(["--capabilities"]) == 0
    assert capsys.readouterr().out.strip() == "cross-host-continuation-v1"


def test_fire_runs_continuation_watchdog_even_without_schedules(tmp_path, monkeypatch):
    root = tmp_path / "threads"
    root.mkdir()
    calls = []
    monkeypatch.setattr(ww, "HARNESS_ROOT", tmp_path)
    monkeypatch.setattr(ww.wls, "reconcile", lambda _root: calls.append("reconcile"))
    monkeypatch.setattr(
        ww.continuation_watchdog, "run_once",
        lambda state_root: calls.append(("watchdog", state_root)) or {"launched": 0},
    )
    monkeypatch.setattr(
        ww.subprocess,
        "Popen",
        lambda argv, **kwargs: calls.append(("legacy", argv, kwargs)),
    )
    assert ww.main(["--threads-root", str(root), "--fire"]) == 0
    assert calls[0] == ("watchdog", tmp_path / "watchdog")
    assert calls[1][0] == "legacy"
    assert "--legacy-fire" in calls[1][1]
    assert calls[1][2]["start_new_session"] is True
    assert "reconcile" not in calls


def test_watchdog_failure_is_visible_without_skipping_legacy_launch(tmp_path, monkeypatch):
    root = tmp_path / "threads"
    root.mkdir()
    calls = []
    monkeypatch.setattr(ww, "HARNESS_ROOT", tmp_path)
    monkeypatch.setattr(
        ww.continuation_watchdog, "run_once",
        lambda _root: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(
        ww.subprocess, "Popen", lambda argv, **_kwargs: calls.append(argv)
    )
    assert ww.main(["--threads-root", str(root), "--fire"]) == 1
    assert len(calls) == 1
    assert "--legacy-fire" in calls[0]


def test_legacy_fire_runs_reconciliation_without_watchdog(tmp_path, monkeypatch):
    root = tmp_path / "threads"
    root.mkdir()
    reconciled = []
    monkeypatch.setattr(ww, "HARNESS_ROOT", tmp_path)
    monkeypatch.setattr(ww.wls, "reconcile", lambda value: reconciled.append(value))
    monkeypatch.setattr(
        ww.continuation_watchdog,
        "run_once",
        lambda _root: (_ for _ in ()).throw(AssertionError("watchdog reran")),
    )

    assert ww.main(["--threads-root", str(root), "--legacy-fire"]) == 0
    assert reconciled == [tmp_path]


# --- dry-run contract -----------------------------------------------------


def test_dry_run_does_not_execute_due_check_commands(tmp_path):
    root = tmp_path / "threads"
    thread_dir = root / "thread-1"
    thread_dir.mkdir(parents=True)
    schedule = thread_dir / "scheduled.json"
    sentinel = tmp_path / "check-ran"
    script = f"from pathlib import Path; Path({str(sentinel)!r}).write_text('ran')"
    entry = _entry(
        kind="check",
        wake_at=CLI_PAST,
        command=f"{sys.executable} -c {shlex.quote(script)}",
        escalate_prompt="condition met",
    )
    schedule.write_text(json.dumps([entry]))

    assert ww.main(["--threads-root", str(root)]) == 0

    assert not sentinel.exists()
    assert json.loads(schedule.read_text()) == [entry]


def test_dry_run_still_reports_due_resume_without_rewriting_schedule(
    tmp_path, capsys, monkeypatch
):
    root = tmp_path / "threads"
    thread_dir = root / "thread-1"
    thread_dir.mkdir(parents=True)
    schedule = thread_dir / "scheduled.json"
    entry = _entry(kind="resume", wake_at=CLI_PAST, prompt="continue")
    schedule.write_text(json.dumps([entry]))

    def fail_if_spawned(argv, cwd=None):
        raise AssertionError(f"dry-run spawned unexpectedly: {argv} in {cwd}")

    monkeypatch.setattr(ww.subprocess, "Popen", fail_if_spawned)

    assert ww.main(["--threads-root", str(root)]) == 0

    assert json.loads(schedule.read_text()) == [entry]
    out = capsys.readouterr().out
    assert '"would_spawn"' in out
    assert "DRY-RUN: 1 spawn(s) planned" in out


def test_dry_run_respects_future_resume_wake_at(tmp_path, capsys):
    root = tmp_path / "threads"
    thread_dir = root / "thread-1"
    thread_dir.mkdir(parents=True)
    schedule = thread_dir / "scheduled.json"
    entry = _entry(kind="resume", wake_at=CLI_FUTURE, prompt="continue later")
    schedule.write_text(json.dumps([entry]))

    assert ww.main(["--threads-root", str(root)]) == 0

    assert json.loads(schedule.read_text()) == [entry]
    out = capsys.readouterr().out
    assert '"would_spawn"' not in out
    assert "DRY-RUN: 0 spawn(s) planned" in out


def test_fire_executes_due_check_and_rearms_when_not_ready(tmp_path, capsys):
    root = tmp_path / "threads"
    thread_dir = root / "thread-1"
    thread_dir.mkdir(parents=True)
    schedule = thread_dir / "scheduled.json"
    sentinel = tmp_path / "check-ran"
    script = (
        f"from pathlib import Path; Path({str(sentinel)!r}).write_text('ran'); "
        "raise SystemExit(1)"
    )
    entry = _entry(
        kind="check",
        wake_at=CLI_PAST,
        command=f"{sys.executable} -c {shlex.quote(script)}",
        escalate_prompt="condition met",
        poll_interval=600,
    )
    schedule.write_text(json.dumps([entry]))

    assert ww.main(["--threads-root", str(root), "--fire"]) == 0

    assert sentinel.read_text() == "ran"
    kept = json.loads(schedule.read_text())
    assert len(kept) == 1
    assert kept[0]["command"] == entry["command"]
    assert kept[0]["wake_at"] != CLI_PAST
    assert "FIRED: 0 spawn(s) planned" in capsys.readouterr().out


def test_fire_preserves_due_entry_when_spawn_fails(tmp_path, monkeypatch):
    root = tmp_path / "threads"
    thread_dir = root / "thread-1"
    thread_dir.mkdir(parents=True)
    schedule = thread_dir / "scheduled.json"
    entry = _entry(kind="resume", wake_at=CLI_PAST, prompt="continue")
    schedule.write_text(json.dumps([entry]))
    _write_session_repo_context(thread_dir, "thread-1")

    def fail_spawn(argv, _cwd):
        raise OSError("claude unavailable")

    monkeypatch.setattr(ww.subprocess, "Popen", fail_spawn)

    assert ww.main(["--threads-root", str(root), "--fire"]) == 1

    assert json.loads(schedule.read_text()) == [entry]


def test_fire_skips_untrusted_schedule_and_does_not_execute_command(tmp_path, capsys):
    # Security guard: a world-writable scheduled.json could have its `command`
    # rewritten by another local user; the waker must NOT shell-execute it.
    # Negative control for trusted_source — an existence-only check would fail this.
    import os

    if not hasattr(os, "geteuid"):
        import pytest

        pytest.skip("perms/ownership guard is POSIX-only")
    root = tmp_path / "threads"
    thread_dir = root / "thread-1"
    thread_dir.mkdir(parents=True)
    schedule = thread_dir / "scheduled.json"
    sentinel = tmp_path / "untrusted-check-ran"
    script = f"from pathlib import Path; Path({str(sentinel)!r}).write_text('ran')"
    entry = _entry(
        kind="check",
        wake_at=CLI_PAST,
        command=f"{sys.executable} -c {shlex.quote(script)}",
        escalate_prompt="condition met",
    )
    schedule.write_text(json.dumps([entry]))
    schedule.chmod(0o666)  # group + other writable -> untrusted

    assert ww.main(["--threads-root", str(root), "--fire"]) == 1

    assert not sentinel.exists()  # the command must NOT have run
    assert json.loads(schedule.read_text()) == [entry]  # schedule left untouched
    assert "untrusted" in capsys.readouterr().err.lower()


def test_fire_skips_locked_schedule_to_avoid_duplicate_wakers(
    tmp_path, monkeypatch, capsys
):
    root = tmp_path / "threads"
    thread_dir = root / "thread-1"
    thread_dir.mkdir(parents=True)
    schedule = thread_dir / "scheduled.json"
    entry = _entry(kind="resume", wake_at=CLI_PAST, prompt="continue")
    schedule.write_text(json.dumps([entry]))
    lock_path = schedule.with_suffix(".json.lock")

    def fail_if_spawned(argv, cwd=None):
        raise AssertionError(f"locked schedule spawned unexpectedly: {argv} in {cwd}")

    monkeypatch.setattr(ww.subprocess, "Popen", fail_if_spawned)
    with lock_path.open("w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert ww.main(["--threads-root", str(root), "--fire"]) == 1

    assert json.loads(schedule.read_text()) == [entry]
    assert "skipped locked schedule" in capsys.readouterr().err


# --- public --fire supervisor boundary -----------------------------------


def _write_interactive_checkout(thread_dir: pathlib.Path, session_id: str) -> None:
    """What an ordinary (non-task-mode) session actually writes."""
    (thread_dir / "checkout.json").write_text(
        json.dumps(
            {
                "session_id": session_id,
                "worktree_root": str(thread_dir),
                "git_common_dir": str(thread_dir / ".git"),
                "is_linked_worktree": False,
            }
        )
    )


def test_interactive_session_wakeup_is_not_refused(tmp_path, monkeypatch, capsys):
    """escapement-bu6a: a wakeup armed outside task mode must actually spawn.

    Before the checkout.json fallback this printed "scheduled spawn lacks
    trusted repository context" and dropped the spawn - 24,501 times in one week,
    stranding real wakeups from 2026-09-02, -03 and -05.
    """
    root = tmp_path / "threads"
    thread_dir = root / "thread-1"
    thread_dir.mkdir(parents=True)
    schedule = thread_dir / "scheduled.json"
    entry = _entry(kind="resume", wake_at=CLI_PAST, prompt="continue", thread_id="thread-1")
    schedule.write_text(json.dumps([entry]))
    _write_interactive_checkout(thread_dir, "thread-1")

    spawned = []

    def capture(argv, cwd):
        spawned.append((argv, cwd))

    monkeypatch.setattr(ww.subprocess, "Popen", capture)

    assert ww.main(["--threads-root", str(root), "--fire"]) == 0

    captured = capsys.readouterr()
    assert "lacks trusted repository context" not in captured.err
    assert len(spawned) == 1  # the wakeup actually fired
    assert spawned[0][1] == thread_dir.resolve()  # in the repo checkout.json named
    assert json.loads(schedule.read_text()) == []  # one-shot pruned, no re-fire storm


def test_thread_without_any_repo_binding_is_still_refused(tmp_path, monkeypatch, capsys):
    """Negative control: no trusted binding must still refuse to spawn."""
    root = tmp_path / "threads"
    thread_dir = root / "thread-1"
    thread_dir.mkdir(parents=True)
    entry = _entry(kind="resume", wake_at=CLI_PAST, prompt="continue", thread_id="thread-1")
    schedule = thread_dir / "scheduled.json"
    schedule.write_text(json.dumps([entry]))

    spawned = []
    monkeypatch.setattr(ww.subprocess, "Popen", lambda argv, cwd: spawned.append(argv))

    assert ww.main(["--threads-root", str(root), "--fire"]) == 1
    assert "lacks trusted repository context" in capsys.readouterr().err
    assert spawned == []  # nothing launched
    assert json.loads(schedule.read_text()) == [entry]  # entry preserved, not lost


# --- escapement-4qta: schedule work must not queue behind reconciliation ----


def _due_resume(thread_dir: pathlib.Path, session_id: str) -> pathlib.Path:
    """A thread with an interactive binding and one due resume."""
    thread_dir.mkdir(parents=True, exist_ok=True)
    (thread_dir / "checkout.json").write_text(
        json.dumps({"session_id": session_id, "worktree_root": str(thread_dir)})
    )
    schedule = thread_dir / "scheduled.json"
    schedule.write_text(
        json.dumps(
            [_entry(kind="resume", wake_at=CLI_PAST, prompt="go", thread_id=session_id)]
        )
    )
    return schedule


def test_schedules_run_while_a_reconciliation_is_in_flight(tmp_path, monkeypatch, capsys):
    """escapement-4qta: measured 15m06s from arming to firing on the live daemon.

    Reconciliation walks a retained worktree registry and takes 10-15 minutes.
    While it held the single legacy-fire lock, a newly-armed wakeup was not even
    enumerated, so launchd's 60s cadence bought nothing.
    """
    root = tmp_path / "threads"
    schedule = _due_resume(root / "thread-1", "thread-1")

    # A reconciliation from an earlier pass is still running.
    held = ww.schedule_store.try_lock(tmp_path / "worktree-reconcile.json")
    assert held is not None, "test could not take the reconcile lock"
    try:
        spawned = []
        monkeypatch.setattr(ww.subprocess, "Popen", lambda argv, cwd: spawned.append(argv))
        monkeypatch.setattr(
            ww.wls, "reconcile",
            lambda _root: (_ for _ in ()).throw(AssertionError("must not reconcile")),
        )

        assert ww.main(["--threads-root", str(root), "--legacy-fire"]) == 0

        assert len(spawned) == 1, "the due wakeup must fire despite reconciliation"
        assert json.loads(schedule.read_text()) == []  # one-shot pruned
        assert "reconciliation already running" in capsys.readouterr().out
    finally:
        held.close()


def test_reconciliation_still_runs_when_its_lock_is_free(tmp_path, monkeypatch):
    """Negative control: reconciliation must not be starved.

    It silently stopped for 17 days once (see the comment at the reconcile call);
    detaching the locks must not reintroduce that.
    """
    root = tmp_path / "threads"
    (root / "thread-1").mkdir(parents=True)
    (root / "thread-1" / "scheduled.json").write_text("[]")
    reconciled = []
    monkeypatch.setattr(ww.wls, "reconcile", lambda value: reconciled.append(value))

    assert ww.main(["--threads-root", str(root), "--legacy-fire"]) == 0
    assert reconciled == [tmp_path]


def test_a_second_schedule_pass_is_still_excluded(tmp_path, monkeypatch, capsys):
    """Negative control: two passes must not process the same schedule at once."""
    root = tmp_path / "threads"
    _due_resume(root / "thread-1", "thread-1")

    held = ww.schedule_store.try_lock(tmp_path / "legacy-fire.json")
    assert held is not None
    try:
        spawned = []
        monkeypatch.setattr(ww.subprocess, "Popen", lambda argv, cwd: spawned.append(argv))
        assert ww.main(["--threads-root", str(root), "--legacy-fire"]) == 0
        assert spawned == [], "a concurrent schedule pass must not double-fire"
        assert "already running" in capsys.readouterr().out
    finally:
        held.close()
