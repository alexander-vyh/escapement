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


if __name__ == "__main__":
    rc_gate = run()
    rc_iso = run_isolation()
    rc_port = run_portability()
    sys.exit(rc_gate or rc_iso or rc_port)
