"""Behavioral tests for claude/hooks/no_direct_send_guard.py.

This hook protects one business outcome: a human reviews any Slack/email
message before it is actually sent. The mechanism is a two-part contract:

  1. The hook itself ALWAYS denies — it is only ever invoked on tool names
     that are on the block list (the matchers in settings.template.json). So
     the hook's own behavioral contract is: "deny, and redirect to the draft
     equivalent of the tool that was attempted."

  2. The DRAFT tools must NOT be wired to this hook in the settings template,
     so a draft send passes through untouched.

Both halves are tested here so neither can regress silently:

  Negative control — a registered direct-send tool is denied via the canonical
  single-mechanism contract (permissionDecision=deny JSON on stdout, exit 0 —
  NOT exit 2) and the denial names the *specific* draft tool to
  use instead. If the hook ever allowed a send through, messages would go out
  un-reviewed — the exact failure this gate exists to prevent.

  Positive control — the draft tools (slack_send_message_draft) are NOT
  matched by this hook in settings.template.json, so they reach the MCP
  server. We assert against the real settings registration, not the hook's
  internal table, so this control catches a regression where someone wires
  the guard onto the draft tool and accidentally blocks the allowed path.

The assertions target externally-observable behavior (exit code, the JSON
permission decision the runtime acts on, the settings registration) — not
private helpers or the internal hint table — so they are not implementation
echoes.

Run from anywhere:
  python3 -m pytest claude/hooks/tests/test_no_direct_send_guard.py -v
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_hooks_dir = Path(__file__).resolve().parent.parent
if str(_hooks_dir) not in sys.path:
    sys.path.insert(0, str(_hooks_dir))

import no_direct_send_guard as hook  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# The four direct-send tool names this guard is wired to deny. Sourced from
# the hook docstring / settings template — these are the tools that, if
# allowed through, would send a message with no human review.
_BLOCKED_SEND_TOOLS = (
    "mcp__plugin_slack_slack__slack_send_message",
    "mcp__plugin_slack_slack__slack_schedule_message",
    "mcp__claude_ai_Slack__slack_send_message",
    "mcp__claude_ai_Slack__slack_schedule_message",
)

_DRAFT_TOOLS = (
    "mcp__plugin_slack_slack__slack_send_message_draft",
    "mcp__claude_ai_Slack__slack_send_message_draft",
)

_SETTINGS_TEMPLATE = (
    Path(__file__).resolve().parents[2] / "claude" / "settings.template.json"
)
# When the tests run from the repo's claude/ tree, parents[2] may already be
# the repo root; resolve robustly by searching upward for the template.
if not _SETTINGS_TEMPLATE.is_file():
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "settings.template.json"
        if candidate.is_file():
            _SETTINGS_TEMPLATE = candidate
            break


def _run(tool_name: str) -> tuple[int, dict, str]:
    """Drive the hook's main() with a PreToolUse payload for ``tool_name``.

    Returns (exit_code, parsed_stdout_json). The hook signals a deny via the
    canonical mechanism: a permissionDecision="deny" JSON document on stdout
    plus exit 0 (NOT exit 2). We capture both the exit code and the raw stdout.
    """
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": {"channel": "C123", "text": "hello"},
    }
    stdout_capture = io.StringIO()
    exit_code = 0
    with (
        patch("sys.stdin", io.StringIO(json.dumps(payload))),
        patch("sys.stdout", stdout_capture),
        # Don't pollute the real signal store while driving the hook.
        patch.object(hook, "_record_signal", lambda *a, **k: None),
    ):
        try:
            ret = hook.main()
            exit_code = ret if ret is not None else 0
        except SystemExit as exc:
            exit_code = exc.code if isinstance(exc.code, int) else 1

    out = stdout_capture.getvalue().strip()
    parsed = json.loads(out) if out else {}
    return exit_code, parsed, out


# ---------------------------------------------------------------------------
# Negative control: every registered direct-send tool is denied + redirected.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("send_tool", _BLOCKED_SEND_TOOLS)
def test_direct_send_is_denied_and_redirected(send_tool):
    """A direct-send tool invocation must be DENIED via the canonical
    single-mechanism contract: a permissionDecision="deny" JSON document on
    stdout AND exit 0 (NOT exit 2). The deny must name a *draft* alternative.
    This is the whole point of the gate: no message leaves without a review
    step."""
    exit_code, parsed, raw_stdout = _run(send_tool)

    # Canonical deny mechanism: JSON decision carries the block; exit code is 0.
    assert exit_code == 0, (
        "deny is signaled by the stdout JSON decision, not exit 2 — a "
        "permissionDecision=deny plus exit 2 is a contradictory double-block"
    )
    out = parsed["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"

    # Honored EXACTLY ONCE: stdout carries a single JSON decision document
    # (one mechanism), not a decision plus a second redundant signal.
    assert raw_stdout.count('"permissionDecision"') == 1, (
        f"deny must be emitted exactly once; stdout was: {raw_stdout!r}"
    )

    reason = out["permissionDecisionReason"]
    # The redirect must point at a DRAFT tool, not just any prose. A draft
    # tool name ending in "_draft" is the externally-meaningful redirect that
    # makes the denial actionable (gate-design Rule 1: escape path in the
    # denial itself).
    assert "_draft" in reason, (
        f"denial must redirect to a draft tool; got: {reason!r}"
    )
    # And it must name the attempted tool so the user knows what was blocked.
    assert send_tool in reason


# ---------------------------------------------------------------------------
# Positive control: draft tools are NOT wired to this guard → they pass.
# ---------------------------------------------------------------------------

def test_draft_tools_are_not_blocked_by_settings():
    """The allowed path: draft send tools must NOT be matched by this guard
    in settings.template.json, so a draft reaches the MCP server unimpeded.

    We verify against the real settings registration (the source of truth for
    which tools the hook fires on), so this control bites if someone wires the
    guard onto a draft tool and breaks the only sanctioned way to send."""
    assert _SETTINGS_TEMPLATE.is_file(), (
        f"settings template not found at {_SETTINGS_TEMPLATE}"
    )
    settings = json.loads(_SETTINGS_TEMPLATE.read_text(encoding="utf-8"))

    matchers_guarded_by_hook = set()
    pre_tool_use = settings.get("hooks", {}).get("PreToolUse", [])
    for entry in pre_tool_use:
        matcher = entry.get("matcher", "")
        commands = [
            h.get("command", "") for h in entry.get("hooks", [])
        ]
        if any("no_direct_send_guard.py" in c for c in commands):
            matchers_guarded_by_hook.add(matcher)

    # Sanity: the guard is actually registered on the direct-send tools
    # (otherwise this whole "positive control" is vacuously true).
    assert matchers_guarded_by_hook, (
        "no_direct_send_guard.py is not registered on any matcher in the "
        "settings template — the gate is not actually wired up"
    )

    for draft_tool in _DRAFT_TOOLS:
        assert draft_tool not in matchers_guarded_by_hook, (
            f"draft tool {draft_tool} is wired to no_direct_send_guard — the "
            "allowed send path would be blocked"
        )


def test_malformed_stdin_fails_open():
    """Defensive: if stdin is not valid JSON the hook must fail OPEN (exit 0,
    no decision) rather than crashing — a logging/parse bug must not wedge the
    tool pipeline."""
    stdout_capture = io.StringIO()
    with (
        patch("sys.stdin", io.StringIO("not json{")),
        patch("sys.stdout", stdout_capture),
        patch.object(hook, "_record_signal", lambda *a, **k: None),
    ):
        ret = hook.main()

    assert ret == 0
    assert stdout_capture.getvalue().strip() == ""
