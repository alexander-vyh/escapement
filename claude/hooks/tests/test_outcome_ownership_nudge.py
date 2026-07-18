"""Behavioral tests for claude/hooks/outcome_ownership_nudge.py.

The oracle: at a PR-ship command the hook must (1) inject the OPERATIVE outcome-ownership
lines — the ones the cake session ignored ("pre-existing" is not an excuse; you are the
follow-up) — as non-blocking additionalContext, and (2) NEVER block. Off the ship
boundary (and specifically on `git push`, excluded by design) it must be silent. The
tests reject a weak implementation that emits a generic non-empty reminder or that could
deny an action: they assert the specific doctrine content and the absence of any
permissionDecision.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_HOOK_PATH = Path(__file__).resolve().parents[1] / "outcome_ownership_nudge.py"
if not _HOOK_PATH.exists():
    pytest.fail(f"outcome_ownership_nudge.py not found at {_HOOK_PATH}")

_spec = importlib.util.spec_from_file_location("outcome_ownership_nudge", _HOOK_PATH)
hook = importlib.util.module_from_spec(_spec)
sys.modules["outcome_ownership_nudge"] = hook
assert _spec.loader is not None
_spec.loader.exec_module(hook)


def _run(command: str) -> tuple[int, dict, str]:
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }
    stdout = io.StringIO()
    with patch("sys.stdin", io.StringIO(json.dumps(payload))), patch("sys.stdout", stdout):
        try:
            code = hook.main()
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
    raw = stdout.getvalue().strip()
    return code or 0, (json.loads(raw) if raw else {}), raw


def _additional_context(out: dict) -> str:
    return out.get("hookSpecificOutput", {}).get("additionalContext", "")


# --- fires on the ship boundary --------------------------------------------------------

def test_fires_on_pr_create():
    code, out, _ = _run("gh pr create --base main --head feat --title X --body-file /tmp/b")
    assert code == 0
    assert out["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
    assert _additional_context(out), "expected an outcome-ownership nudge on gh pr create"


def test_fires_on_pr_merge_including_auto():
    code, out, _ = _run("gh pr merge 1750 --auto --squash")
    assert code == 0
    assert _additional_context(out)


@pytest.mark.parametrize(
    "command",
    [
        "cd /repo/wt && gh pr merge 1750 --auto --squash",           # && compound
        "cd /repo/wt\ngh pr merge 1750 --auto --squash",             # NEWLINE compound — the exact cake-incident shape
        "GH_TOKEN=ghp_x gh pr merge 262 --squash",                   # inline-auth env prefix
        "time gh pr merge 262 --squash",                             # wrapper prefix
        "sudo gh pr merge 262",                                      # wrapper prefix
        "(gh pr merge 262)",                                         # subshell
        "echo start; gh pr create --title X",                        # ; separator
        "gh   pr    merge   262",                                    # extra whitespace
    ],
)
def test_fires_on_real_ship_shapes_that_evade_a_leading_anchor(command):
    # Regression for reviewer findings #1/#2: a leading-anchor regex (^|[;&|]) silently
    # missed every one of these — including the newline-compound cake shape the hook
    # exists to catch. Token-bounded matching fires on all of them.
    code, out, _ = _run(command)
    assert code == 0, command
    assert _additional_context(out), f"expected a nudge on real ship shape: {command!r}"


# --- the content IS the operative doctrine (rejects a weak generic reminder) ------------

def test_content_names_the_ignored_doctrine():
    _, out, _ = _run("gh pr create --title X")
    ctx = _additional_context(out).lower()
    # The precise excuses the cake agent used, and the ownership rule it violated.
    assert "pre-existing" in ctx
    assert "orthogonal" in ctx
    assert "follow-up" in ctx  # "you are the follow-up" — no handoff to the user
    assert "hand it off" in ctx or "handoff" in ctx or "hand off" in ctx


# --- never blocks (advisory only) ------------------------------------------------------

def test_never_blocks_on_ship():
    _, out, raw = _run("gh pr merge 1750 --auto")
    # Advisory: no permissionDecision anywhere in the payload.
    assert "permissionDecision" not in raw
    assert "deny" not in raw.lower()


# --- silent off the ship boundary ------------------------------------------------------

def test_silent_on_unrelated_bash():
    code, out, raw = _run("git status && ls")
    assert code == 0
    assert raw == "", f"expected no output on unrelated Bash, got: {raw!r}"


def test_silent_on_git_push_by_design():
    # git push is deliberately EXCLUDED: agents push constantly and a per-push nudge
    # becomes wallpaper. This asserts that design decision, not an accident.
    code, out, raw = _run("git push --force-with-lease origin feat")
    assert code == 0
    assert raw == "", f"git push must not nudge (wallpaper avoidance), got: {raw!r}"


def test_pr_substring_in_other_context_does_not_fire():
    # "gh pr view" / "gh pr list" are inspection, not delivery declarations.
    for cmd in ("gh pr view 1750 --json state", "gh pr checks 1750", "gh pr list"):
        code, out, raw = _run(cmd)
        assert code == 0
        assert raw == "", f"{cmd!r} should not nudge, got: {raw!r}"


def test_accepted_false_positive_on_echoed_literal_is_intentional():
    # A `gh pr create` literal inside a quoted echo string DOES fire — the hook does not
    # parse shell. This is a DELIBERATE trade: token-matching catches every real ship
    # shape (incl. newline-compound) at the cost of occasional noise on echoed literals.
    # Since the hook is advisory-only, the cost is one paragraph, never a block. This test
    # pins the trade so suppressing it later is a conscious decision, not drift.
    code, out, raw = _run('echo "reminder: run gh pr create when ready"')
    assert code == 0
    assert _additional_context(out)  # fires — accepted, bounded to advisory noise


# --- robustness ------------------------------------------------------------------------

def test_malformed_stdin_is_silent():
    stdout = io.StringIO()
    with patch("sys.stdin", io.StringIO("not json")), patch("sys.stdout", stdout):
        code = hook.main()
    assert code == 0
    assert stdout.getvalue().strip() == ""


# --- codex-specific wiring -------------------------------------------------------------
# Codex has no argument-scoped matcher support, so it wires this same script to a broad
# `Bash` matcher and relies on the script's own `_is_ship_command` filter — the same
# split-of-responsibility the merge-authorization gate uses. These fixtures prove the
# self-filtering holds under codex's broad matcher.

def test_codex_outcome_ownership_nudge_fires_on_ship():
    code, out, _ = _run("gh pr merge 262 --squash")
    assert code == 0
    assert _additional_context(out)


def test_codex_outcome_ownership_nudge_silent_off_ship():
    # Broad Bash matcher hands every command to the script; it must self-filter to silence
    # on non-ship commands (incl. git push, excluded by design).
    for cmd in ("git status", "git push origin feat", "gh pr view 262"):
        code, out, raw = _run(cmd)
        assert code == 0
        assert raw == "", f"{cmd!r} should be silent under codex broad matcher, got: {raw!r}"
