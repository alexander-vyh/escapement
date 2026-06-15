"""Codex-specific behavioral tests for discovery-gate.py.

These tests load the hook from the repo path so they run in Codex environments
that do not have ~/.claude/hooks/. They exercise the hook's public main()
interface with realistic JSON payloads, using cwd to point to a tmp filesystem
fixture.

Positive control: a `bd create -t feature` command is ALLOWED when a valid
design doc with all three required sections exists at
openspec/changes/{name}/design.md.

Negative control: the same command is DENIED when no design doc exists —
proving the gate enforces discovery before feature creation, not just any doc.

Bypass: `bd create -t bug` is always ALLOWED regardless of design docs.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_HOOK_PATH = Path(__file__).resolve().parents[1] / "discovery-gate.py"
if not _HOOK_PATH.exists():
    pytest.fail(f"discovery-gate.py not found at {_HOOK_PATH} — cannot run Codex tests")

_spec = importlib.util.spec_from_file_location("discovery_gate", _HOOK_PATH)
gate = importlib.util.module_from_spec(_spec)
sys.modules["discovery_gate"] = gate
_spec.loader.exec_module(gate)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

COMPLETE_DESIGN = """\
# Design - my-feature

## Problem Statement
Users cannot schedule recurring tasks without manual daily setup.

## Non-Goals
Mobile push notifications are out of scope.

## Riskiest Assumption
Users are willing to grant calendar access.
"""


def _make_design_doc(tmp_path: Path, name: str = "my-feature", content: str = COMPLETE_DESIGN) -> Path:
    doc_dir = tmp_path / "openspec" / "changes" / name
    doc_dir.mkdir(parents=True)
    doc = doc_dir / "design.md"
    doc.write_text(content, encoding="utf-8")
    return doc


def _run_main(payload: dict) -> tuple[int, dict | None]:
    captured = io.StringIO()
    code = 0
    with patch("sys.stdin", io.StringIO(json.dumps(payload))):
        with patch("sys.stdout", captured):
            try:
                code = gate.main()
            except SystemExit as exc:
                code = exc.code or 0
    out = captured.getvalue().strip()
    return code, json.loads(out) if out else None


def _payload(command: str, cwd: str) -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "cwd": cwd,
        "tool_input": {"command": command},
    }


# ---------------------------------------------------------------------------
# Codex-specific behavioral tests
# ---------------------------------------------------------------------------


def test_codex_feature_create_blocked_without_design_doc(tmp_path):
    """Negative control: bd create -t feature with no design doc → deny.

    Proves the gate actually enforces discovery. An implementation that always
    allows would pass the positive control but fail this test.
    """
    payload = _payload("bd create 'add recurring tasks' -t feature", str(tmp_path))
    code, output = _run_main(payload)

    assert code == 0, "deny is signaled by stdout JSON, not a non-zero exit"
    assert output is not None, "gate must emit a JSON decision when blocking"
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
    reason = output["hookSpecificOutput"]["permissionDecisionReason"]
    assert "design" in reason.lower() or "openspec" in reason.lower(), (
        f"denial must explain the missing design doc requirement; got: {reason!r}"
    )


def test_codex_feature_create_allowed_with_valid_design_doc(tmp_path):
    """Positive control: bd create -t feature WITH all three required sections → allow.

    Proves valid discovery docs are not falsely blocked. Without this, an
    implementation that always denies would pass only the negative control.
    """
    _make_design_doc(tmp_path)
    payload = _payload("bd create 'add recurring tasks' -t feature", str(tmp_path))
    code, output = _run_main(payload)

    assert code == 0
    assert output is None, (
        f"a valid design doc must allow without any JSON output; got: {output!r}"
    )


def test_codex_bug_create_bypasses_gate(tmp_path):
    """Bypass: bug creates always pass, no design doc required.

    Proves the gate does not over-reach into bug/chore workflow.
    """
    payload = _payload("bd create 'fix null pointer' -t bug", str(tmp_path))
    code, output = _run_main(payload)

    assert code == 0
    assert output is None, "bug creates must be allowed without a design doc"


def test_codex_incomplete_design_doc_asks_not_denies(tmp_path):
    """Partial design doc (missing sections) results in ask, not silent allow.

    A design doc that exists but lacks required sections should surface the gap —
    an empty file must not masquerade as passing discovery.
    """
    _make_design_doc(tmp_path, content="## Problem Statement\nOnly one section.\n")
    payload = _payload("bd create 'add recurring tasks' -t feature", str(tmp_path))
    code, output = _run_main(payload)

    assert code == 0
    # Hook must signal something (ask or deny) rather than silently allowing
    assert output is not None, (
        "a partial design doc must not silently allow — the gate must surface the gap"
    )


def test_codex_non_pretooluse_is_allowed(tmp_path):
    """Fast-path: non-PreToolUse events pass unconditionally."""
    payload = {
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "cwd": str(tmp_path),
        "tool_input": {"command": "bd create 'x' -t feature"},
    }
    code, output = _run_main(payload)

    assert code == 0
    assert output is None
