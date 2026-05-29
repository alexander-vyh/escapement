"""Tests for ~/.claude/hooks/session_status.py.

Covers all 11 pattern-table cases plus graceful degradation.

Run from anywhere:
  python claude/hooks/tests/test_session_status.py
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

_hooks_dir = Path(__file__).resolve().parent.parent
if str(_hooks_dir) not in sys.path:
    sys.path.insert(0, str(_hooks_dir))

from session_status import _format_status, _task_line, main  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _task(title: str, task_id: str) -> dict:
    return {"id": task_id, "title": title}


def _run_main(
    cwd: str,
    in_progress: Optional[list] = None,
    ready: Optional[list] = None,
    open_all: Optional[list] = None,
    mol_output: str = "",
) -> Optional[str]:
    """Run main() with mocked bd calls and mol-status.sh; return systemMessage or None."""

    def fake_run_bd(args, cwd_arg):
        if "in_progress" in " ".join(args):
            return in_progress if in_progress is not None else []
        if "ready" in args:
            return ready if ready is not None else []
        return open_all if open_all is not None else []

    def fake_mol(cwd_arg):
        return mol_output or None

    with (
        patch("session_status._read_cwd", return_value=cwd),
        patch("session_status._run_bd", side_effect=fake_run_bd),
        patch("session_status._molecule_status", side_effect=fake_mol),
        # main() probes `bd --version` to distinguish all-empty from all-failed.
        # Mock it so this unit test is hermetic — the intent is "bd present +
        # empty queue -> 'Queue empty'", independent of whether the bd binary is
        # installed in the runtime env (it is not, e.g., in CI).
        patch("session_status.subprocess.run", return_value=MagicMock(returncode=0)),
        patch("sys.stdout", new_callable=io.StringIO) as mock_stdout,
    ):
        main()
        output = mock_stdout.getvalue().strip()

    if not output:
        return None
    return json.loads(output).get("systemMessage")


def _with_beads(fn):
    """Decorator: create a temp dir with .beads/ and pass it as cwd."""
    def wrapper():
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".beads").mkdir()
            fn(tmp)
    wrapper.__name__ = fn.__name__
    return wrapper


# ---------------------------------------------------------------------------
# _format_status unit tests
# ---------------------------------------------------------------------------

TASK_A = _task("implement session mode", "proj-42")
TASK_B = _task("write tests", "proj-43")
TASK_C = _task("update docs", "proj-44")


def test_pattern3_one_in_progress_nothing_else():
    assert _format_status([TASK_A], [], []) == "▶ implement session mode (proj-42)"


def test_pattern4_one_in_progress_with_ready():
    assert _format_status([TASK_A], [TASK_B], [TASK_B]) == "▶ implement session mode (proj-42) · 1 ready"


def test_pattern5_one_in_progress_blocked_only():
    # blocked present but no ready — suppressed, show only in-progress
    assert _format_status([TASK_A], [], [TASK_C]) == "▶ implement session mode (proj-42)"


def test_pattern6_one_in_progress_ready_and_blocked():
    # ready takes precedence in display; blocked suppressed
    assert _format_status([TASK_A], [TASK_B], [TASK_B, TASK_C]) == "▶ implement session mode (proj-42) · 1 ready"


def test_pattern7_multiple_in_progress():
    assert _format_status([TASK_A, TASK_B], [], []) == "2 tasks in progress"


def test_pattern8_ready_only():
    assert _format_status([], [TASK_B, TASK_C], [TASK_B, TASK_C]) == "2 tasks ready"


def test_pattern8_one_ready():
    assert _format_status([], [TASK_B], [TASK_B]) == "1 task ready"


def test_pattern9_ready_and_blocked():
    # blocked present but ready also present — show only ready count
    assert _format_status([], [TASK_B], [TASK_B, TASK_C]) == "1 task ready"


def test_pattern10_blocked_only():
    msg = _format_status([], [], [TASK_C])
    assert "1 task blocked" in msg
    assert "bd blocked for details" in msg


def test_pattern10_multiple_blocked():
    msg = _format_status([], [], [TASK_B, TASK_C])
    assert "2 tasks blocked" in msg


def test_pattern11_queue_empty():
    assert _format_status([], [], []) == "Queue empty"


# ---------------------------------------------------------------------------
# _task_line unit tests
# ---------------------------------------------------------------------------

def test_task_line_with_id():
    assert _task_line(TASK_A) == "▶ implement session mode (proj-42)"


def test_task_line_without_id():
    assert _task_line({"title": "my task"}) == "▶ my task"


def test_task_line_empty_title():
    assert _task_line({"id": "x-1"}) == "▶ untitled (x-1)"


# ---------------------------------------------------------------------------
# Integration: main() patterns via mocked bd
# ---------------------------------------------------------------------------

def test_pattern1_no_beads():
    with tempfile.TemporaryDirectory() as tmp:
        with (
            patch("session_status._read_cwd", return_value=tmp),
            patch("sys.stdout", new_callable=io.StringIO) as mock_stdout,
        ):
            main()
        assert mock_stdout.getvalue().strip() == ""


@_with_beads
def test_pattern2_active_molecule(cwd):
    msg = _run_main(cwd, mol_output="Molecule: dark-mode — Build")
    assert msg == "Molecule: dark-mode — Build"


@_with_beads
def test_pattern3_integration(cwd):
    msg = _run_main(cwd, in_progress=[TASK_A], ready=[], open_all=[])
    assert msg == "▶ implement session mode (proj-42)"


@_with_beads
def test_pattern4_integration(cwd):
    msg = _run_main(cwd, in_progress=[TASK_A], ready=[TASK_B], open_all=[TASK_B])
    assert msg == "▶ implement session mode (proj-42) · 1 ready"


@_with_beads
def test_pattern7_integration(cwd):
    msg = _run_main(cwd, in_progress=[TASK_A, TASK_B], ready=[], open_all=[])
    assert msg == "2 tasks in progress"


@_with_beads
def test_pattern8_integration(cwd):
    msg = _run_main(cwd, in_progress=[], ready=[TASK_B, TASK_C], open_all=[TASK_B, TASK_C])
    assert msg == "2 tasks ready"


@_with_beads
def test_pattern10_integration(cwd):
    msg = _run_main(cwd, in_progress=[], ready=[], open_all=[TASK_C])
    assert msg is not None
    assert "blocked" in msg
    assert "bd blocked" in msg


@_with_beads
def test_pattern11_integration(cwd):
    msg = _run_main(cwd, in_progress=[], ready=[], open_all=[])
    assert msg == "Queue empty"


@_with_beads
def test_molecule_takes_priority_over_bd(cwd):
    # Even with in-progress tasks, molecule status wins
    msg = _run_main(cwd, in_progress=[TASK_A], mol_output="Molecule: my-mol — Validate")
    assert msg == "Molecule: my-mol — Validate"


@_with_beads
def test_graceful_degradation_all_bd_none(cwd):
    # All bd calls return None (bd unavailable) — exits silently
    def fake_run_bd(args, cwd_arg):
        return None

    with (
        patch("session_status._read_cwd", return_value=cwd),
        patch("session_status._run_bd", side_effect=fake_run_bd),
        patch("session_status._molecule_status", return_value=None),
        patch("subprocess.run", side_effect=FileNotFoundError),
        patch("sys.stdout", new_callable=io.StringIO) as mock_stdout,
    ):
        main()
    assert mock_stdout.getvalue().strip() == ""


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import traceback

    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS: {t.__name__}")
            passed += 1
        except Exception:
            print(f"FAIL: {t.__name__}")
            traceback.print_exc()
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
