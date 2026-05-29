"""Unit tests for ~/.claude/hooks/enforce_named_agents.py.

Tests:
- Non-Agent tools pass through
- Agent with name + team_name → allowed
- Agent without name → hard block (canonical deny: permissionDecision JSON + exit 0)
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

_FAKE_SESSION = "test-session-99999"


def _run(
    name: str | None,
    team_name: str | None,
    waiver: str | None = None,
    session_id: str | None = None,
) -> tuple[int, dict]:
    """Run main() for an Agent PreToolUse call.

    Returns (exit_code, parsed_stdout_json).

    CANONICAL DENY CONTRACT: a hard block is signaled by a single mechanism —
    a permissionDecision="deny" JSON document on stdout plus exit code 0 (NOT
    exit 2). exit_code is therefore 0 for every outcome (allow / nudge / deny);
    a deny is distinguished by the stdout JSON, asserted via ``assert_denied``.

    When ``session_id`` is given it is put on the payload (mirroring a real
    Claude Code dispatch) and the _get_session_id patch is NOT applied, so the
    hook's real session resolution / CI-detection logic runs end to end.
    """
    tool_input: dict = {}
    if name is not None:
        tool_input["name"] = name
    if team_name is not None:
        tool_input["team_name"] = team_name
    if waiver is not None:
        tool_input["enforce_named_agents_waiver"] = waiver

    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Agent",
        "tool_input": tool_input,
    }
    if session_id is not None:
        payload["session_id"] = session_id

    stdout_capture = io.StringIO()
    exit_code = 0
    with ExitStack() as stack:
        stack.enter_context(patch("sys.stdin", io.StringIO(json.dumps(payload))))
        stack.enter_context(patch("sys.stdout", stdout_capture))
        # When the caller supplies an explicit session_id we exercise the real
        # _get_session_id (so CI-without-session detection runs against the
        # real payload). Otherwise pin the session for hermetic tracker
        # isolation.
        if session_id is None:
            stack.enter_context(
                patch(
                    "enforce_named_agents._get_session_id",
                    return_value=_FAKE_SESSION,
                )
            )
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
        assert_denied(exit_code, output)

    def test_empty_name_hard_blocked(self):
        exit_code, output = _run(name="", team_name="my-team")
        assert_denied(exit_code, output)

    def test_block_output_is_deny(self):
        _, output = _run(name=None, team_name="my-team")
        decision = output["hookSpecificOutput"]["permissionDecision"]
        assert decision == "deny"

    def test_block_message_mentions_name(self):
        _, output = _run(name=None, team_name="my-team")
        reason = output["hookSpecificOutput"]["permissionDecisionReason"]
        assert "name" in reason.lower()

    def test_no_name_blocked_even_with_team(self):
        exit_code, output = _run(name=None, team_name="some-team")
        assert_denied(exit_code, output)


# ---------------------------------------------------------------------------
# Escape path — waiver on the missing-name hard block (gate-design.md Rule 1)
# ---------------------------------------------------------------------------

class TestEscapePath:
    _VALID_REASON = (
        "user explicitly requested an anonymous probe agent for a one-shot "
        "diagnostic that will never be addressed"
    )

    def test_block_message_documents_waiver_flag(self):
        """Rule 1: the denial itself must document the escape path."""
        _, output = _run(name=None, team_name="my-team")
        reason = output["hookSpecificOutput"]["permissionDecisionReason"]
        assert "enforce_named_agents_waiver" in reason

    def test_escape_with_valid_reason_allows_dispatch(self):
        """A valid waiver reason converts the hard block into an allow."""
        exit_code, output = _run(
            name=None, team_name="my-team", waiver=self._VALID_REASON
        )
        assert exit_code == 0
        # not a deny
        assert output.get("hookSpecificOutput", {}).get("permissionDecision") != "deny"

    def test_escape_with_placeholder_reason_rejected(self):
        """A placeholder waiver does not satisfy the escape — still blocked."""
        exit_code, output = _run(name=None, team_name="my-team", waiver="tbd")
        assert_denied(exit_code, output)

    def test_escape_with_short_reason_rejected(self):
        """A reason under the 20-char substance threshold is rejected."""
        exit_code, output = _run(name=None, team_name="my-team", waiver="too short")
        assert_denied(exit_code, output)

    def test_escape_with_empty_reason_rejected(self):
        exit_code, output = _run(name=None, team_name="my-team", waiver="   ")
        assert_denied(exit_code, output)

    def test_escape_rejection_message_explains_why(self):
        """Rule 1/Internal Transparency: rejection tells the agent what failed."""
        _, output = _run(name=None, team_name="my-team", waiver="wip")
        reason = output["hookSpecificOutput"]["permissionDecisionReason"]
        assert "placeholder" in reason.lower() or "reason" in reason.lower()

    def test_escape_persists_signal(self):
        """Rule 2: an accepted waiver records to the gate-signal store."""
        with patch("enforce_named_agents._record_signal") as mock_record:
            exit_code, _ = _run(
                name=None, team_name="my-team", waiver=self._VALID_REASON
            )
        assert exit_code == 0
        decisions = [
            kw.get("decision")
            for _, kw in mock_record.call_args_list
        ]
        assert "waiver-accepted" in decisions

    def test_escape_signal_carries_reason(self):
        """The captured reason is the labeled training data (Rule 2)."""
        with patch("enforce_named_agents._record_signal") as mock_record:
            _run(name=None, team_name="my-team", waiver=self._VALID_REASON)
        waiver_calls = [
            kw for _, kw in mock_record.call_args_list
            if kw.get("decision") == "waiver-accepted"
        ]
        assert waiver_calls
        assert self._VALID_REASON in waiver_calls[0].get("reason", "")

    def test_escape_uses_waiver_event_type(self):
        """Standard waiver convention: the accepted waiver is recorded with
        event_type='waiver' so it lands in the dedicated waiver corpus."""
        with patch("enforce_named_agents._record_signal") as mock_record:
            _run(name=None, team_name="my-team", waiver=self._VALID_REASON)
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

        exit_code, _ = _run(
            name=None, team_name="my-team", waiver=self._VALID_REASON
        )
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
        exit_code, output = _run(name="agent-2", team_name=None)  # second — block
        assert_denied(exit_code, output)

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
        exit_code, output = _run(name="agent-3", team_name=None)
        assert_denied(exit_code, output)


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
        exit_code, output = _run(name="agent-fresh-2", team_name=None)  # second → block
        assert_denied(exit_code, output)


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

    # -- e2e: the CI stand-down must NOT swallow the missing-name hard block --
    #
    # Bug (claude-workflow-setup-3lq): the _is_ci_without_session early-return
    # ran BEFORE the missing-name block, so an anonymous agent in CI was wrongly
    # ALLOWED. The missing-name check needs no session/PPID state — only the
    # teamless-tracking path does — so it must still fire under CI.

    def test_ci_without_session_missing_name_still_blocks(self):
        """main() e2e: CI=true, no session, no name → hard block (canonical deny).

        This is the live-probe regression: outside CI a no-name agent is
        blocked; the CI stand-down must not turn that into an allow.
        """
        with patch.dict(os.environ, {"CI": "true", "CLAUDE_SESSION_ID": ""}):
            exit_code, output = _run(name=None, team_name="my-team")
        assert_denied(exit_code, output)

    def test_ci_valid_session_second_teamless_agent_blocks(self):
        """main() e2e: CI=true + valid session + 2nd teamless agent → block.

        With a real session id the PPID-fallback concern does not apply, so
        teamless-multi-agent tracking must still fire under CI.
        """
        sid = "ci-real-session-12345"
        track = (
            Path.home() / ".claude" / "hooks" / "state"
            / f"agent-team-tracker-{sid}"
        )
        track.unlink(missing_ok=True)
        try:
            with patch.dict(os.environ, {"CI": "true", "CLAUDE_SESSION_ID": ""}):
                # first teamless agent in window → nudge (allowed)
                first_code, _ = _run(
                    name="agent-1", team_name=None, session_id=sid
                )
                # second teamless agent in window → hard block
                exit_code, output = _run(
                    name="agent-2", team_name=None, session_id=sid
                )
        finally:
            track.unlink(missing_ok=True)
        assert first_code == 0  # positive control: first is allowed (nudge)
        # negative control: second is blocked via canonical single-mechanism deny
        assert_denied(exit_code, output)

    def test_ci_without_session_teamless_tracking_stands_down(self):
        """Positive control for the stand-down's TRUE purpose.

        CI=true with NO usable session id: teamless tracking would use the
        meaningless PPID fallback, so a NAMED-but-teamless agent should still
        be allowed (not falsely blocked) — the stand-down stays scoped to the
        tracking path it was designed for.
        """
        with patch.dict(os.environ, {"CI": "true", "CLAUDE_SESSION_ID": ""}):
            # Two named teamless agents back to back; without the stand-down
            # the second would hard-block off a bogus PPID-keyed tracker.
            _run(name="agent-1", team_name=None)
            exit_code, _ = _run(name="agent-2", team_name=None)
        assert exit_code == 0  # stand-down keeps teamless tracking quiet in CI


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


class TestSafeSessionId:
    """Directly exercise _is_safe_session_id's reject set.

    Business invariant: the function must reject ANY value that could
    escape the tracker directory or corrupt the tracker filename. The
    docstring promises to reject "anything that could escape the tracker
    directory"; a NUL byte is a classic filename-injection vector that
    was silently accepted before this fix.
    """

    # --- Positive controls: real session ids must stay safe ---
    @pytest.mark.parametrize(
        "value",
        [
            "test-session-99999",
            "abc123",
            "a-b_c.d",  # dots/dashes/underscores in the middle are fine
            "UUID-4f3a9b2c",
        ],
    )
    def test_safe_session_ids_accepted(self, value):
        assert hook._is_safe_session_id(value) is True

    # --- Negative control: the bug this fix closes ---
    def test_nul_byte_rejected(self):
        """A NUL byte must be rejected (regression: previously True)."""
        assert hook._is_safe_session_id("a\x00b") is False

    def test_leading_nul_rejected(self):
        assert hook._is_safe_session_id("\x00abc") is False

    def test_trailing_nul_rejected(self):
        assert hook._is_safe_session_id("abc\x00") is False

    # --- Negative controls: other control bytes must also be rejected ---
    @pytest.mark.parametrize(
        "value",
        [
            "a\nb",   # newline — corrupts the line-delimited tracker file
            "a\rb",   # carriage return
            "a\tb",   # tab
            "a\x1bb",  # ESC
            "a\x7fb",  # DEL
        ],
    )
    def test_control_bytes_rejected(self, value):
        assert hook._is_safe_session_id(value) is False

    # --- Negative controls: pre-existing path-traversal rejects still hold ---
    @pytest.mark.parametrize(
        "value",
        ["", "/", "..", ".", "a/b", "a\\b"],
    )
    def test_path_traversal_still_rejected(self, value):
        assert hook._is_safe_session_id(value) is False

    def test_nul_session_id_falls_back(self):
        """A payload session id with a NUL byte must not be used as-is."""
        data = {"session_id": "a\x00b"}
        result = hook._get_session_id(data)
        assert result != "a\x00b"
