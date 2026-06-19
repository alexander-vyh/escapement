"""Unit tests for ~/.claude/hooks/enforce_named_agents.py.

Tests:
- Non-Agent tools pass through
- Agent with name → allowed
- Agent without name → hard block (canonical deny: permissionDecision JSON + exit 0)
- Waiver escape path: valid reason allows anonymous; invalid/placeholder blocks

Run from anywhere with:
  python -m pytest ~/.claude/hooks/tests/test_enforce_named_agents.py -v
"""

import io
import json
import os
import sys
from contextlib import ExitStack
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

def _run(
    name: str | None,
    waiver: str | None = None,
) -> tuple[int, dict]:
    """Run main() for an Agent PreToolUse call.

    Returns (exit_code, parsed_stdout_json).

    CANONICAL DENY CONTRACT: a hard block is signaled by a single mechanism —
    a permissionDecision="deny" JSON document on stdout plus exit code 0 (NOT
    exit 2). exit_code is therefore 0 for every outcome (allow / deny);
    a deny is distinguished by the stdout JSON, asserted via ``assert_denied``.
    """
    tool_input: dict = {}
    if name is not None:
        tool_input["name"] = name
    if waiver is not None:
        tool_input["enforce_named_agents_waiver"] = waiver

    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Agent",
        "tool_input": tool_input,
    }

    stdout_capture = io.StringIO()
    exit_code = 0
    with ExitStack() as stack:
        stack.enter_context(patch("sys.stdin", io.StringIO(json.dumps(payload))))
        stack.enter_context(patch("sys.stdout", stdout_capture))
        try:
            # hook returns 0 for every outcome; a deny is carried by the
            # stdout JSON decision (canonical single-mechanism contract)
            result = hook.main()
            exit_code = result if result is not None else 0
        except SystemExit as exc:
            exit_code = exc.code or 0

    out = stdout_capture.getvalue().strip()
    # json.loads raises on a second concatenated document ("Extra data"), so a
    # successful parse here is itself part of the EXACTLY-ONCE guarantee: the
    # hook emitted a single JSON decision, not two stacked block signals.
    data = json.loads(out) if out else {}
    return exit_code, data


def assert_denied(exit_code: int, output: dict) -> None:
    """Assert the hard block was honored EXACTLY ONCE via the canonical
    mechanism: a single permissionDecision="deny" JSON document on stdout AND
    exit code 0 (NOT exit 2). A deny JSON *plus* exit 2 would be a
    contradictory double-block — asserting exit 0 rejects that shape, and the
    single-document parse in ``_run`` rejects two stacked JSON signals.
    """
    assert exit_code == 0, (
        "deny is carried by the stdout JSON decision, not exit 2 — "
        "permissionDecision=deny plus exit 2 is a contradictory double-block"
    )
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"


@pytest.fixture(autouse=True)
def neutralize_ci_env(monkeypatch):
    """Neutralize ambient CI env vars so tests run hermetically."""
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)


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
# Named agents — should always be allowed
# ---------------------------------------------------------------------------

class TestNamedAgent:
    def test_named_agent_allowed(self):
        exit_code, output = _run(name="researcher")
        assert exit_code == 0
        assert output == {}  # no output = clean allow

    def test_different_names_allowed(self):
        exit_code, _ = _run(name="qa-tester")
        assert exit_code == 0

    def test_named_agent_ignores_deprecated_team_name(self):
        """team_name is deprecated and ignored; named agent must still be allowed."""
        tool_input = {"name": "explorer", "team_name": "some-team"}
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Agent",
                   "tool_input": tool_input}
        with patch("sys.stdin", io.StringIO(json.dumps(payload))):
            with patch("sys.stdout", io.StringIO()):
                result = hook.main()
        assert result == 0


# ---------------------------------------------------------------------------
# Missing name — hard block
# ---------------------------------------------------------------------------

class TestMissingName:
    def test_no_name_hard_blocked(self):
        exit_code, output = _run(name=None)
        assert_denied(exit_code, output)

    def test_empty_name_hard_blocked(self):
        exit_code, output = _run(name="")
        assert_denied(exit_code, output)

    def test_block_output_is_deny(self):
        _, output = _run(name=None)
        decision = output["hookSpecificOutput"]["permissionDecision"]
        assert decision == "deny"

    def test_block_message_mentions_name(self):
        _, output = _run(name=None)
        reason = output["hookSpecificOutput"]["permissionDecisionReason"]
        assert "name" in reason.lower()


# ---------------------------------------------------------------------------
# Escape path — waiver for anonymous agents
# ---------------------------------------------------------------------------

class TestEscapePath:
    _VALID_REASON = (
        "user explicitly requested an anonymous probe agent for a one-shot "
        "diagnostic that will never be addressed"
    )

    def test_block_message_documents_waiver_flag(self):
        """Rule 1: the denial itself must document the escape path."""
        _, output = _run(name=None)
        reason = output["hookSpecificOutput"]["permissionDecisionReason"]
        assert "enforce_named_agents_waiver" in reason

    def test_escape_with_valid_reason_allows_dispatch(self):
        """A valid waiver reason converts the hard block into an allow."""
        exit_code, output = _run(name=None, waiver=self._VALID_REASON)
        assert exit_code == 0
        # not a deny
        assert output.get("hookSpecificOutput", {}).get("permissionDecision") != "deny"

    def test_escape_with_placeholder_reason_rejected(self):
        """A placeholder waiver does not satisfy the escape — still blocked."""
        exit_code, output = _run(name=None, waiver="tbd")
        assert_denied(exit_code, output)

    def test_escape_with_short_reason_rejected(self):
        """A reason under the 20-char substance threshold is rejected."""
        exit_code, output = _run(name=None, waiver="too short")
        assert_denied(exit_code, output)

    def test_escape_with_empty_reason_rejected(self):
        exit_code, output = _run(name=None, waiver="   ")
        assert_denied(exit_code, output)

    def test_escape_rejection_message_explains_why(self):
        """Rule 1/Internal Transparency: rejection tells the agent what failed."""
        _, output = _run(name=None, waiver="wip")
        reason = output["hookSpecificOutput"]["permissionDecisionReason"]
        assert "placeholder" in reason.lower() or "reason" in reason.lower()

    def test_escape_persists_signal(self):
        """Rule 2: an accepted waiver records to the gate-signal store."""
        with patch("enforce_named_agents._record_signal") as mock_record:
            exit_code, _ = _run(name=None, waiver=self._VALID_REASON)
        assert exit_code == 0
        decisions = [
            kw.get("decision")
            for _, kw in mock_record.call_args_list
        ]
        assert "waiver-accepted" in decisions

    def test_escape_signal_carries_reason(self):
        """The captured reason is the labeled training data (Rule 2)."""
        with patch("enforce_named_agents._record_signal") as mock_record:
            _run(name=None, waiver=self._VALID_REASON)
        waiver_calls = [
            kw for _, kw in mock_record.call_args_list
            if kw.get("decision") == "waiver-accepted"
        ]
        assert waiver_calls
        assert self._VALID_REASON in waiver_calls[0].get("reason", "")

    def test_escape_uses_waiver_event_type(self):
        """Standard waiver convention: the accepted waiver is recorded with
        event_type='waiver' so it lands in the dedicated waiver corpus.
        """
        with patch("enforce_named_agents._record_signal") as mock_record:
            _run(name=None, waiver=self._VALID_REASON)
        waiver_calls = [
            kw for _, kw in mock_record.call_args_list
            if kw.get("decision") == "waiver-accepted"
        ]
        assert waiver_calls
        assert waiver_calls[0].get("event_type") == "waiver"

    def test_escape_writes_dedicated_waiver_corpus_end_to_end(
        self, tmp_path, monkeypatch
    ):
        """End-to-end: an accepted waiver lands a REAL line in
        .beads/.gate-waivers.jsonl (the bead's 'exercise it' requirement).

        Points the shared _gate_signal backbone at a tmp .beads/ via BEADS_DIR
        and runs the hook with NO _record_signal mock, so the gate produces a
        genuine greppable waiver entry.
        """
        beads = tmp_path / ".beads"
        beads.mkdir()
        monkeypatch.setenv("BEADS_DIR", str(beads))
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)

        exit_code, _ = _run(name=None, waiver=self._VALID_REASON)
        assert exit_code == 0

        waiver_file = beads / ".gate-waivers.jsonl"
        assert waiver_file.is_file(), "gate must write the dedicated waiver corpus"
        recs = [json.loads(line)
                for line in waiver_file.read_text().strip().splitlines()]
        waiver_recs = [r for r in recs if r["decision"] == "waiver-accepted"]
        assert waiver_recs, "accepted waiver must be recorded in the corpus"
        assert waiver_recs[0]["gate"] == "enforce_named_agents"
        assert waiver_recs[0]["reason"] == self._VALID_REASON
        assert waiver_recs[0]["event_type"] == "waiver"


# ---------------------------------------------------------------------------
# CI environment — missing-name block must still fire
# (regression: claude-workflow-setup-3lq — CI env must not swallow the
# anonymous-agent hard block)
# ---------------------------------------------------------------------------

class TestCIEnvironment:
    def test_ci_without_session_missing_name_still_blocks(self):
        """main() e2e: CI=true, no session, no name → hard block (canonical deny).

        The CI environment must not suppress the anonymous-agent gate.
        """
        with patch.dict(os.environ, {"CI": "true", "CLAUDE_SESSION_ID": ""}):
            exit_code, output = _run(name=None)
        assert_denied(exit_code, output)

    def test_ci_named_agent_allowed(self):
        """A named agent is allowed even in a CI environment."""
        with patch.dict(os.environ, {"CI": "true"}):
            exit_code, output = _run(name="ci-agent")
        assert exit_code == 0
        assert output == {}
