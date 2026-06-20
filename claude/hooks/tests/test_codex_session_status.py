"""Codex-specific behavioral tests for session_status.py.

Loads the hook from the repo path (no ~/.claude/hooks/ dependency) so these run
in Codex environments. The cwd and bd boundaries (_read_cwd, _molecule_status,
_run_bd) are patched so tests are hermetic and do not depend on a real beads DB.

The hook fires on SessionStart: in a beads project (no active molecule) it emits a
bd queue summary as a systemMessage; it stays silent when the cwd is not a beads
project.

Positive control: beads project + bd queue state -> systemMessage emitted.
Negative control: non-beads cwd -> no output.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_HOOK_PATH = Path(__file__).resolve().parents[1] / "session_status.py"
if not _HOOK_PATH.exists():
    pytest.fail(f"session_status.py not found at {_HOOK_PATH}")

_spec = importlib.util.spec_from_file_location("session_status", _HOOK_PATH)
gate = importlib.util.module_from_spec(_spec)
sys.modules["session_status"] = gate
_spec.loader.exec_module(gate)


def _run_main(cwd: str, bd_lists) -> tuple[int, dict | None]:
    captured = io.StringIO()
    with patch("sys.stdin", io.StringIO(json.dumps({"hook_event_name": "SessionStart", "cwd": cwd}))):
        with patch.object(gate, "_read_cwd", return_value=cwd):
            with patch.object(gate, "_molecule_status", return_value=None):
                with patch.object(gate, "_run_bd", return_value=bd_lists):
                    with patch("sys.stdout", captured):
                        try:
                            code = gate.main()
                        except SystemExit as exc:
                            code = exc.code or 0
    out = captured.getvalue().strip()
    return code, json.loads(out) if out else None


def test_codex_session_status_emits_queue_in_beads_project(tmp_path):
    """Positive control: a beads project with queue state emits a systemMessage.
    Without this, a hook that never emits would pass only the negative control."""
    (tmp_path / ".beads").mkdir()

    code, output = _run_main(str(tmp_path), [{"id": "cake-1", "title": "do the thing"}])

    assert code == 0
    assert output is not None and output.get("systemMessage"), "beads project must emit a status"


def test_codex_session_status_silent_when_not_beads_project(tmp_path):
    """Negative control: non-beads cwd -> no output."""
    code, output = _run_main(str(tmp_path), [{"id": "cake-1", "title": "do the thing"}])

    assert code == 0
    assert output is None, "non-beads cwd must produce no output"
