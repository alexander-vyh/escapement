"""Oracle for the file-complexity gate.

Business invariant
------------------
A Write/Edit that would push a NON-exempt file past 500 lines is blocked
(exit 2, ``permissionDecision: deny``) unless a *substantive* waiver is present.
Legitimate writes at/under the limit, exempt paths, and validly-waived files are
allowed (exit 0). The gate fails OPEN on malformed input or unreadable targets —
it must never crash a session.

Independent source of truth
---------------------------
The 500-line LIMIT and the waiver convention (``# file-complexity-waiver: <reason>``
in the first 5 lines, or ``FILE_COMPLEXITY_WAIVER`` env) — asserted via the
externally observable hook contract (exit code + stdout decision), NOT by importing
LIMIT and recomputing it (that would be an implementation echo).

Fragile implementations this suite rejects
-------------------------------------------
- Fail-open / always-allow  -> ``test_write_over_limit_no_waiver_denies`` (neg control)
- Over-blocking at the boundary -> ``test_write_exactly_at_limit_allows``
- Presence-only waiver (accepts an empty reason) -> ``test_empty_waiver_reason_still_denies``
  (the gate documents value-not-presence; an empty ``# file-complexity-waiver:`` must NOT bypass)
- Ignoring exemptions -> ``test_exempt_suffix_allows``
"""

import importlib.util
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

TEST_DIR = Path(__file__).resolve().parent
HOOK_PATH = TEST_DIR / "file_complexity_gate.py"
if not HOOK_PATH.exists():
    HOOK_PATH = TEST_DIR.parent / "file_complexity_gate.py"
spec = importlib.util.spec_from_file_location("file_complexity_gate", HOOK_PATH)
gate = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["file_complexity_gate"] = gate
spec.loader.exec_module(gate)


def run_hook(payload: dict) -> tuple[int, dict | None]:
    """Invoke the gate with a hook-protocol payload; return (exit_code, decision|None)."""
    out = io.StringIO()
    # Keep hermetic: the gate's best-effort signal emit must not touch the real corpus.
    with patch.object(gate, "_emit_signal", lambda *a, **k: None), \
            patch("sys.stdin", io.StringIO(json.dumps(payload))), \
            patch("sys.stdout", out):
        code = gate.main()
    text = out.getvalue().strip()
    return code, (json.loads(text) if text else None)


def _write_payload(file_path: str, n_lines: int, *, first_line: str | None = None) -> dict:
    lines = [f"line {i}" for i in range(n_lines)]
    if first_line is not None and lines:
        lines[0] = first_line
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Write",
        "tool_input": {"file_path": file_path, "content": "\n".join(lines)},
    }


# --- Negative control: the bug this gate exists to prevent ---

def test_write_over_limit_no_waiver_denies():
    code, decision = run_hook(_write_payload("/repo/src/big.py", 501))
    assert code == 2
    assert decision is not None and decision["permissionDecision"] == "deny"


# --- Positive controls: must not over-block valid work ---

def test_write_exactly_at_limit_allows():
    # 500 lines is the boundary — allowed (projected <= LIMIT).
    code, decision = run_hook(_write_payload("/repo/src/ok.py", 500))
    assert code == 0
    assert decision is None


def test_write_well_under_limit_allows():
    code, decision = run_hook(_write_payload("/repo/src/small.py", 42))
    assert code == 0


def test_write_over_limit_with_valid_waiver_allows():
    code, _ = run_hook(
        _write_payload("/repo/src/big.py", 501,
                       first_line="# file-complexity-waiver: cohesive renderer, split tracked in bead xyz")
    )
    assert code == 0


# --- Value-not-presence: an empty waiver reason must NOT bypass ---

def test_empty_waiver_reason_still_denies():
    code, decision = run_hook(
        _write_payload("/repo/src/big.py", 501, first_line="# file-complexity-waiver:")
    )
    assert code == 2
    assert decision is not None and decision["permissionDecision"] == "deny"


def test_env_waiver_allows(monkeypatch):
    monkeypatch.setenv("FILE_COMPLEXITY_WAIVER", "deliberate large generated map")
    code, _ = run_hook(_write_payload("/repo/src/big.py", 501))
    assert code == 0


# --- Exemptions ---

def test_exempt_suffix_allows():
    # .md is exempt even far over the limit.
    code, _ = run_hook(_write_payload("/repo/docs/huge.md", 900))
    assert code == 0


def test_exempt_path_fragment_allows():
    code, _ = run_hook(_write_payload("/repo/node_modules/pkg/big.py", 900))
    assert code == 0


# --- Non-target tools and malformed input fail open ---

def test_non_write_edit_tool_allows():
    code, _ = run_hook({"hook_event_name": "PreToolUse", "tool_name": "Read",
                        "tool_input": {"file_path": "/repo/src/big.py"}})
    assert code == 0


def test_malformed_stdin_fails_open():
    out = io.StringIO()
    with patch.object(gate, "_emit_signal", lambda *a, **k: None), \
            patch("sys.stdin", io.StringIO("not json")), patch("sys.stdout", out):
        assert gate.main() == 0


# --- Edit path: delta that pushes an existing file over the limit denies ---

def test_edit_growing_existing_file_over_limit_denies(tmp_path):
    f = tmp_path / "grow.py"
    f.write_text("\n".join(f"line {i}" for i in range(500)))  # at limit
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(f),
            "old_string": "line 0",
            "new_string": "line 0\n" + "\n".join("added" for _ in range(5)),  # +5 lines
        },
    }
    code, decision = run_hook(payload)
    assert code == 2
    assert decision is not None and decision["permissionDecision"] == "deny"


def test_edit_missing_file_fails_open(tmp_path):
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Edit",
        "tool_input": {"file_path": str(tmp_path / "nope.py"),
                       "old_string": "a", "new_string": "b"},
    }
    code, _ = run_hook(payload)
    assert code == 0
