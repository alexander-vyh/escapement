"""Behavioral tests for claude/hooks/root_checkout_guard.py.

The oracle is repo shape, not path strings: a primary checkout has `.git/` and
`.beads/`; a linked worktree has `.git` as a file and must be allowed.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


_HOOK_PATH = Path(__file__).resolve().parents[1] / "root_checkout_guard.py"
if not _HOOK_PATH.exists():
    pytest.fail(f"root_checkout_guard.py not found at {_HOOK_PATH}")

_spec = importlib.util.spec_from_file_location("root_checkout_guard", _HOOK_PATH)
guard = importlib.util.module_from_spec(_spec)
sys.modules["root_checkout_guard"] = guard
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


def _write_payload(path: Path, *, cwd: Path, tool_name: str = "Write") -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": {"file_path": str(path), "content": "changed\n"},
        "cwd": str(cwd),
    }


def _bash_payload(command: str, *, cwd: Path) -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(cwd),
    }


def _decision(output: dict) -> str | None:
    return output.get("hookSpecificOutput", {}).get("permissionDecision")


def _reason(output: dict) -> str:
    return output["hookSpecificOutput"]["permissionDecisionReason"]


def _make_primary_beads_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / ".beads").mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("print('old')\n", encoding="utf-8")
    return repo


def _make_linked_worktree(tmp_path: Path) -> tuple[Path, Path]:
    main = tmp_path / "main"
    (main / ".git" / "worktrees" / "wt").mkdir(parents=True)
    (main / ".beads").mkdir()
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / ".git").write_text(f"gitdir: {main}/.git/worktrees/wt\n", encoding="utf-8")
    (worktree / ".beads").mkdir()
    (worktree / ".beads" / "redirect").write_text(str(main / ".beads"), encoding="utf-8")
    (worktree / "src").mkdir()
    (worktree / "src" / "app.py").write_text("print('old')\n", encoding="utf-8")
    return main, worktree


def test_write_to_primary_checkout_file_is_denied(tmp_path):
    repo = _make_primary_beads_repo(tmp_path)

    code, output, raw = _run_payload(_write_payload(repo / "src" / "app.py", cwd=repo))

    assert code == 0
    assert _decision(output) == "deny", raw
    reason = _reason(output)
    assert "primary checkout" in reason
    assert "bd worktree create" in reason
    assert "# root-checkout-waiver:" in reason


@pytest.mark.parametrize("tool_name", ["Write", "Edit", "NotebookEdit"])
def test_write_to_primary_checkout_denied_when_cwd_outside_repo(tmp_path, tool_name):
    repo = _make_primary_beads_repo(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    payload = _write_payload(repo / "src" / "app.py", cwd=outside, tool_name=tool_name)
    payload["tool_input"]["old_string"] = "old"
    payload["tool_input"]["new_string"] = "new"

    code, output, raw = _run_payload(payload)

    assert code == 0
    assert _decision(output) == "deny", raw


def test_write_to_linked_worktree_is_allowed(tmp_path):
    _main, worktree = _make_linked_worktree(tmp_path)

    code, output, raw = _run_payload(_write_payload(worktree / "src" / "app.py", cwd=worktree))

    assert code == 0
    assert output == {}, f"linked worktree writes must pass untouched; got {raw!r}"


def test_state_changing_git_in_primary_checkout_is_denied(tmp_path):
    repo = _make_primary_beads_repo(tmp_path)

    code, output, raw = _run_payload(_bash_payload("git checkout -b feature/root-mess", cwd=repo))

    assert code == 0
    assert _decision(output) == "deny", raw
    assert "git checkout" in _reason(output)


def test_codex_root_checkout_guard_denies_primary_checkout_bash(tmp_path):
    repo = _make_primary_beads_repo(tmp_path)

    code, output, raw = _run_payload(_bash_payload("git pull --ff-only", cwd=repo))

    assert code == 0
    assert _decision(output) == "deny", raw


def test_codex_root_checkout_guard_denies_primary_checkout_write(tmp_path):
    repo = _make_primary_beads_repo(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()

    code, output, raw = _run_payload(_write_payload(repo / "src" / "app.py", cwd=outside))

    assert code == 0
    assert _decision(output) == "deny", raw


def test_primary_checkout_denial_records_signal(tmp_path):
    repo = _make_primary_beads_repo(tmp_path)
    calls: list[dict] = []
    payload = _bash_payload("git checkout -b feature/root-mess", cwd=repo)
    stdout = io.StringIO()

    with (
        patch("sys.stdin", io.StringIO(json.dumps(payload))),
        patch("sys.stdout", stdout),
        patch.object(guard, "_record_signal", lambda **kwargs: calls.append(kwargs)),
    ):
        try:
            code = guard.main()
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1

    assert code == 0
    assert calls, "root-checkout denials must persist signal"
    assert calls[0]["decision"] == "deny"
    assert calls[0]["gate_name"] == "root_checkout_guard"
    assert "primary checkout" in calls[0]["reason"]
    assert calls[0]["tool"] == "Bash"
    assert str(repo) in calls[0]["target"]


def test_state_changing_git_via_dash_c_to_primary_checkout_is_denied(tmp_path):
    repo = _make_primary_beads_repo(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()

    code, output, raw = _run_payload(_bash_payload(f"git -C {repo} pull --ff-only", cwd=outside))

    assert code == 0
    assert _decision(output) == "deny", raw


@pytest.mark.parametrize("command", ["git status --short", "git log --oneline -5", "git diff -- src/app.py", "rg root_checkout_guard claude/hooks"])
def test_readonly_commands_in_primary_checkout_are_allowed(tmp_path, command):
    repo = _make_primary_beads_repo(tmp_path)

    code, output, raw = _run_payload(_bash_payload(command, cwd=repo))

    assert code == 0
    assert output == {}, f"read-only command must pass untouched; got {raw!r}"


def test_state_changing_git_in_linked_worktree_is_allowed_by_root_guard(tmp_path):
    _main, worktree = _make_linked_worktree(tmp_path)

    code, output, raw = _run_payload(_bash_payload("git checkout -b feature/wt", cwd=worktree))

    assert code == 0
    assert output == {}, f"linked worktree git mutation is not a root-checkout violation; got {raw!r}"


@pytest.mark.parametrize("reason", ["tbd", "n/a", "todo", "<reason>", "short"])
def test_placeholder_waiver_does_not_allow(tmp_path, reason):
    repo = _make_primary_beads_repo(tmp_path)
    command = f"git checkout -b maintenance/root # root-checkout-waiver: {reason}"

    code, output, raw = _run_payload(_bash_payload(command, cwd=repo))

    assert code == 0
    assert _decision(output) == "deny", raw


def test_substantive_waiver_allows_and_records_reason(tmp_path):
    repo = _make_primary_beads_repo(tmp_path)
    calls: list[dict] = []
    command = "git checkout -b maintenance/root # root-checkout-waiver: intentional root metadata maintenance"
    payload = _bash_payload(command, cwd=repo)
    stdout = io.StringIO()

    with (
        patch("sys.stdin", io.StringIO(json.dumps(payload))),
        patch("sys.stdout", stdout),
        patch.object(guard, "_record_signal", lambda **kwargs: calls.append(kwargs)),
    ):
        code = guard.main()

    assert code == 0
    assert stdout.getvalue().strip() == ""
    assert calls[0]["decision"] == "waiver-accepted"
    assert calls[0]["event_type"] == "waiver"
    assert "intentional root metadata maintenance" in calls[0]["reason"]


@pytest.mark.parametrize("git_file_content", ["not a gitdir marker\n", "gitdir: /path/that/does/not/exist\n", "gitdir:\n"])
def test_malformed_linked_worktree_shape_fails_open(tmp_path, git_file_content):
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / ".git").write_text(git_file_content, encoding="utf-8")
    (worktree / ".beads").mkdir()
    (worktree / ".beads" / "redirect").write_text("/missing/main/.beads", encoding="utf-8")

    code, output, raw = _run_payload(_bash_payload("git checkout -b feature/x", cwd=worktree))

    assert code == 0
    assert output == {}, f"uncertain linked-worktree state must fail open; got {raw!r}"


def test_non_beads_git_repo_is_allowed(tmp_path):
    repo = tmp_path / "plain"
    repo.mkdir()
    (repo / ".git").mkdir()

    code, output, raw = _run_payload(_bash_payload("git checkout -b feature/plain", cwd=repo))

    assert code == 0
    assert output == {}, f"plain git repos are outside the root-checkout guard; got {raw!r}"


def test_missing_or_malformed_payload_fails_open():
    code, output, raw = _run_payload({"hook_event_name": "PreToolUse", "tool_name": "Write"})

    assert code == 0
    assert output == {}, f"malformed payload must fail open; got {raw!r}"
