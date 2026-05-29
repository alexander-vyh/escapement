"""Unit tests for ~/.claude/hooks/enforce_named_agents.py.

Tests:
- Non-Agent tools pass through
- Agent with name + team_name → allowed
- Agent without name → hard block (exit 2, deny)
- First agent without team_name → soft nudge (systemMessage)
- Second+ agent without team_name within window → hard block
- Tracker file is per-session and cleaned up by stale-check

Run from anywhere with:
  python -m pytest ~/.claude/hooks/tests/test_enforce_named_agents.py -v
"""

import io
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

_hooks_dir = Path.home() / ".claude" / "hooks"
if not _hooks_dir.exists():
    pytest.skip("~/.claude/hooks/ not found", allow_module_level=True)

if str(_hooks_dir) not in sys.path:
    sys.path.insert(0, str(_hooks_dir))

import enforce_named_agents as hook


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_SESSION = "test-session-99999"


def _run(name: str | None, team_name: str | None) -> tuple[int, dict]:
    """Run main() for an Agent PreToolUse call.

    Returns (exit_code, parsed_stdout_json).
    exit_code 0 = allow/nudge, 2 = hard block.
    """
    tool_input: dict = {}
    if name is not None:
        tool_input["name"] = name
    if team_name is not None:
        tool_input["team_name"] = team_name

    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Agent",
        "tool_input": tool_input,
    }

    stdout_capture = io.StringIO()
    exit_code = 0
    with (
        patch("sys.stdin", io.StringIO(json.dumps(payload))),
        patch("sys.stdout", stdout_capture),
        patch("enforce_named_agents._get_session_id", return_value=_FAKE_SESSION),
    ):
        try:
            # hook uses `return 2` (not sys.exit) for hard blocks
            result = hook.main()
            exit_code = result if result is not None else 0
        except SystemExit as exc:
            exit_code = exc.code or 0

    out = stdout_capture.getvalue().strip()
    data = json.loads(out) if out else {}
    return exit_code, data


@pytest.fixture(autouse=True)
def clean_tracker(monkeypatch):
    """Hermetic per-test env.

    - Ensure the tracker state dir EXISTS (a fresh $HOME, e.g. CI, has none — the
      stale-tracker tests write a tracker file directly).
    - Remove the fake-session tracker file before and after each test.
    - Neutralize ambient CI: CI runners set CI=true, which would trigger the
      hook's _is_ci_without_session stand-down and make the blocking tests see
      exit 0 instead of 2. Tests that exercise CI detection set CI explicitly via
      patch.dict, which overrides this delenv during their own body.
    """
    state_dir = Path.home() / ".claude" / "hooks" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    track = state_dir / f"agent-team-tracker-{_FAKE_SESSION}"
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    track.unlink(missing_ok=True)
    yield
    track.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Non-Agent tools
# ---------------------------------------------------------------------------

class TestNonAgentTools:
    def test_bash_passes_through(self):
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
                   "tool_input": {"command": "ls"}}
        with patch("sys.stdin", io.StringIO(json.dumps(payload))):
            result = hook.main()
        assert result == 0

    def test_write_passes_through(self):
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Write",
                   "tool_input": {"file_path": "/tmp/x.py", "content": ""}}
        with patch("sys.stdin", io.StringIO(json.dumps(payload))):
            result = hook.main()
        assert result == 0

    def test_invalid_json_passes_through(self):
        with patch("sys.stdin", io.StringIO("not json")):
            result = hook.main()
        assert result == 0


# ---------------------------------------------------------------------------
# Named agent on a team → always allowed
# ---------------------------------------------------------------------------

class TestNamedAgentOnTeam:
    def test_name_and_team_allowed(self):
        exit_code, output = _run(name="researcher", team_name="analysis")
        assert exit_code == 0
        assert output == {}  # no output = clean allow

    def test_different_names_and_teams_allowed(self):
        exit_code, _ = _run(name="qa-tester", team_name="feature-x")
        assert exit_code == 0


# ---------------------------------------------------------------------------
# Missing name → hard block
# ---------------------------------------------------------------------------

class TestMissingName:
    def test_no_name_hard_blocked(self):
        exit_code, output = _run(name=None, team_name="my-team")
        assert exit_code == 2

    def test_empty_name_hard_blocked(self):
        exit_code, output = _run(name="", team_name="my-team")
        assert exit_code == 2

    def test_block_output_is_deny(self):
        _, output = _run(name=None, team_name="my-team")
        decision = output["hookSpecificOutput"]["permissionDecision"]
        assert decision == "deny"

    def test_block_message_mentions_name(self):
        _, output = _run(name=None, team_name="my-team")
        reason = output["hookSpecificOutput"]["permissionDecisionReason"]
        assert "name" in reason.lower()

    def test_no_name_blocked_even_with_team(self):
        exit_code, _ = _run(name=None, team_name="some-team")
        assert exit_code == 2


# ---------------------------------------------------------------------------
# Missing team_name — first dispatch: soft nudge
# ---------------------------------------------------------------------------

class TestFirstTeamlessDispatch:
    def test_first_teamless_is_nudge_not_block(self):
        exit_code, output = _run(name="explorer", team_name=None)
        assert exit_code == 0  # not a hard block

    def test_first_teamless_emits_system_message(self):
        _, output = _run(name="explorer", team_name=None)
        assert "systemMessage" in output

    def test_nudge_message_mentions_team_create(self):
        _, output = _run(name="explorer", team_name=None)
        assert "TeamCreate" in output["systemMessage"]

    def test_nudge_mentions_agent_name(self):
        _, output = _run(name="my-explorer", team_name=None)
        assert "my-explorer" in output["systemMessage"]


# ---------------------------------------------------------------------------
# Missing team_name — second dispatch within window: hard block
# ---------------------------------------------------------------------------

class TestSecondTeamlessDispatch:
    def test_second_teamless_within_window_is_blocked(self):
        _run(name="agent-1", team_name=None)  # first — nudge
        exit_code, _ = _run(name="agent-2", team_name=None)  # second — block
        assert exit_code == 2

    def test_second_block_is_deny(self):
        _run(name="agent-1", team_name=None)
        _, output = _run(name="agent-2", team_name=None)
        decision = output["hookSpecificOutput"]["permissionDecision"]
        assert decision == "deny"

    def test_second_block_mentions_team_create(self):
        _run(name="agent-1", team_name=None)
        _, output = _run(name="agent-2", team_name=None)
        reason = output["hookSpecificOutput"]["permissionDecisionReason"]
        assert "TeamCreate" in reason

    def test_third_teamless_also_blocked(self):
        _run(name="agent-1", team_name=None)
        _run(name="agent-2", team_name=None)
        exit_code, _ = _run(name="agent-3", team_name=None)
        assert exit_code == 2


# ---------------------------------------------------------------------------
# Stale tracker behaviour
# ---------------------------------------------------------------------------

class TestStaleTrackerBehaviour:
    def test_stale_entry_does_not_trigger_block(self):
        """A tracker entry older than _WINDOW_SECONDS should not count."""
        track = Path.home() / ".claude" / "hooks" / "state" / f"agent-team-tracker-{_FAKE_SESSION}"
        old_ts = time.time() - hook._WINDOW_SECONDS - 5
        track.write_text(f"{old_ts}\n")

        exit_code, output = _run(name="fresh-agent", team_name=None)
        # Should be a nudge (first in window), not a block
        assert exit_code == 0
        assert "systemMessage" in output

    def test_fresh_entry_after_stale_triggers_nudge_then_block(self):
        """One fresh entry + one stale should count as 1 fresh → second real call blocks."""
        track = Path.home() / ".claude" / "hooks" / "state" / f"agent-team-tracker-{_FAKE_SESSION}"
        old_ts = time.time() - hook._WINDOW_SECONDS - 5
        track.write_text(f"{old_ts}\n")

        _run(name="agent-fresh", team_name=None)   # first in-window → nudge
        exit_code, _ = _run(name="agent-fresh-2", team_name=None)  # second → block
        assert exit_code == 2


# ---------------------------------------------------------------------------
# CI detection
# ---------------------------------------------------------------------------

class TestCIDetection:
    def test_ci_without_session_id_allows(self):
        """In CI without session_id, hook should allow to avoid false positives."""
        payload = {
            "hook_event_name": "PreToolUse",
            "tool_name": "Agent",
            "tool_input": {"name": "researcher"},
            # no session_id
        }
        with patch.dict(os.environ, {"CI": "true", "CLAUDE_SESSION_ID": ""}):
            result = hook._is_ci_without_session(payload)
        assert result  # should detect CI without session

    def test_ci_with_session_id_not_skipped(self):
        payload = {"session_id": "abc123-valid"}
        with patch.dict(os.environ, {"CI": "true"}):
            result = hook._is_ci_without_session(payload)
        assert not result  # has session_id, should not skip


# ---------------------------------------------------------------------------
# Session ID extraction
# ---------------------------------------------------------------------------

class TestSessionIdExtraction:
    def test_session_id_from_payload_used(self):
        data = {"session_id": "test-session-abc"}
        assert hook._get_session_id(data) == "test-session-abc"

    def test_unsafe_session_id_falls_back(self):
        """Session IDs with path-traversal chars should be rejected."""
        data = {"session_id": "../evil/path"}
        result = hook._get_session_id(data)
        assert result != "../evil/path"

    def test_empty_session_id_falls_back_to_env(self):
        data = {"session_id": ""}
        with patch.dict(os.environ, {"CLAUDE_SESSION_ID": "env-session-id"}):
            result = hook._get_session_id(data)
        assert result == "env-session-id"
