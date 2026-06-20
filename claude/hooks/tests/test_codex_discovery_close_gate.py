"""Codex-specific behavioral tests for discovery-close-gate.py.

Loads the hook from the repo path (no ~/.claude/hooks/ dependency) so these run
in Codex environments. Tests are hermetic via tmp_path: they build a real
openspec/changes/<name>/design.md and point the hook's project_dir (the payload
`cwd`) at it, exercising the actual design-loading path. No session_id is
supplied, so the within-session dedup is bypassed (no state file is touched) —
this is also the Codex shape, where the Claude session id is absent.

The hook fires as PreToolUse on Bash `bd close`. When the located design doc has
unresolved verification prompts (e.g. a `## Proof of Delivery` section), it
surfaces them as a permissionDecision=ask before allowing the close.

Positive control: `bd close` with a clean design (no prompts) -> allow.
Negative control: `bd close` with a design carrying a Proof of Delivery -> ask.
Fast-paths: non-`bd close` commands, and closes with no design present, allow.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_HOOK_PATH = Path(__file__).resolve().parents[1] / "discovery-close-gate.py"
if not _HOOK_PATH.exists():
    pytest.fail(f"discovery-close-gate.py not found at {_HOOK_PATH}")

_spec = importlib.util.spec_from_file_location("discovery_close_gate", _HOOK_PATH)
gate = importlib.util.module_from_spec(_spec)
sys.modules["discovery_close_gate"] = gate
_spec.loader.exec_module(gate)


def _make_change(cwd: Path, design_text: str | None) -> None:
    if design_text is None:
        return
    change_dir = cwd / "openspec" / "changes" / "test-change"
    change_dir.mkdir(parents=True, exist_ok=True)
    (change_dir / "design.md").write_text(design_text, encoding="utf-8")


def _run_main(command: str, cwd: Path) -> tuple[int, dict | None]:
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(cwd),
        # no session_id -> within-session dedup is bypassed (matches Codex)
    }
    captured = io.StringIO()
    with patch("sys.stdin", io.StringIO(json.dumps(payload))):
        with patch("sys.stdout", captured):
            try:
                code = gate.main()
            except SystemExit as exc:
                code = exc.code or 0
    out = captured.getvalue().strip()
    return code, json.loads(out) if out else None


_DESIGN_WITH_PROOF = """# Design

## Proof of Delivery

The report shows accurate, correct revenue numbers to the user when run end-to-end.
"""

_DESIGN_CLEAN = """# Design

A plain design note with no proof-of-delivery, anti-metrics, or blocking
open questions. Nothing here should trigger a close-time prompt.
"""


def test_codex_close_asks_when_design_has_proof_of_delivery(tmp_path):
    """Negative control: a design with a Proof of Delivery surfaces an ask prompt.

    An implementation that always allows would pass the positive control but
    fail here.
    """
    _make_change(tmp_path, _DESIGN_WITH_PROOF)
    code, output = _run_main("bd close disco-1", cwd=tmp_path)

    assert code == 0
    assert output is not None, "a design with unresolved proof-of-delivery must surface a prompt"
    assert output["hookSpecificOutput"]["permissionDecision"] == "ask"
    reason = output["hookSpecificOutput"]["permissionDecisionReason"]
    assert "Proof of Delivery".lower() in reason.lower() or "verify" in reason.lower(), (
        f"the prompt must surface the proof-of-delivery question; got: {reason!r}"
    )


def test_codex_close_allowed_when_design_is_clean(tmp_path):
    """Positive control: a design with no unresolved prompts -> allow.

    Without this, an implementation that always asks would pass only the
    negative control.
    """
    _make_change(tmp_path, _DESIGN_CLEAN)
    code, output = _run_main("bd close disco-1", cwd=tmp_path)

    assert code == 0
    assert output is None, f"a clean design must allow the close silently; got: {output!r}"


def test_codex_close_allowed_when_no_design_present(tmp_path):
    """Fast-path: with no openspec change or design doc, there is nothing to gate."""
    code, output = _run_main("bd close disco-1", cwd=tmp_path)

    assert code == 0
    assert output is None, "a close with no design present must be allowed"


def test_codex_non_close_command_allowed(tmp_path):
    """Fast-path: a command that is not `bd close` is never gated."""
    _make_change(tmp_path, _DESIGN_WITH_PROOF)
    code, output = _run_main("bd update disco-1 --claim", cwd=tmp_path)

    assert code == 0
    assert output is None, "non-`bd close` commands must always be allowed"
