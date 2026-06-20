"""Codex-specific behavioral tests for session_cleanup.py.

Loads the hook from the repo path (no ~/.claude/hooks/ dependency) so these run
in Codex environments. The cleanup targets are pointed at a tmp dir (hermetic), so
no real /tmp state is touched.

The hook fires on SessionStart and deletes stale (older than 24h) state files
matching its known prefixes, leaving recent files and non-matching files alone.

Positive control: a stale matching file is deleted.
Negative controls: a recent matching file is kept; a stale NON-matching file is kept.
"""

from __future__ import annotations

import importlib.util
import io
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

_HOOK_PATH = Path(__file__).resolve().parents[1] / "session_cleanup.py"
if not _HOOK_PATH.exists():
    pytest.fail(f"session_cleanup.py not found at {_HOOK_PATH}")

_spec = importlib.util.spec_from_file_location("session_cleanup", _HOOK_PATH)
gate = importlib.util.module_from_spec(_spec)
sys.modules["session_cleanup"] = gate
_spec.loader.exec_module(gate)


def _aged_file(path: Path, age_seconds: float) -> Path:
    path.write_text("x")
    t = time.time() - age_seconds
    os.utime(path, (t, t))
    return path


def test_codex_session_cleanup_removes_stale_keeps_fresh(tmp_path):
    stale = _aged_file(tmp_path / "context_burn_stale", 48 * 3600)      # >24h: delete
    fresh = _aged_file(tmp_path / "context_burn_fresh", 60)             # recent: keep
    other = _aged_file(tmp_path / "unrelated_stale", 48 * 3600)        # wrong prefix: keep

    with patch.object(gate, "_CLEANUP_TARGETS", [(tmp_path, "context_burn_")]):
        with patch.object(gate, "_CLEANUP_DIRS", []):
            with patch("sys.stdin", io.StringIO("{}")):
                code = gate.main()

    assert code == 0
    assert not stale.exists(), "stale matching file must be deleted (positive control)"
    assert fresh.exists(), "recent matching file must be kept (negative control)"
    assert other.exists(), "stale NON-matching file must be kept (negative control)"
