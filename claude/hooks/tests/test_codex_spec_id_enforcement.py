"""Codex-specific behavioral tests for spec_id_enforcement.py.

Loads from the repo path (no ~/.claude/hooks/ dependency) so these run in
Codex environments. The bd subprocess boundary (is_mol_feature_parent) is
patched so tests are hermetic.

The hook fires as PreToolUse on `bd create` when the command has --parent
pointing to a mol-feature molecule and --spec-id is missing.

Positive control: `bd create` WITH --spec-id under mol-feature → allow.
Negative control: `bd create` under mol-feature WITHOUT --spec-id → deny.
Fast-path: `bd create` without --parent is always allowed (standalone creates).
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_HOOK_PATH = Path(__file__).resolve().parents[1] / "spec_id_enforcement.py"
if not _HOOK_PATH.exists():
    pytest.fail(f"spec_id_enforcement.py not found at {_HOOK_PATH}")

_spec = importlib.util.spec_from_file_location("spec_id_enforcement", _HOOK_PATH)
gate = importlib.util.module_from_spec(_spec)
sys.modules["spec_id_enforcement"] = gate
_spec.loader.exec_module(gate)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_main(
    command: str,
    is_mol_feature: bool = False,
    spec_valid: bool = True,
) -> tuple[int, dict | None]:
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }
    captured = io.StringIO()
    # validate_spec_id resolves file paths on disk; patch it so tests are
    # hermetic and do not depend on the openspec directory being present.
    _spec_result = (True, "") if spec_valid else (False, "spec path does not resolve")
    with patch("sys.stdin", io.StringIO(json.dumps(payload))):
        with patch("spec_id_enforcement.is_mol_feature_parent", return_value=is_mol_feature):
            with patch("spec_id_enforcement.validate_spec_id", return_value=_spec_result):
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


# ---------------------------------------------------------------------------
# Codex-specific behavioral tests
# ---------------------------------------------------------------------------


def test_codex_bd_create_without_parent_allowed():
    """Fast-path: standalone bd create (no --parent) is never gated.

    Proves the gate only enforces spec-id discipline on molecule-parented tasks,
    not on ad-hoc creates.
    """
    code, output = _run_main("bd create 'explore the API'", is_mol_feature=False)

    assert code == 0
    assert output is None, "standalone creates (no --parent) must always be allowed"


def test_codex_bd_create_with_spec_id_allowed():
    """Positive control: bd create with --spec-id under mol-feature → allow.

    Proves the gate allows correctly-formed creates. Without this, an
    implementation that always denies would pass only the negative control.
    """
    cmd = "bd create 'implement login' --parent bd-mol-123 --spec-id openspec/changes/auth/specs/auth.md#Login"
    code, output = _run_main(cmd, is_mol_feature=True)

    assert code == 0
    assert output is None, (
        f"a bd create with --spec-id under mol-feature must be allowed; got: {output!r}"
    )


def test_codex_bd_create_missing_spec_id_under_mol_feature_denied():
    """Negative control: bd create under mol-feature WITHOUT --spec-id → deny.

    This is the gate's core contract: work-breakdown tasks in a mol-feature
    molecule must carry spec-id backlinks for referential integrity. An
    implementation that always allows would pass the positive control but fail here.
    """
    cmd = "bd create 'implement login' --parent bd-mol-123"
    code, output = _run_main(cmd, is_mol_feature=True)

    assert_denied(code, output)
    reason = output["hookSpecificOutput"]["permissionDecisionReason"]
    assert "--spec-id" in reason, f"denial must name the missing flag; got: {reason!r}"
    assert "mol-feature" in reason, f"denial must explain why; got: {reason!r}"


def test_codex_bd_create_non_mol_feature_parent_allowed():
    """Fast-path: parent exists but is not a mol-feature molecule → allow.

    Proves the gate only fires on mol-feature molecules, not on all epics.
    """
    cmd = "bd create 'fix styling' --parent bd-chore-456"
    code, output = _run_main(cmd, is_mol_feature=False)

    assert code == 0
    assert output is None


def test_codex_spec_id_denial_single_mechanism():
    """Contract: deny is signaled by ONE JSON document AND exit 0 — never exit 2.

    A permissionDecision=deny plus non-zero exit is a contradictory double-signal.
    json.loads raises on stacked documents, rejecting doubled output.
    """
    cmd = "bd create 'implement login' --parent bd-mol-123"
    code, output = _run_main(cmd, is_mol_feature=True)

    assert code == 0, "deny must be exit 0 with JSON on stdout, not exit 2"
    assert output is not None
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
