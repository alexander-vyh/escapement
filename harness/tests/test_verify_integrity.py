#!/usr/bin/env python3
"""Oracle for the verification-command suppression detector (move 1b).

Business invariant
------------------
A contract's `verification_command` is the agent's to write, so an agent can
reach exit 0 by GUTTING the check instead of fixing the work — the never-suppress
violation relocated to the contract oracle. A self-neutering command must NOT
count as a passed verification at the harness Stop gate.

Conservative by design (per the approved scope): flag only UNAMBIGUOUS
self-neutering. Scope-narrowing (`pytest -k`) and `|| exit` (which PROPAGATES the
failure) are deliberately NOT flagged — those need a baseline / stay with the
oracle-downgrade detectors + human review.

Fragile implementation this suite rejects
------------------------------------------
Anything that lets `verification_command: "true"` (or `pytest || true`) reach the
("allow", "verification_passed") decision with exit_code 0. The integration tests
at the bottom kill that.
"""

from __future__ import annotations

import datetime as _dt
import pathlib
import sys

HARNESS_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HARNESS_ROOT / "bin"))

from verify_integrity import is_suppressed_verification  # noqa: E402
from would_block_stop import would_block_stop  # noqa: E402


# --- POSITIVE: these are self-neutering and MUST be flagged ------------------

def test_bare_noop_commands_flagged():
    for cmd in ("true", ":", "  true  "):
        assert is_suppressed_verification(cmd), cmd


def test_or_true_masking_flagged():
    for cmd in ("pytest || true", "pytest tests/ || :", "pytest || exit 0", "ruff check||true"):
        assert is_suppressed_verification(cmd), cmd


def test_trailing_semicolon_true_flagged():
    for cmd in ("pytest; true", "ruff check ; exit 0", "pytest ; :"):
        assert is_suppressed_verification(cmd), cmd


def test_embedded_hook_disable_flagged():
    for cmd in ("git commit --no-verify", "SKIP=flake8 pytest", "HUSKY=0 npm test"):
        assert is_suppressed_verification(cmd), cmd


# --- NEGATIVE: legitimate verify commands MUST NOT be flagged ----------------

def test_plain_commands_not_flagged():
    for cmd in ("pytest", "pytest -q", "ruff check && pytest", "make test"):
        assert is_suppressed_verification(cmd) is None, cmd


def test_scope_narrowing_not_flagged():
    # Conservative scope: -k narrowing isn't mechanically a suppression here.
    assert is_suppressed_verification("pytest -k some_test") is None


def test_true_as_prefix_not_flagged():
    # `true && pytest` runs pytest and propagates its exit — not masking.
    assert is_suppressed_verification("true && pytest") is None


def test_or_exit_propagates_not_flagged():
    # `|| exit` (no code) exits with the failing command's status — propagates.
    assert is_suppressed_verification("pytest || exit") is None


def test_skip_lookalike_not_flagged():
    assert is_suppressed_verification("SKIP_SLOW=1 pytest") is None


def test_empty_not_flagged():
    assert is_suppressed_verification("") is None
    assert is_suppressed_verification(None) is None


# --- INTEGRATION: the gate must not allow a suppressed green -----------------

def _now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _state(command: str):
    return {
        "contract": {
            "goal": "x",
            "verification_command": command,
            "expected_exit": 0,
            "last_run": {"exit_code": 0, "timestamp": _now_iso()},
        },
        "scheduled": None,
        "recent_user_message": None,
    }


def test_gate_blocks_suppressed_green():
    decision, reason = would_block_stop(_state("pytest || true"))
    assert (decision, reason) == ("block", "verification_suppressed"), (
        f"a suppressed verify command at exit 0 must block with a distinct reason; got {decision}/{reason}"
    )


def test_gate_allows_genuine_green():
    decision, reason = would_block_stop(_state("pytest -q"))
    assert (decision, reason) == ("allow", "verification_passed")
