#!/usr/bin/env python3
"""
Sanity tests for would_block_stop.

Governed by .agent/runtime/test-oracle-brief.md. Covers the canonical decision
scenarios plus the explicit negative and positive controls named there. Not
the full 57-stall regression test (that's v0.1) — this is enough to ship v0
with confidence the gate behaves correctly on the explicitly-enumerated
scenarios and rejects the named fragile implementation (stale-last_run reuse).

Run: python3 harness/tests/test_gate.py
"""

from __future__ import annotations

import datetime as _dt
import pathlib
import sys

HARNESS_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HARNESS_ROOT / "bin"))

from would_block_stop import would_block_stop  # noqa: E402


def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _past_iso(seconds_ago: int) -> str:
    return (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(seconds=seconds_ago)).isoformat()


def _future_iso(seconds_ahead: int) -> str:
    return (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(seconds=seconds_ahead)).isoformat()


def _contract(*, exit_code=None, ts=None, expected_exit=0):
    c = {
        "goal": "x",
        "verification_command": "true",
        "expected_exit": expected_exit,
        "source": "agent-declared",
        "thread_id": "t",
        "created_at": _now_iso(),
        "last_run": None,
    }
    if exit_code is not None:
        c["last_run"] = {"exit_code": exit_code, "timestamp": ts or _now_iso()}
    return c


CASES = [
    # Positive control #1 — happy path must not be broken.
    {
        "name": "verification_passed (fresh)",
        "state": {"contract": _contract(exit_code=0, ts=_now_iso())},
        "expect": ("allow", "verification_passed"),
    },
    # Negative control #1 — the named fragile implementation must fail here.
    {
        "name": "verification_passed (stale last_run beyond window)",
        "state": {"contract": _contract(exit_code=0, ts=_past_iso(600))},
        "expect": ("block", "no_completion_or_resumption_proof"),
    },
    # Invariant: exit-code mismatch is not a pass even if recent.
    {
        "name": "verification_failed (exit mismatch)",
        "state": {"contract": _contract(exit_code=1, ts=_now_iso())},
        "expect": ("block", "no_completion_or_resumption_proof"),
    },
    # Positive control #2 — wakeup-without-contract must allow.
    {
        "name": "wakeup_registered (future)",
        "state": {
            "contract": None,
            "scheduled": [
                {
                    "wake_at": _future_iso(120),
                    "prompt": "resume work",
                    "thread_id": "t",
                    "created_by": "ScheduleWakeup",
                    "crash_count": 0,
                }
            ],
        },
        "expect": ("allow", "wakeup_registered"),
    },
    # Invariant: past wakeups don't count.
    {
        "name": "wakeup_past (does not count)",
        "state": {
            "contract": None,
            "scheduled": [
                {
                    "wake_at": _past_iso(120),
                    "prompt": "old",
                    "thread_id": "t",
                    "created_by": "ScheduleWakeup",
                    "crash_count": 0,
                }
            ],
        },
        "expect": ("block", "no_contract"),
    },
    # User release variants.
    {
        "name": "user_released ('stop')",
        "state": {"contract": None, "recent_user_message": "stop"},
        "expect": ("allow", "user_released"),
    },
    {
        "name": "user_released ('end here.')",
        "state": {"contract": None, "recent_user_message": "end here."},
        "expect": ("allow", "user_released"),
    },
    {
        "name": "non-release message does not release",
        "state": {"contract": None, "recent_user_message": "what's next?"},
        "expect": ("block", "no_contract"),
    },
    # Negative control #2 — empty state defaults to block.
    {
        "name": "empty state defaults to block",
        "state": {},
        "expect": ("block", "no_contract"),
    },
    # Invariant: contract present but no proof at all.
    {
        "name": "contract present but no proof",
        "state": {"contract": _contract()},
        "expect": ("block", "no_completion_or_resumption_proof"),
    },
    # user_released takes priority over an unverified contract (B1 oracle).
    {
        "name": "user_released with unverified contract present",
        "state": {"contract": _contract(), "recent_user_message": "stop"},
        "expect": ("allow", "user_released"),
    },
    # Invariant: wakeup outranks absent contract.
    {
        "name": "wakeup wins over absent contract",
        "state": {
            "scheduled": [
                {
                    "wake_at": _future_iso(60),
                    "prompt": "resume",
                    "thread_id": "t",
                    "created_by": "x",
                    "crash_count": 0,
                }
            ],
        },
        "expect": ("allow", "wakeup_registered"),
    },
    # Malformed state should not allow stop.
    {
        "name": "malformed contract treated as null",
        "state": {"contract": "this is not a dict"},
        "expect": ("block", "no_contract"),
    },
    {
        "name": "malformed scheduled treated as null",
        "state": {"contract": None, "scheduled": "not a list"},
        "expect": ("block", "no_contract"),
    },
    # Custom expected_exit honored.
    {
        "name": "custom expected_exit honored",
        "state": {"contract": _contract(exit_code=42, ts=_now_iso(), expected_exit=42)},
        "expect": ("allow", "verification_passed"),
    },
    {
        "name": "custom expected_exit rejects wrong code",
        "state": {"contract": _contract(exit_code=0, ts=_now_iso(), expected_exit=42)},
        "expect": ("block", "no_completion_or_resumption_proof"),
    },
]


def run() -> int:
    passed = 0
    failed = 0
    for case in CASES:
        got = would_block_stop(case["state"])
        ok = got == case["expect"]
        status = "PASS" if ok else "FAIL"
        if ok:
            passed += 1
        else:
            failed += 1
        print(f"{status}: {case['name']}  expected={case['expect']!r}  got={got!r}")
    print(f"\n{passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


# ---------------------------------------------------------------------------
# Session-isolation tests (v0.1) — governed by the Session-isolation invariant
# in .agent/runtime/test-oracle-brief.md. These verify two concurrent sessions
# get distinct thread dirs and cannot clobber each other's contracts.
# ---------------------------------------------------------------------------

import json  # noqa: E402
import os as _os  # noqa: E402
import tempfile as _tempfile  # noqa: E402
from would_block_stop import (  # noqa: E402
    thread_dir_for_session,
    sanitize_session_id,
    load_thread_state,
)


def _assert(cond, name, results):
    results.append((cond, name))
    print(f"{'PASS' if cond else 'FAIL'}: {name}")


def run_isolation() -> int:
    results = []
    root = pathlib.Path(_tempfile.mkdtemp(prefix="harness-iso-"))

    # Ensure no override leaks in from the environment for the resolution tests.
    saved_override = _os.environ.pop("HARNESS_THREAD_DIR", None)
    try:
        # Resolution invariant: distinct sessions -> distinct dirs (the bug fix).
        a = thread_dir_for_session("sessA-1111", root)
        b = thread_dir_for_session("sessB-2222", root)
        _assert(a != b, "distinct session_ids resolve to distinct dirs", results)
        _assert(a == root / "threads" / "sessA-1111", "session dir is threads/{id}", results)

        # Determinism: same inputs -> same path.
        _assert(thread_dir_for_session("sessA-1111", root) == a, "resolution is deterministic", results)

        # Fallback: no session id -> current.
        _assert(
            thread_dir_for_session(None, root) == root / "threads" / "current",
            "no session_id falls back to threads/current",
            results,
        )
        _assert(
            thread_dir_for_session("", root) == root / "threads" / "current",
            "empty session_id falls back to threads/current",
            results,
        )

        # Sanitization: path traversal cannot escape threads/.
        evil = thread_dir_for_session("../../etc/passwd", root)
        _assert(
            str(evil.resolve()).startswith(str((root / "threads").resolve())),
            "malicious session_id cannot escape threads/",
            results,
        )
        _assert(sanitize_session_id("a/b/../c") == "abc", "sanitizer strips path metachars", results)
        _assert(sanitize_session_id("x" * 500) == "x" * 128, "sanitizer caps length at 128", results)

        # Override wins (for tests / special cases).
        _os.environ["HARNESS_THREAD_DIR"] = str(root / "explicit")
        _assert(
            thread_dir_for_session("ignored", root) == root / "explicit",
            "HARNESS_THREAD_DIR override wins over session_id",
            results,
        )
        _os.environ.pop("HARNESS_THREAD_DIR", None)

        # Negative control: session A writes a contract, session B writes its own;
        # A's contract is byte-identical afterward (the exact reported bug).
        dir_a = thread_dir_for_session("sessA-1111", root)
        dir_b = thread_dir_for_session("sessB-2222", root)
        dir_a.mkdir(parents=True, exist_ok=True)
        dir_b.mkdir(parents=True, exist_ok=True)
        contract_a = {"goal": "A's goal", "verification_command": "true", "expected_exit": 0,
                      "source": "agent-declared", "thread_id": "sessA-1111", "created_at": _now_iso(), "last_run": None}
        (dir_a / "contract.json").write_text(json.dumps(contract_a))
        a_bytes_before = (dir_a / "contract.json").read_bytes()
        contract_b = {"goal": "B's goal", "verification_command": "false", "expected_exit": 0,
                      "source": "agent-declared", "thread_id": "sessB-2222", "created_at": _now_iso(), "last_run": None}
        (dir_b / "contract.json").write_text(json.dumps(contract_b))
        a_bytes_after = (dir_a / "contract.json").read_bytes()
        _assert(a_bytes_before == a_bytes_after, "session B writing its contract does NOT clobber session A's", results)

        # Positive control: A loads its own state and sees A's goal, not B's.
        state_a = load_thread_state(dir_a)
        _assert(
            state_a["contract"]["goal"] == "A's goal",
            "session A loads its own contract, not B's",
            results,
        )
    finally:
        if saved_override is not None:
            _os.environ["HARNESS_THREAD_DIR"] = saved_override
        else:
            _os.environ.pop("HARNESS_THREAD_DIR", None)
        import shutil as _shutil
        _shutil.rmtree(root, ignore_errors=True)

    passed = sum(1 for ok, _ in results if ok)
    failed = sum(1 for ok, _ in results if not ok)
    print(f"\n[isolation] {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


def run_portability() -> int:
    """Portability invariant: no harness script may hardcode the author's repo
    path. That hardcoding is exactly what made the harness non-installable —
    it only worked at ~/GitHub/claude-workflow-setup. Static check over source.
    """
    results = []
    bindir = HARNESS_ROOT / "bin"
    offenders = []
    for f in sorted(bindir.iterdir()):
        if f.is_dir():
            continue
        try:
            text = f.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        if "claude-workflow-setup/harness" in text or "GitHub/claude-workflow-setup" in text:
            offenders.append(f.name)
    _assert(not offenders, f"no harness script hardcodes the repo path (offenders: {offenders})", results)

    # Default state root resolves to the standard per-user location, not a repo.
    from would_block_stop import DEFAULT_HARNESS_ROOT  # noqa: E402
    s = str(DEFAULT_HARNESS_ROOT)
    _assert("GitHub" not in s and "claude-workflow-setup" not in s,
            "default state root is not inside the repo / GitHub tree", results)

    passed = sum(1 for ok, _ in results if ok)
    failed = sum(1 for ok, _ in results if not ok)
    print(f"\n[portability] {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


import subprocess as _subprocess  # noqa: E402


def run_stop_hook() -> int:
    """Integration tests for stop_hook.py — B1 (transcript reading) and B2 (no-contract allow).

    These call the hook as a subprocess, controlling HARNESS_THREAD_DIR, so
    they test the full adapter path rather than would_block_stop in isolation.
    """
    results = []
    bin_path = HARNESS_ROOT / "bin" / "stop_hook.py"

    def call_hook(payload: dict, thread_dir: pathlib.Path) -> "dict | None":
        env = {**_os.environ, "HARNESS_THREAD_DIR": str(thread_dir)}
        r = _subprocess.run(
            [sys.executable, str(bin_path)],
            input=json.dumps(payload),
            capture_output=True, text=True, env=env,
        )
        if r.stdout.strip():
            try:
                return json.loads(r.stdout)
            except json.JSONDecodeError:
                return {"raw": r.stdout}
        return None  # allow: hook exited 0 with no output

    import shutil as _shutil
    import tempfile as _tf
    tmp = pathlib.Path(_tf.mkdtemp(prefix="harness-hook-"))
    try:
        # B2: no contract.json → allow stop (conversational session, no gate).
        td = tmp / "no-contract"
        td.mkdir(parents=True)
        out = call_hook({"session_id": "x", "transcript_path": ""}, td)
        _assert(out is None, "B2: no contract.json → allow (no block output)", results)

        # B2 negative: malformed contract.json → block (fail safe, not silently allow).
        td = tmp / "malformed"
        td.mkdir(parents=True)
        (td / "contract.json").write_text("not valid json {{{")
        out = call_hook({"session_id": "x", "transcript_path": ""}, td)
        _assert(
            out is not None and out.get("decision") == "block",
            "B2 negative: malformed contract.json → block (fail safe)",
            results,
        )

        # B1: user says 'stop' in transcript → allow even with unverified contract.
        td = tmp / "b1-user-release"
        td.mkdir(parents=True)
        contract = {
            "goal": "test", "verification_command": "false", "expected_exit": 0,
            "source": "agent-declared", "thread_id": "x",
            "created_at": _now_iso(), "last_run": None,
        }
        (td / "contract.json").write_text(json.dumps(contract))
        transcript = tmp / "transcript-stop.jsonl"
        transcript.write_text(
            json.dumps({"message": {"role": "user", "content": [{"type": "text", "text": "stop"}]}}) + "\n"
        )
        out = call_hook({"session_id": "x", "transcript_path": str(transcript)}, td)
        _assert(out is None, "B1: transcript 'stop' with unverified contract → allow (user_released)", results)

        # B1 negative: non-release transcript message + unverified contract → block.
        td = tmp / "b1-non-release"
        td.mkdir(parents=True)
        (td / "contract.json").write_text(json.dumps(contract))
        transcript2 = tmp / "transcript-question.jsonl"
        transcript2.write_text(
            json.dumps({"message": {"role": "user", "content": [{"type": "text", "text": "what's the status?"}]}}) + "\n"
        )
        out = call_hook({"session_id": "x", "transcript_path": str(transcript2)}, td)
        _assert(
            out is not None and out.get("decision") == "block",
            "B1 negative: non-release message + unverified contract → block",
            results,
        )
    finally:
        _shutil.rmtree(tmp, ignore_errors=True)

    passed = sum(1 for ok, _ in results if ok)
    failed = sum(1 for ok, _ in results if not ok)
    print(f"\n[stop_hook] {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


def run_task_mode() -> int:
    """Integration tests for session-mode (task mode entry + queue-drain gate).

    Uses fake 'bd' scripts in a temp bin dir to control bd ready / bd list output
    without needing a real beads database.
    """
    results = []
    bin_path = HARNESS_ROOT / "bin" / "stop_hook.py"
    entry_path = HARNESS_ROOT / "bin" / "task_mode_entry.py"

    import shutil as _shutil
    import tempfile as _tf

    def call_hook(payload: dict, thread_dir: pathlib.Path, env_extra=None) -> "dict | None":
        env = {**_os.environ, "HARNESS_THREAD_DIR": str(thread_dir), **(env_extra or {})}
        r = _subprocess.run(
            [sys.executable, str(bin_path)],
            input=json.dumps(payload),
            capture_output=True, text=True, env=env,
        )
        if r.stdout.strip():
            try:
                return json.loads(r.stdout)
            except json.JSONDecodeError:
                return {"raw": r.stdout}
        return None

    def call_entry(payload: dict, thread_dir: pathlib.Path) -> int:
        env = {**_os.environ, "HARNESS_THREAD_DIR": str(thread_dir)}
        r = _subprocess.run(
            [sys.executable, str(entry_path)],
            input=json.dumps(payload),
            capture_output=True, text=True, env=env,
        )
        return r.returncode

    def make_fake_bd(tmp: pathlib.Path, ready_items: int, list_items: int) -> pathlib.Path:
        """Write a fake 'bd' script returning JSON arrays of controlled length."""
        bin_dir = tmp / "fakebin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        script = bin_dir / "bd"
        ready_json = json.dumps([{"id": f"t-{i}"} for i in range(ready_items)])
        list_json = json.dumps([{"id": f"t-{i}"} for i in range(list_items)])
        script.write_text(
            "#!/bin/sh\n"
            f'if echo "$*" | grep -q "^ready"; then echo \'{ready_json}\'; exit 0; fi\n'
            f'if echo "$*" | grep -q "^list"; then echo \'{list_json}\'; exit 0; fi\n'
            "exit 0\n"
        )
        script.chmod(0o755)
        return bin_dir

    tmp = pathlib.Path(_tf.mkdtemp(prefix="harness-task-mode-"))
    try:
        # --- Pre-tool hook (task_mode_entry.py) ---

        # Claim command → writes session_mode.json.
        td = tmp / "entry-claim"
        td.mkdir(parents=True)
        rc = call_entry(
            {"session_id": "x", "tool_name": "Bash",
             "tool_input": {"command": "bd update cake-123 --claim"}},
            td,
        )
        mode = json.loads((td / "session_mode.json").read_text()) if (td / "session_mode.json").exists() else None
        _assert(rc == 0 and mode is not None and mode.get("mode") == "task",
                "entry: claim command writes session_mode.json with mode=task", results)

        # Non-claim bd command → no session_mode.json.
        td = tmp / "entry-no-claim"
        td.mkdir(parents=True)
        call_entry(
            {"session_id": "x", "tool_name": "Bash",
             "tool_input": {"command": "bd list"}},
            td,
        )
        _assert(not (td / "session_mode.json").exists(),
                "entry: non-claim command does not write session_mode.json", results)

        # Non-Bash tool → no session_mode.json.
        td = tmp / "entry-non-bash"
        td.mkdir(parents=True)
        call_entry(
            {"session_id": "x", "tool_name": "Read",
             "tool_input": {"file_path": "/tmp/x"}},
            td,
        )
        _assert(not (td / "session_mode.json").exists(),
                "entry: non-Bash tool does not write session_mode.json", results)

        # First-claim-wins: second claim does not overwrite.
        td = tmp / "entry-first-wins"
        td.mkdir(parents=True)
        call_entry({"session_id": "x", "tool_name": "Bash",
                    "tool_input": {"command": "bd update cake-1 --claim"}}, td)
        first_ctime = (td / "session_mode.json").read_text()
        call_entry({"session_id": "x", "tool_name": "Bash",
                    "tool_input": {"command": "bd update cake-2 --claim"}}, td)
        second_ctime = (td / "session_mode.json").read_text()
        _assert(first_ctime == second_ctime,
                "entry: first-claim-wins — second claim does not overwrite session_mode.json", results)

        # --- Stop hook task mode queue-drain gate ---

        # Task mode + ready items → block (tasks remain).
        td = tmp / "queue-has-items"
        td.mkdir(parents=True)
        fake_beads = td / ".beads"
        fake_beads.mkdir()
        mode_rec = {"mode": "task", "repo_cwd": str(td), "parent_id": None,
                    "entered_at": _now_iso(), "session_id": "x"}
        (td / "session_mode.json").write_text(json.dumps(mode_rec))
        fakebin = make_fake_bd(tmp / "bin1", ready_items=1, list_items=1)
        out = call_hook({"session_id": "x", "transcript_path": ""},
                        td, {"PATH": f"{fakebin}:{_os.environ.get('PATH', '')}"})
        _assert(out is not None and out.get("decision") == "block",
                "task mode: bd ready non-empty → block (tasks remain)", results)

        # Task mode + empty ready + open tasks → block (all blocked, register wakeup).
        td = tmp / "queue-empty-but-open"
        td.mkdir(parents=True)
        (td / ".beads").mkdir()
        (td / "session_mode.json").write_text(json.dumps({**mode_rec, "repo_cwd": str(td)}))
        fakebin = make_fake_bd(tmp / "bin2", ready_items=0, list_items=1)
        out = call_hook({"session_id": "x", "transcript_path": ""},
                        td, {"PATH": f"{fakebin}:{_os.environ.get('PATH', '')}"})
        _assert(
            out is not None and out.get("decision") == "block"
            and "all_remaining_tasks_blocked" in out.get("reason", ""),
            "task mode: bd ready empty + open tasks → block (all blocked, reason in display)",
            results,
        )

        # Task mode + empty ready + no open tasks → allow (queue drained).
        td = tmp / "queue-drained"
        td.mkdir(parents=True)
        (td / ".beads").mkdir()
        (td / "session_mode.json").write_text(json.dumps({**mode_rec, "repo_cwd": str(td)}))
        fakebin = make_fake_bd(tmp / "bin3", ready_items=0, list_items=0)
        out = call_hook({"session_id": "x", "transcript_path": ""},
                        td, {"PATH": f"{fakebin}:{_os.environ.get('PATH', '')}"})
        _assert(out is None,
                "task mode: bd ready empty + no open tasks → allow (queue drained)", results)

        # Task mode + user says 'stop' → allow (universal override).
        td = tmp / "task-mode-user-release"
        td.mkdir(parents=True)
        (td / ".beads").mkdir()
        (td / "session_mode.json").write_text(json.dumps({**mode_rec, "repo_cwd": str(td)}))
        transcript = tmp / "transcript-task-stop.jsonl"
        transcript.write_text(
            json.dumps({"message": {"role": "user", "content": [{"type": "text", "text": "stop"}]}}) + "\n"
        )
        fakebin = make_fake_bd(tmp / "bin4", ready_items=1, list_items=1)
        out = call_hook({"session_id": "x", "transcript_path": str(transcript)},
                        td, {"PATH": f"{fakebin}:{_os.environ.get('PATH', '')}"})
        _assert(out is None,
                "task mode: user 'stop' overrides queue-drain gate → allow", results)

    finally:
        _shutil.rmtree(tmp, ignore_errors=True)

    passed = sum(1 for ok, _ in results if ok)
    failed = sum(1 for ok, _ in results if not ok)
    print(f"\n[task_mode] {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


def run_implicit_queue() -> int:
    """Integration tests for B3 fix: implicit bd queue check after verification_passed.

    Covers the subagent-claim gap: when task-mode was not entered via the PreToolUse
    hook but bd work is still in-flight, the stop hook should block.
    """
    results = []
    bin_path = HARNESS_ROOT / "bin" / "stop_hook.py"

    import shutil as _shutil
    import tempfile as _tf

    def _passing_contract(thread_id: str) -> dict:
        """A contract whose last_run is fresh and exit_code 0 — would_block_stop returns allow."""
        return {
            "goal": "test outcome",
            "verification_command": "true",
            "expected_exit": 0,
            "source": "agent-declared",
            "thread_id": thread_id,
            "created_at": _now_iso(),
            "last_run": {
                "exit_code": 0,
                "timestamp": _now_iso(),
                "output_excerpt": "",
            },
        }

    def make_fake_bd_implicit(
        bin_dir: pathlib.Path,
        in_progress_items: int,
        ready_items: int,
    ) -> pathlib.Path:
        """Fake bd distinguishing in_progress (list --status=in_progress) from ready."""
        bin_dir.mkdir(parents=True, exist_ok=True)
        script = bin_dir / "bd"
        ip_json = json.dumps([{"id": f"t-{i}", "title": f"task {i}"} for i in range(in_progress_items)])
        ready_json = json.dumps([{"id": f"t-{i}", "title": f"task {i}"} for i in range(ready_items)])
        script.write_text(
            "#!/bin/sh\n"
            f"if echo \"$*\" | grep -q 'in_progress'; then echo '{ip_json}'; exit 0; fi\n"
            f"if echo \"$*\" | grep -q '^ready'; then echo '{ready_json}'; exit 0; fi\n"
            "echo '[]'; exit 0\n"
        )
        script.chmod(0o755)
        return bin_dir

    def call_hook(
        payload: dict,
        thread_dir: pathlib.Path,
        project_dir: pathlib.Path,
        env_extra: "dict | None" = None,
    ) -> "dict | None":
        """Run stop_hook.py from project_dir so os.getcwd() returns the project."""
        env = {**_os.environ, "HARNESS_THREAD_DIR": str(thread_dir), **(env_extra or {})}
        r = _subprocess.run(
            [sys.executable, str(bin_path)],
            input=json.dumps(payload),
            capture_output=True, text=True, env=env,
            cwd=str(project_dir),
        )
        if r.stdout.strip():
            try:
                return json.loads(r.stdout)
            except json.JSONDecodeError:
                return {"raw": r.stdout}
        return None

    tmp = pathlib.Path(_tf.mkdtemp(prefix="harness-implicit-"))
    try:
        # Test 1: verify passes, no .beads/ in cwd → allow (no bd project, skip check).
        td = tmp / "no-beads"
        td.mkdir()
        project_dir = tmp / "project-no-beads"
        project_dir.mkdir()
        (td / "contract.json").write_text(json.dumps(_passing_contract("no-beads")))
        out = call_hook({"session_id": "no-beads", "transcript_path": ""}, td, project_dir)
        _assert(
            out is None,
            "implicit: verify passes, no .beads/ → allow (no implicit check)",
            results,
        )

        # Test 2: verify passes, in-progress items in .beads/ repo → block.
        td = tmp / "in-progress-block"
        td.mkdir()
        project_dir = tmp / "project-in-progress"
        project_dir.mkdir()
        (project_dir / ".beads").mkdir()
        (td / "contract.json").write_text(json.dumps(_passing_contract("in-progress")))
        fakebin = make_fake_bd_implicit(tmp / "bin-ip", in_progress_items=1, ready_items=0)
        out = call_hook(
            {"session_id": "in-progress", "transcript_path": ""},
            td, project_dir,
            {"PATH": f"{fakebin}:{_os.environ.get('PATH', '')}"},
        )
        _assert(
            out is not None and out.get("decision") == "block"
            and "unfinished work" in out.get("reason", ""),
            "implicit: verify passes, in-progress items → block (implicit_queue_in_progress)",
            results,
        )

        # Test 3: verify passes, ready items (no in-progress) → block.
        td = tmp / "ready-block"
        td.mkdir()
        project_dir = tmp / "project-ready"
        project_dir.mkdir()
        (project_dir / ".beads").mkdir()
        (td / "contract.json").write_text(json.dumps(_passing_contract("ready")))
        fakebin = make_fake_bd_implicit(tmp / "bin-ready", in_progress_items=0, ready_items=2)
        out = call_hook(
            {"session_id": "ready", "transcript_path": ""},
            td, project_dir,
            {"PATH": f"{fakebin}:{_os.environ.get('PATH', '')}"},
        )
        _assert(
            out is not None and out.get("decision") == "block",
            "implicit: verify passes, ready items (no in-progress) → block (implicit_queue_ready_items)",
            results,
        )

        # Test 4: verify passes, queue empty → allow.
        td = tmp / "queue-empty"
        td.mkdir()
        project_dir = tmp / "project-empty"
        project_dir.mkdir()
        (project_dir / ".beads").mkdir()
        (td / "contract.json").write_text(json.dumps(_passing_contract("empty")))
        fakebin = make_fake_bd_implicit(tmp / "bin-empty", in_progress_items=0, ready_items=0)
        out = call_hook(
            {"session_id": "empty", "transcript_path": ""},
            td, project_dir,
            {"PATH": f"{fakebin}:{_os.environ.get('PATH', '')}"},
        )
        _assert(
            out is None,
            "implicit: verify passes, queue empty → allow (implicit_queue_drained)",
            results,
        )

        # Test 5: user_released bypasses implicit check even with in-progress items.
        td = tmp / "user-release-bypass"
        td.mkdir()
        project_dir = tmp / "project-user-release"
        project_dir.mkdir()
        (project_dir / ".beads").mkdir()
        # Contract is NOT passing (last_run=None) — but user says stop.
        unverified_contract = {
            "goal": "test", "verification_command": "false", "expected_exit": 0,
            "source": "agent-declared", "thread_id": "user-release",
            "created_at": _now_iso(), "last_run": None,
        }
        (td / "contract.json").write_text(json.dumps(unverified_contract))
        transcript = tmp / "transcript-user-release.jsonl"
        transcript.write_text(
            json.dumps({"message": {"role": "user", "content": [{"type": "text", "text": "stop"}]}}) + "\n"
        )
        fakebin = make_fake_bd_implicit(tmp / "bin-urel", in_progress_items=3, ready_items=5)
        out = call_hook(
            {"session_id": "user-release", "transcript_path": str(transcript)},
            td, project_dir,
            {"PATH": f"{fakebin}:{_os.environ.get('PATH', '')}"},
        )
        _assert(
            out is None,
            "implicit: user_released bypasses implicit queue check even with bd work",
            results,
        )

    finally:
        _shutil.rmtree(tmp, ignore_errors=True)

    passed = sum(1 for ok, _ in results if ok)
    failed = sum(1 for ok, _ in results if not ok)
    print(f"\n[implicit_queue] {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    rc_gate = run()
    rc_iso = run_isolation()
    rc_port = run_portability()
    rc_hook = run_stop_hook()
    rc_task = run_task_mode()
    rc_implicit = run_implicit_queue()
    sys.exit(rc_gate or rc_iso or rc_port or rc_hook or rc_task or rc_implicit)
