"""Codex-specific behavioral tests for openspec_init_guard.py.

Loads the hook from the repo path (no ~/.claude/hooks/ dependency) so these run
in Codex environments. The init-detection filesystem boundary
(openspec_is_initialized) is patched so tests are hermetic and do not depend on
an openspec/ directory being present.

The hook fires as PreToolUse on Bash `openspec` commands and blocks them when
openspec/ is not initialized — except always-allowed subcommands (init, --help,
--version, config, completion, feedback).

Positive control: a gated openspec command WITH openspec initialized -> allow.
Negative control: a gated openspec command WITHOUT openspec initialized -> deny.
Fast-paths: `openspec init` and non-openspec commands are always allowed.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_HOOK_PATH = Path(__file__).resolve().parents[1] / "openspec_init_guard.py"
if not _HOOK_PATH.exists():
    pytest.fail(f"openspec_init_guard.py not found at {_HOOK_PATH}")

_spec = importlib.util.spec_from_file_location("openspec_init_guard", _HOOK_PATH)
gate = importlib.util.module_from_spec(_spec)
sys.modules["openspec_init_guard"] = gate
_spec.loader.exec_module(gate)


def _run_main(command: str, initialized: bool = True) -> tuple[int, dict | None]:
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }
    captured = io.StringIO()
    with patch("sys.stdin", io.StringIO(json.dumps(payload))):
        with patch.object(gate, "openspec_is_initialized", return_value=initialized):
            with patch("sys.stdout", captured):
                try:
                    code = gate.main()
                except SystemExit as exc:
                    code = exc.code or 0
    out = captured.getvalue().strip()
    return code, json.loads(out) if out else None


def assert_denied(code: int, output: dict | None) -> None:
    assert code == 0, "deny is carried by stdout JSON, not exit 2"
    assert output is not None
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_codex_openspec_command_allowed_when_initialized():
    """Positive control: a gated openspec command with openspec/ present -> allow.

    Without this, an implementation that always denies would pass only the
    negative control.
    """
    code, output = _run_main("openspec list", initialized=True)

    assert code == 0
    assert output is None, f"gated openspec command must be allowed when initialized; got: {output!r}"


def test_codex_openspec_command_denied_when_not_initialized():
    """Negative control: a gated openspec command without openspec/ -> deny.

    This is the gate's core contract. An implementation that always allows would
    pass the positive control but fail here.
    """
    code, output = _run_main("openspec list", initialized=False)

    assert_denied(code, output)
    reason = output["hookSpecificOutput"]["permissionDecisionReason"]
    assert "openspec init" in reason, f"denial must name the remedy; got: {reason!r}"


def test_codex_openspec_init_always_allowed_even_when_not_initialized():
    """Fast-path: `openspec init` is how you set up — never blocked.

    Proves the gate cannot deadlock the very command that resolves it.
    """
    code, output = _run_main("openspec init", initialized=False)

    assert code == 0
    assert output is None, "openspec init must always be allowed"


def test_codex_non_openspec_command_allowed():
    """Fast-path: a command that does not invoke openspec is never gated."""
    code, output = _run_main("ls -la", initialized=False)

    assert code == 0
    assert output is None, "non-openspec commands must always be allowed"
