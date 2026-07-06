"""Behavioral tests for claude/hooks/merge_authorization_gate.py.

The oracle is the repo's real `.escapement/repo.json` declaration, resolved by the
real `repo_outcome.py` (not mocked) — a fixture repo IS the independent source of
truth here, exactly as it is for the Stop-gate backstop's own tests. The gate is
correct if, and only if, its allow/deny verdict matches what repo_outcome.resolve()
would say for that fixture, and the deny reason always names the true cause (missing
declaration) rather than any fabricated external constraint — the defect a real
incident (2026-07-04, PR #262) exposed.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_HOOK_PATH = Path(__file__).resolve().parents[1] / "merge_authorization_gate.py"
if not _HOOK_PATH.exists():
    pytest.fail(f"merge_authorization_gate.py not found at {_HOOK_PATH}")

_spec = importlib.util.spec_from_file_location("merge_authorization_gate", _HOOK_PATH)
guard = importlib.util.module_from_spec(_spec)
sys.modules["merge_authorization_gate"] = guard
assert _spec.loader is not None
_spec.loader.exec_module(guard)


def _run_payload(payload: dict) -> tuple[int, dict, str]:
    stdout = io.StringIO()
    with (
        patch("sys.stdin", io.StringIO(json.dumps(payload))),
        patch("sys.stdout", stdout),
        patch.object(guard, "_record_signal", lambda *a, **k: None),
    ):
        try:
            code = guard.main()
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
    raw = stdout.getvalue().strip()
    return code or 0, json.loads(raw) if raw else {}, raw


def _bash_payload(command: str, *, cwd: Path) -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(cwd),
    }


def _decision(result: dict) -> str | None:
    return result.get("hookSpecificOutput", {}).get("permissionDecision")


def _reason(result: dict) -> str:
    return result.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")


def _write_declaration(repo: Path, declaration: dict | str) -> None:
    (repo / ".escapement").mkdir(parents=True, exist_ok=True)
    text = declaration if isinstance(declaration, str) else json.dumps(declaration)
    (repo / ".escapement" / "repo.json").write_text(text, encoding="utf-8")


def test_unconfigured_repo_denies_merge_with_honest_reason(tmp_path: Path) -> None:
    code, result, raw = _run_payload(_bash_payload("gh pr merge 262 --squash", cwd=tmp_path))
    assert code == 0
    assert _decision(result) == "deny"
    reason = _reason(result)
    assert ".escapement/repo.json" in reason
    assert "no platform-level restriction" in reason
    assert "escapement's own conservative default" in reason


def test_authorized_repo_allows_merge_silently(tmp_path: Path) -> None:
    _write_declaration(
        tmp_path, {"intended_outcome": "merged-and-deployed", "auto_merge_on_green": True}
    )
    code, result, raw = _run_payload(_bash_payload("gh pr merge 262 --squash", cwd=tmp_path))
    assert code == 0
    assert raw == ""  # no output at all == default allow, no permissionDecision block
    assert result == {}


def test_declared_no_auto_merge_still_denies(tmp_path: Path) -> None:
    _write_declaration(tmp_path, {"intended_outcome": "pr-opened", "auto_merge_on_green": False})
    code, result, _raw = _run_payload(_bash_payload("gh pr merge 262 --squash", cwd=tmp_path))
    assert _decision(result) == "deny"


def test_malformed_declaration_denies_conservatively(tmp_path: Path) -> None:
    _write_declaration(tmp_path, "{not valid json")
    code, result, _raw = _run_payload(_bash_payload("gh pr merge 262 --squash", cwd=tmp_path))
    assert _decision(result) == "deny"


def test_substantive_waiver_allows_even_when_unauthorized(tmp_path: Path) -> None:
    command = (
        "gh pr merge 262 --squash  "
        "# merge-authorization-waiver: user explicitly confirmed merge in chat this turn"
    )
    code, result, raw = _run_payload(_bash_payload(command, cwd=tmp_path))
    assert code == 0
    assert raw == ""


def test_placeholder_waiver_does_not_allow(tmp_path: Path) -> None:
    command = "gh pr merge 262 --squash  # merge-authorization-waiver: tbd"
    code, result, _raw = _run_payload(_bash_payload(command, cwd=tmp_path))
    assert _decision(result) == "deny"


def test_non_merge_bash_command_is_ignored(tmp_path: Path) -> None:
    for command in ["gh pr create --title x", "gh pr merge-conflict-report", "git status"]:
        code, result, raw = _run_payload(_bash_payload(command, cwd=tmp_path))
        assert code == 0
        assert raw == "", f"unexpected output for {command!r}: {raw}"


def test_non_bash_tool_is_ignored(tmp_path: Path) -> None:
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Write",
        "tool_input": {"file_path": str(tmp_path / "f.txt"), "content": "x"},
        "cwd": str(tmp_path),
    }
    code, result, raw = _run_payload(payload)
    assert code == 0
    assert raw == ""


def test_missing_or_malformed_payload_fails_open() -> None:
    stdout = io.StringIO()
    with patch("sys.stdin", io.StringIO("not json")), patch("sys.stdout", stdout):
        code = guard.main()
    assert code == 0
    assert stdout.getvalue().strip() == ""


def test_resolver_unavailable_denies_not_allows(tmp_path: Path) -> None:
    """If repo_outcome can't even be imported, the gate must deny — never fabricate
    an allow from an unresolvable check (mirrors repo_outcome.py's own fail-safe)."""
    with patch.dict(sys.modules, {"repo_outcome": None}):
        assert guard._authorizes_auto_merge(str(tmp_path)) is None
        code, result, _raw = _run_payload(_bash_payload("gh pr merge 262 --squash", cwd=tmp_path))
        assert _decision(result) == "deny"


def test_merge_command_embedded_after_shell_separator_is_detected(tmp_path: Path) -> None:
    code, result, _raw = _run_payload(
        _bash_payload("echo done && gh pr merge 262 --squash", cwd=tmp_path)
    )
    assert _decision(result) == "deny"  # unconfigured repo — still no fabricated allow


def test_codex_merge_authorization_gate_denies_unconfigured_repo(tmp_path: Path) -> None:
    """Codex wires this same script to a broad `Bash` matcher (no argument-scoped
    matcher support) — the script's own `_is_merge_command` filter does the work
    the matcher does for Claude Code. Same payload schema, same script, same test
    harness as the Claude-side tests above."""
    code, result, _raw = _run_payload(_bash_payload("gh pr merge 262 --squash", cwd=tmp_path))
    assert code == 0
    assert _decision(result) == "deny"


def test_codex_merge_authorization_gate_allows_authorized_repo(tmp_path: Path) -> None:
    _write_declaration(
        tmp_path, {"intended_outcome": "merged", "auto_merge_on_green": True}
    )
    code, result, raw = _run_payload(_bash_payload("gh pr merge 262 --squash", cwd=tmp_path))
    assert code == 0
    assert raw == ""
