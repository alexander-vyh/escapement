"""Unit tests for ~/.claude/hooks/validate_no_shirking.py.

Tests:
- find_shirking_phrase: pattern matching against known evasion phrases
- read_recent_agent_text: JSONL transcript parsing
- main (PreToolUse): only fires on finishing Bash commands with shirking transcript
- main (Stop): fires when agent declares done with shirking transcript

Run from anywhere with:
  python -m pytest ~/.claude/hooks/tests/test_validate_no_shirking.py -v
"""

import io
import importlib.util
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

_hooks_dir = Path(__file__).resolve().parent.parent
if not _hooks_dir.exists():
    pytest.skip("~/.claude/hooks/ not found", allow_module_level=True)

if str(_hooks_dir) not in sys.path:
    sys.path.insert(0, str(_hooks_dir))

_MODULE_PATH = _hooks_dir / "validate_no_shirking.py"
_spec = importlib.util.spec_from_file_location("validate_no_shirking", _MODULE_PATH)
assert _spec is not None and _spec.loader is not None
shirking_gate = importlib.util.module_from_spec(_spec)
sys.modules["validate_no_shirking"] = shirking_gate
_spec.loader.exec_module(shirking_gate)
from validate_no_shirking import (  # noqa: E402
    find_shirking_match,
    find_shirking_phrase,
    find_stop_solicitation_match,
    read_recent_agent_text,
)

_ORIGINAL_STOP_SOLICITATION_MODEL_VERDICT = shirking_gate._stop_solicitation_model_verdict


def test_stop_solicitation_uses_shared_local_judge_client_architecture() -> None:
    source = (Path(__file__).resolve().parent.parent / "validate_no_shirking.py").read_text()
    assert "_lj.boolean_verdict" in source
    assert "localhost:8000" not in source
    assert "chat/completions" not in source
    assert "import httpx" not in source


@pytest.fixture(autouse=True)
def _disable_live_stop_solicitation_judge(monkeypatch):
    """Tests inject semantic verdicts explicitly; never call the live local model."""
    monkeypatch.setattr(shirking_gate, "_stop_solicitation_model_verdict", lambda text: None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_transcript(agent_text: str) -> str:
    """Write a single assistant turn to a temp JSONL file; return its path."""
    entry = {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": agent_text}],
        },
    }
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, prefix="/tmp/test_shirking_"
    )
    f.write(json.dumps(entry) + "\n")
    f.flush()
    f.close()
    return f.name


def _run_main(hook_event: str, command: str = "", transcript_path: str = "") -> bool:
    """Run main() with the given hook input; return True if it denied (SystemExit(2))."""
    from validate_no_shirking import main

    payload: dict = {"hook_event_name": hook_event, "transcript_path": transcript_path}
    if hook_event == "PreToolUse":
        payload["tool_name"] = "Bash"
        payload["tool_input"] = {"command": command}

    stdin_data = json.dumps(payload)
    try:
        with patch("sys.stdin", io.StringIO(stdin_data)):
            main()
        return False
    except SystemExit as exc:
        return exc.code == 2


def _run_main_output(hook_event: str, command: str = "", transcript_path: str = "") -> dict:
    """Run main() and return the parsed JSON deny payload. Raises if hook allowed."""
    import io as _io

    from validate_no_shirking import main

    payload: dict = {"hook_event_name": hook_event, "transcript_path": transcript_path}
    if hook_event == "PreToolUse":
        payload["tool_name"] = "Bash"
        payload["tool_input"] = {"command": command}

    stdin_data = json.dumps(payload)
    captured = _io.StringIO()
    try:
        with patch("sys.stdin", _io.StringIO(stdin_data)), patch("sys.stdout", captured):
            main()
        raise AssertionError("Expected hook to block but it allowed the action")
    except SystemExit:
        captured.seek(0)
        return json.loads(captured.read())


# ---------------------------------------------------------------------------
# find_shirking_phrase tests
# ---------------------------------------------------------------------------


class TestFindShirkingPhrase:
    """Pattern matching against known evasion phrases."""

    def test_pre_existing_failure(self) -> None:
        phrase = find_shirking_phrase("This looks like a pre-existing failure in the suite.")
        assert phrase is not None

    def test_pre_existing_issue(self) -> None:
        phrase = find_shirking_phrase("That's a pre-existing issue, not caused by my change.")
        assert phrase is not None

    def test_not_in_anything_i_changed(self) -> None:
        phrase = find_shirking_phrase(
            "The test is in test_memory_bounded_streaming.py, not in anything I changed."
        )
        assert phrase is not None

    def test_unrelated_to_our_changes(self) -> None:
        phrase = find_shirking_phrase(
            "Let me check if this is a pre-existing failure unrelated to our changes."
        )
        assert phrase is not None

    def test_unrelated_to_my_changes(self) -> None:
        phrase = find_shirking_phrase("This failure seems unrelated to my changes.")
        assert phrase is not None

    def test_was_already_failing(self) -> None:
        phrase = find_shirking_phrase("That test was already failing before we started.")
        assert phrase is not None

    def test_failed_before_our_changes(self) -> None:
        phrase = find_shirking_phrase("It failed before our changes were applied.")
        assert phrase is not None

    def test_completely_different_problem(self) -> None:
        phrase = find_shirking_phrase("This is a completely different problem from what I fixed.")
        assert phrase is not None

    def test_let_me_check_if_pre_existing(self) -> None:
        """The exact phrasing from the real evasion example."""
        phrase = find_shirking_phrase(
            "There's a failing test, but it's in test_memory_bounded_streaming.py, "
            "not in anything I changed.\n"
            "Let me check if this is a pre-existing failure unrelated to our changes."
        )
        assert phrase is not None

    def test_case_insensitive(self) -> None:
        phrase = find_shirking_phrase("PRE-EXISTING FAILURE in the test suite")
        assert phrase is not None

    def test_hyphen_variant(self) -> None:
        phrase = find_shirking_phrase("This is a pre-existing issue.")
        assert phrase is not None

    def test_clean_text_returns_none(self) -> None:
        phrase = find_shirking_phrase(
            "All tests pass. Fixed the streaming bug by capping buffer size."
        )
        assert phrase is None

    def test_fixing_acknowledgment_returns_none(self) -> None:
        phrase = find_shirking_phrase(
            "I ran the full test suite and everything is green. The fix works correctly."
        )
        assert phrase is None

    def test_returned_snippet_contains_context(self) -> None:
        """The snippet should include some text around the match."""
        phrase = find_shirking_phrase("The test was already failing before our changes landed.")
        assert phrase is not None
        assert len(phrase) > 10

    def test_not_my_problem(self) -> None:
        phrase = find_shirking_phrase("That's not my problem, it was broken before.")
        assert phrase is not None

    def test_separate_issue_from(self) -> None:
        phrase = find_shirking_phrase("This is a separate issue from what I was fixing.")
        assert phrase is not None

    # Acceptance evasion patterns
    def test_note_and_move_past(self) -> None:
        phrase = find_shirking_phrase(
            "that's a sync process issue I should note and move past"
        )
        assert phrase is not None

    def test_note_and_move_on(self) -> None:
        phrase = find_shirking_phrase("I'll note this and move on to the next problem.")
        assert phrase is not None

    def test_just_accept_the_errors(self) -> None:
        phrase = find_shirking_phrase(
            "I can either make the table creation conditional or just accept the errors until the data shows up."
        )
        assert phrase is not None

    def test_accept_the_errors_until(self) -> None:
        phrase = find_shirking_phrase(
            "Let's just accept the failures until the compaction jobs run."
        )
        assert phrase is not None

    def test_real_acceptance_evasion_example(self) -> None:
        """Reproduces the exact statement that slipped through."""
        phrase = find_shirking_phrase(
            "that's a sync process issue I should note and move past. "
            "I can either make the table creation conditional or just accept the errors "
            "until the data shows up."
        )
        assert phrase is not None


# ---------------------------------------------------------------------------
# read_recent_agent_text tests
# ---------------------------------------------------------------------------


class TestReadRecentAgentText:
    """JSONL transcript parsing."""

    def test_extracts_assistant_text(self) -> None:
        path = _make_transcript("Something went wrong with the sync.")
        try:
            text = read_recent_agent_text(path)
            assert "Something went wrong with the sync." in text
        finally:
            Path(path).unlink(missing_ok=True)

    def test_ignores_user_turns(self) -> None:
        entry = {
            "type": "user",
            "message": {"role": "user", "content": "user message here"},
        }
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, prefix="/tmp/test_shirking_"
        )
        f.write(json.dumps(entry) + "\n")
        f.close()
        try:
            text = read_recent_agent_text(f.name)
            assert "user message here" not in text
        finally:
            Path(f.name).unlink(missing_ok=True)

    def test_nonexistent_file_returns_empty(self) -> None:
        text = read_recent_agent_text("/tmp/does_not_exist_xyzzy.jsonl")
        assert text == ""

    def test_malformed_json_lines_handled(self) -> None:
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, prefix="/tmp/test_shirking_"
        )
        f.write("not valid json\n")
        f.write(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "valid turn"}],
                    },
                }
            )
            + "\n"
        )
        f.close()
        try:
            text = read_recent_agent_text(f.name)
            assert "valid turn" in text
        finally:
            Path(f.name).unlink(missing_ok=True)

    def test_multiple_turns_concatenated(self) -> None:
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, prefix="/tmp/test_shirking_"
        )
        for text in ("first turn", "second turn", "third turn"):
            entry = {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": text}],
                },
            }
            f.write(json.dumps(entry) + "\n")
        f.close()
        try:
            result = read_recent_agent_text(f.name)
            assert "first turn" in result
            assert "third turn" in result
        finally:
            Path(f.name).unlink(missing_ok=True)

    def test_flat_role_format(self) -> None:
        """Handles transcripts where role is at the top level (no 'message' wrapper)."""
        entry = {
            "role": "assistant",
            "content": [{"type": "text", "text": "flat format works"}],
        }
        f = tempfile.NamedTemporaryFile(
            mode="w", suffix=".jsonl", delete=False, prefix="/tmp/test_shirking_"
        )
        f.write(json.dumps(entry) + "\n")
        f.close()
        try:
            text = read_recent_agent_text(f.name)
            assert "flat format works" in text
        finally:
            Path(f.name).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# main — PreToolUse path
# ---------------------------------------------------------------------------


class TestMainPreToolUse:
    """Full pipeline tests for the PreToolUse event."""

    def test_non_bash_tool_allowed(self) -> None:
        transcript = _make_transcript("pre-existing failure in test_x.py")
        try:
            payload = json.dumps(
                {
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Edit",
                    "tool_input": {"file_path": "foo.py"},
                    "transcript_path": transcript,
                }
            )
            from validate_no_shirking import main

            with patch("sys.stdin", io.StringIO(payload)):
                result = main()
            assert result == 0
        finally:
            Path(transcript).unlink(missing_ok=True)

    def test_non_finishing_bash_command_allowed(self) -> None:
        transcript = _make_transcript("pre-existing failure in the suite")
        try:
            denied = _run_main("PreToolUse", command="uv run pytest tests/", transcript_path=transcript)
            assert denied is False
        finally:
            Path(transcript).unlink(missing_ok=True)

    def test_clean_transcript_allows_commit(self) -> None:
        transcript = _make_transcript("All tests pass. Looks good.")
        try:
            denied = _run_main("PreToolUse", command="git commit -m 'fix'", transcript_path=transcript)
            assert denied is False
        finally:
            Path(transcript).unlink(missing_ok=True)

    def test_shirking_transcript_blocks_commit(self) -> None:
        transcript = _make_transcript(
            "The test is failing but it's in test_memory_bounded_streaming.py, "
            "not in anything I changed."
        )
        try:
            denied = _run_main("PreToolUse", command="git commit -m 'fix'", transcript_path=transcript)
            assert denied is True
        finally:
            Path(transcript).unlink(missing_ok=True)

    def test_shirking_transcript_blocks_pr(self) -> None:
        transcript = _make_transcript("This appears to be a pre-existing issue.")
        try:
            denied = _run_main("PreToolUse", command="gh pr create --title 'fix'", transcript_path=transcript)
            assert denied is True
        finally:
            Path(transcript).unlink(missing_ok=True)

    def test_shirking_transcript_blocks_push(self) -> None:
        transcript = _make_transcript("The failure was already failing before our changes.")
        try:
            denied = _run_main("PreToolUse", command="git push origin main", transcript_path=transcript)
            assert denied is True
        finally:
            Path(transcript).unlink(missing_ok=True)

    def test_no_transcript_path_allows(self) -> None:
        denied = _run_main("PreToolUse", command="git commit -m 'fix'", transcript_path="")
        assert denied is False

    def test_nonexistent_transcript_allows(self) -> None:
        denied = _run_main(
            "PreToolUse",
            command="git commit -m 'fix'",
            transcript_path="/tmp/nonexistent_xyzzy.jsonl",
        )
        assert denied is False

    def test_real_evasion_example_blocked(self) -> None:
        """Reproduces the exact phrasing that slipped through originally."""
        transcript = _make_transcript(
            "There's a failing test, but it's in test_memory_bounded_streaming.py, "
            "not in anything I changed.\n"
            "Let me check if this is a pre-existing failure unrelated to our changes."
        )
        try:
            denied = _run_main("PreToolUse", command="git commit -m 'done'", transcript_path=transcript)
            assert denied is True
        finally:
            Path(transcript).unlink(missing_ok=True)

    def test_stop_hook_active_allows(self) -> None:
        """stop_hook_active=true must always allow to prevent infinite loops."""
        transcript = _make_transcript("pre-existing failure, not in anything I changed")
        try:
            from validate_no_shirking import main

            payload = json.dumps(
                {
                    "hook_event_name": "PreToolUse",
                    "tool_name": "Bash",
                    "tool_input": {"command": "git commit -m 'fix'"},
                    "transcript_path": transcript,
                    "stop_hook_active": True,
                }
            )
            with patch("sys.stdin", io.StringIO(payload)):
                result = main()
            assert result == 0
        finally:
            Path(transcript).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# main — Stop path
# ---------------------------------------------------------------------------


class TestMainStop:
    """Full pipeline tests for the Stop event."""

    def test_shirking_transcript_blocks_stop(self) -> None:
        transcript = _make_transcript("This is a pre-existing failure, not related to my changes.")
        try:
            denied = _run_main("Stop", transcript_path=transcript)
            assert denied is True
        finally:
            Path(transcript).unlink(missing_ok=True)

    def test_clean_transcript_allows_stop(self) -> None:
        transcript = _make_transcript("Fixed the OOM issue. All tests pass.")
        try:
            denied = _run_main("Stop", transcript_path=transcript)
            assert denied is False
        finally:
            Path(transcript).unlink(missing_ok=True)

    def test_no_transcript_allows_stop(self) -> None:
        denied = _run_main("Stop", transcript_path="")
        assert denied is False

    def test_real_evasion_example_blocked_at_stop(self) -> None:
        """Agent says 'pre-existing' and tries to stop without committing."""
        transcript = _make_transcript(
            "Let me check if this is a pre-existing failure unrelated to our changes."
        )
        try:
            denied = _run_main("Stop", transcript_path=transcript)
            assert denied is True
        finally:
            Path(transcript).unlink(missing_ok=True)

    def test_stop_hook_active_allows(self) -> None:
        """stop_hook_active=true must always allow to prevent infinite loops."""
        transcript = _make_transcript("pre-existing failure")
        try:
            from validate_no_shirking import main

            payload = json.dumps(
                {
                    "hook_event_name": "Stop",
                    "transcript_path": transcript,
                    "stop_hook_active": True,
                }
            )
            with patch("sys.stdin", io.StringIO(payload)):
                result = main()
            assert result == 0
        finally:
            Path(transcript).unlink(missing_ok=True)

    def test_stop_solicitation_blocks_stop(self) -> None:
        transcript = _make_transcript("Should I continue, or stop here?")
        try:
            denied = _run_main("Stop", transcript_path=transcript)
            assert denied is True
        finally:
            Path(transcript).unlink(missing_ok=True)

    def test_technical_stopping_condition_allows_stop(self) -> None:
        transcript = _make_transcript(
            "The loop's stopping condition should be None when the stream closes."
        )
        try:
            denied = _run_main("Stop", transcript_path=transcript)
            assert denied is False
        finally:
            Path(transcript).unlink(missing_ok=True)

    def test_semantic_stop_solicitation_blocks_stop_without_known_phrase(self) -> None:
        transcript = _make_transcript(
            "I can hand this back at the checkpoint; say the word and I'll proceed."
        )
        try:
            with patch.object(shirking_gate, "_stop_solicitation_model_verdict", return_value=True):
                denied = _run_main("Stop", transcript_path=transcript)
            assert denied is True
        finally:
            Path(transcript).unlink(missing_ok=True)

    def test_semantic_negative_verdict_allows_even_backstop_phrase(self) -> None:
        transcript = _make_transcript("Want me to wrap for the night, or keep going?")
        try:
            with patch.object(shirking_gate, "_stop_solicitation_model_verdict", return_value=False):
                denied = _run_main("Stop", transcript_path=transcript)
            assert denied is False
        finally:
            Path(transcript).unlink(missing_ok=True)

    def test_stop_solicitation_judge_outage_records_signal(self, monkeypatch) -> None:
        records = []
        monkeypatch.setattr(shirking_gate, "_record_signal", lambda **kwargs: records.append(kwargs))
        transcript = _make_transcript(
            "I can hand this back at the checkpoint; say the word and I'll proceed."
        )
        try:
            denied = _run_main("Stop", transcript_path=transcript)
            assert denied is False
        finally:
            Path(transcript).unlink(missing_ok=True)

        assert any(
            record["reason"] == "stop_solicitation_judge_unavailable"
            and record["category"] == "stop-solicitation"
            and record["hook_event"] == "Stop"
            for record in records
        )


# ---------------------------------------------------------------------------
# Block message content
# ---------------------------------------------------------------------------


class TestBlockMessageContent:
    """Verify the deny payload contains the right fields and phrase."""

    def test_output_contains_matched_phrase(self) -> None:
        transcript = _make_transcript("This was already failing before our changes.")
        try:
            output = _run_main_output("PreToolUse", command="git commit -m 'x'", transcript_path=transcript)
            reason = output["hookSpecificOutput"]["permissionDecisionReason"]
            assert "already failing" in reason
        finally:
            Path(transcript).unlink(missing_ok=True)

    def test_output_permission_decision_is_deny(self) -> None:
        transcript = _make_transcript("pre-existing failure in test_x.py")
        try:
            output = _run_main_output("PreToolUse", command="git commit -m 'x'", transcript_path=transcript)
            assert output["hookSpecificOutput"]["permissionDecision"] == "deny"
        finally:
            Path(transcript).unlink(missing_ok=True)

    def test_stop_uses_top_level_format(self) -> None:
        """Stop events use {decision: 'block', reason: '...'}, not hookSpecificOutput."""
        transcript = _make_transcript("completely different problem from this PR")
        try:
            output = _run_main_output("Stop", transcript_path=transcript)
            assert output["decision"] == "block"
            assert "OUTCOME OWNERSHIP VIOLATION" in output["reason"]
        finally:
            Path(transcript).unlink(missing_ok=True)

    def test_pretooluse_event_name_in_output(self) -> None:
        transcript = _make_transcript("not in anything I changed")
        try:
            output = _run_main_output("PreToolUse", command="git push", transcript_path=transcript)
            assert output["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
        finally:
            Path(transcript).unlink(missing_ok=True)

    def test_block_message_includes_remediation(self) -> None:
        """The block message must tell the agent what to do, not just what it did wrong."""
        transcript = _make_transcript("unrelated to our changes")
        try:
            output = _run_main_output("PreToolUse", command="git commit -m 'x'", transcript_path=transcript)
            reason = output["hookSpecificOutput"]["permissionDecisionReason"]
            assert "FIX" in reason
            # Message should be directive — no "ask user to skip" option
            assert "ask to skip" not in reason.lower()
        finally:
            Path(transcript).unlink(missing_ok=True)

    def test_stop_solicitation_message_does_not_say_fix_failures(self) -> None:
        transcript = _make_transcript("Should I continue, or stop here?")
        try:
            output = _run_main_output("Stop", transcript_path=transcript)
            reason = output["reason"]
            assert "STOP-SOLICITATION VIOLATION" in reason
            assert "FIX THE FAILURES NOW" not in reason
            assert "Continue with the next in-scope action" in reason
        finally:
            Path(transcript).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# New shirking pattern tests (Level 1 expansion)
# ---------------------------------------------------------------------------


def _make_tool_transcript(entries: list[dict]) -> str:
    """Create a transcript with tool_use blocks. Each entry: {role, content}."""
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".jsonl", delete=False, prefix="/tmp/test_shirking_"
    )
    for entry in entries:
        wrapped = {"type": entry["role"], "message": entry}
        f.write(json.dumps(wrapped) + "\n")
    f.close()
    return f.name


class TestNewShirkingPatterns:
    """Patterns added to catch infrastructure blame, deferral, and scope limitation."""

    def test_exact_triggering_quote(self) -> None:
        """The exact phrase that triggered this improvement."""
        assert find_shirking_phrase("CI infra issue, not my code") is not None

    def test_not_my_code(self) -> None:
        assert find_shirking_phrase("That's not my code that's failing") is not None

    def test_not_my_responsibility(self) -> None:
        assert find_shirking_phrase("That's not our responsibility to fix") is not None

    def test_ci_issue(self) -> None:
        assert find_shirking_phrase("This is a CI issue") is not None

    def test_ci_infra_issue(self) -> None:
        assert find_shirking_phrase("This is a CI infra issue") is not None

    def test_ci_infrastructure_issue(self) -> None:
        assert find_shirking_phrase("Looks like a CI infrastructure problem") is not None

    def test_pipeline_issue(self) -> None:
        assert find_shirking_phrase("This is a pipeline issue") is not None

    def test_infra_problem(self) -> None:
        assert find_shirking_phrase("This is an infrastructure problem") is not None

    def test_environment_issue(self) -> None:
        assert find_shirking_phrase("This is an environment issue") is not None

    def test_runner_issue(self) -> None:
        assert find_shirking_phrase("This is a runner issue") is not None

    def test_ci_is_broken(self) -> None:
        assert find_shirking_phrase("The CI is broken") is not None

    def test_pipeline_is_flaky(self) -> None:
        assert find_shirking_phrase("The pipeline is flaky") is not None

    def test_build_seems_unstable(self) -> None:
        assert find_shirking_phrase("The build seems unstable") is not None

    # Negative controls: the works/passes-locally patterns were removed (0 lifetime
    # true catches, fired opposite to intent — flagging honest local verification as
    # deflection). These phrases must NOT be flagged as shirking.
    def test_works_locally_not_flagged(self) -> None:
        assert find_shirking_phrase("It works fine locally") is None

    def test_works_on_my_machine_not_flagged(self) -> None:
        assert find_shirking_phrase("It works on my machine") is None

    def test_passes_locally_not_flagged(self) -> None:
        assert find_shirking_phrase("The test passes locally") is None

    def test_needs_separate_investigation(self) -> None:
        assert find_shirking_phrase("This needs a separate investigation") is not None

    def test_needs_separate_ticket(self) -> None:
        assert find_shirking_phrase("This needs a separate ticket") is not None

    def test_can_be_fixed_later(self) -> None:
        assert find_shirking_phrase("This can be fixed later") is not None

    def test_should_be_addressed_separately(self) -> None:
        assert find_shirking_phrase("This should be addressed separately") is not None

    def test_will_be_fixed_in_follow_up(self) -> None:
        assert find_shirking_phrase("This will be fixed in a follow-up PR") is not None

    def test_leaving_it_for_now(self) -> None:
        assert find_shirking_phrase("I'll leave this for now") is not None

    def test_left_it_as_is(self) -> None:
        assert find_shirking_phrase("I left that as-is") is not None

    def test_out_of_scope(self) -> None:
        assert find_shirking_phrase("That's out of scope for this task") is not None

    def test_beyond_scope(self) -> None:
        assert find_shirking_phrase("That's beyond the scope of this PR") is not None

    def test_outside_scope(self) -> None:
        assert find_shirking_phrase("That's outside scope") is not None

    def test_flaky_test_dismissal(self) -> None:
        assert find_shirking_phrase("That's just a flaky test") is not None

    def test_intermittent_failure(self) -> None:
        assert find_shirking_phrase("This is an intermittent failure") is not None

    def test_known_issue(self) -> None:
        assert find_shirking_phrase("This is a known issue") is not None

    def test_stop_solicitation_model_uses_shared_local_judge_client(self, monkeypatch) -> None:
        calls = []

        def fake_boolean_verdict(text, **kwargs):
            calls.append((text, kwargs))
            return True

        monkeypatch.setattr(
            shirking_gate,
            "_stop_solicitation_model_verdict",
            _ORIGINAL_STOP_SOLICITATION_MODEL_VERDICT,
        )
        monkeypatch.setattr(shirking_gate._lj, "boolean_verdict", fake_boolean_verdict)

        assert shirking_gate._stop_solicitation_model_verdict(
            "I can hand this back here; say the word and I will proceed."
        ) is True
        assert calls == [
            (
                "I can hand this back here; say the word and I will proceed.",
                {
                    "system_prompt": shirking_gate._STOP_SOLICITATION_SYSTEM,
                    "positive_labels": ("stop_solicitation",),
                    "negative_labels": ("not_stop_solicitation",),
                },
            )
        ]

    def test_want_me_to_wrap_or_keep_going_is_stop_solicitation(self) -> None:
        match = find_stop_solicitation_match(
            "Want me to wrap for the night, or keep going?",
            judge=lambda text: None,
        )
        assert match is not None
        assert match[1] == "stop-solicitation"

    def test_good_stopping_point_is_stop_solicitation(self) -> None:
        match = find_stop_solicitation_match(
            "Want any of those, or is this a good stopping point?",
            judge=lambda text: None,
        )
        assert match is not None
        assert match[1] == "stop-solicitation"

    def test_optional_pr_finish_memory_choice_is_stop_solicitation(self) -> None:
        match = find_stop_solicitation_match(
            "Want me to open a draft PR, finish the remaining design.md sections, "
            "or save a memory so a future session picks up cleanly?",
            judge=lambda text: None,
        )
        assert match is not None
        assert match[1] == "stop-solicitation"

    def test_should_i_continue_or_stop_here_is_stop_solicitation(self) -> None:
        match = find_stop_solicitation_match(
            "Should I continue, or stop here?",
            judge=lambda text: None,
        )
        assert match is not None
        assert match[1] == "stop-solicitation"

    def test_semantic_judge_blocks_paraphrase_without_known_phrase(self) -> None:
        match = find_stop_solicitation_match(
            "I can hand this back at the checkpoint; say the word and I'll proceed.",
            judge=lambda text: True,
        )
        assert match is not None
        assert match[1] == "stop-solicitation"

    def test_semantic_negative_overrides_backstop_phrase(self) -> None:
        assert find_stop_solicitation_match(
            "Want me to wrap for the night, or keep going?",
            judge=lambda text: False,
        ) is None

    def test_semantic_judge_unavailable_callback_runs_before_backstop(self) -> None:
        unavailable = []
        match = find_stop_solicitation_match(
            "Should I continue, or stop here?",
            judge=lambda text: None,
            on_unavailable=lambda text: unavailable.append(text),
        )
        assert match is not None
        assert match[1] == "stop-solicitation"
        assert unavailable == ["Should I continue, or stop here?"]

    def test_technical_stopping_condition_not_stop_solicitation(self) -> None:
        assert find_stop_solicitation_match(
            "The loop's stopping condition should be None when the stream closes.",
            judge=lambda text: False,
        ) is None

    def test_product_question_about_stopping_worker_not_stop_solicitation(self) -> None:
        assert find_stop_solicitation_match(
            "Should the worker stop when the queue is empty or keep polling?",
            judge=lambda text: False,
        ) is None

    def test_known_bug(self) -> None:
        assert find_shirking_phrase("That's a known bug") is not None

    def test_tracked_issue(self) -> None:
        assert find_shirking_phrase("It's a tracked issue") is not None

    def test_deployment_issue(self) -> None:
        assert find_shirking_phrase("This is a deployment issue") is not None

    def test_build_system_issue(self) -> None:
        assert find_shirking_phrase("This is a build system issue") is not None

    # False positive guards — these should NOT trigger
    def test_fixing_ci_not_flagged(self) -> None:
        """Agent describing what it's doing to fix CI should be allowed."""
        assert find_shirking_phrase("I'm fixing the CI configuration now") is None

    def test_describing_local_test_run_not_flagged(self) -> None:
        assert find_shirking_phrase("I ran the full test suite and all tests pass") is None


# ---------------------------------------------------------------------------
# Verification evidence tests (Level 3)
# ---------------------------------------------------------------------------


# NOTE: the transcript-based verification-evidence gate was RETIRED in move-1
# (claude-workflow-setup-e9v.2). Its job — block a Stop when code changed but the
# outcome wasn't really verified — is now owned by the continuation-harness contract
# gate, which reads the REAL exit code (harness/tests/test_gate.py: a contract with
# exit_code=1 blocks the Stop). That is a stronger oracle than command-presence.







class TestNegationGuard:
    def test_negated_pre_existing_not_flagged(self):
        assert find_shirking_phrase("I will NOT claim this is a pre-existing failure.") is None

    def test_avoid_not_my_problem_not_flagged(self):
        assert find_shirking_phrase("Avoid saying 'not my problem' — own the outcome.") is None

    def test_if_clause_not_flagged(self):
        assert find_shirking_phrase("If the test was already failing before our changes, we still need to fix it.") is None

    def test_non_negated_still_flagged(self):
        assert find_shirking_phrase("These failures are pre-existing and unrelated to our changes.") is not None

    def test_dont_before_not_my_problem(self):
        assert find_shirking_phrase("Don't say it's not my problem.") is None


class TestWithoutCertaintyIdiom:
    """'without a doubt' / 'without question' are CERTAINTY idioms, not disavowals.

    Bare 'without' is a negation cue ("I fixed this without claiming it's
    pre-existing" genuinely disavows), but "Without a doubt this is a
    pre-existing failure" ASSERTS the shirking — the 'without' opens a
    certainty idiom that intensifies, not denies. Those must still flag.
    """

    # --- MUST FLAG: 'without' opens a certainty idiom, not a disavowal ---

    def test_without_a_doubt_pre_existing_still_flagged(self):
        assert find_shirking_phrase(
            "Without a doubt this is a pre-existing failure unrelated to us."
        ) is not None

    def test_without_question_pre_existing_still_flagged(self):
        assert find_shirking_phrase(
            "Without question this is a pre-existing failure."
        ) is not None

    def test_without_a_doubt_case_insensitive_still_flagged(self):
        assert find_shirking_phrase(
            "without a doubt this is a pre-existing failure."
        ) is not None

    # --- MUST NOT FLAG: 'without' is a genuine disavowal ---

    def test_without_claiming_disavowal_not_flagged(self):
        # "without claiming it is a pre-existing failure" denies the assertion.
        assert find_shirking_phrase(
            "I fixed this without claiming it is a pre-existing failure"
        ) is None


class TestNegationClauseScope:
    """Negation only disavows when it scopes the SAME clause as the match.

    A negation cue in an earlier clause (separated from the match by a comma,
    semicolon, colon, or dash) does NOT guard the following shirking phrase.
    These are negative controls protecting against the over-broad guard that
    suppressed any match with an incidental negation anywhere in the window.
    """

    # --- MUST FLAG: negation is in a different clause from the match ---

    def test_incidental_negation_before_comma_still_flagged(self):
        # "not" scopes "have time", not the "leaving this for now" deferral.
        assert find_shirking_phrase("I do not have time, leaving this for now.") is not None

    def test_negation_before_semicolon_still_flagged(self):
        assert find_shirking_phrase(
            "The disk issue is not ours; this is a pre-existing failure."
        ) is not None

    def test_negation_before_em_dash_still_flagged(self):
        assert find_shirking_phrase(
            "Doesn't matter — leave this for now and move on."
        ) is not None

    # --- MUST NOT FLAG: negation scopes the same clause as the match ---

    def test_same_clause_negation_not_flagged(self):
        assert find_shirking_phrase("I will not defer this") is None

    def test_same_clause_negation_pre_existing_not_flagged(self):
        # No clause break between "not" and "pre-existing failure".
        assert find_shirking_phrase("I will not call this a pre-existing failure") is None


class TestExpandedStripping:
    def test_tilde_fence_stripped(self):
        text = "~~~\npre-existing failure\n~~~\nclean text here"
        assert find_shirking_phrase(text) is None

    def test_system_reminder_tag_stripped(self):
        text = "<system-reminder>pre-existing failure was already failing</system-reminder> clean"
        assert find_shirking_phrase(text) is None

    def test_example_tag_stripped(self):
        text = "<example>not my problem</example> clean prose"
        assert find_shirking_phrase(text) is None

    def test_content_outside_tags_still_flagged(self):
        text = "<example>safe</example> but this is a pre-existing failure"
        assert find_shirking_phrase(text) is not None


class TestNegationGuardMetaDescription:
    """Phrases used in a descriptive/explanatory context should not trigger."""

    def test_scan_for_signs_not_flagged(self):
        # Explaining what the hook does — "scan for signs it skipped work"
        text = 'scan for signs it skipped work ("leave this for now", "outside scope")'
        assert find_shirking_phrase(text) is None

    def test_look_for_phrases_like_not_flagged(self):
        text = 'look for phrases like "not my problem" and block the stop'
        assert find_shirking_phrase(text) is None

    def test_check_for_patterns_not_flagged(self):
        text = 'check for patterns like "was already failing" in the transcript'
        assert find_shirking_phrase(text) is None

    def test_detect_not_flagged(self):
        text = 'detecting "unrelated to our changes" in the recent transcript'
        assert find_shirking_phrase(text) is None

    def test_such_as_not_flagged(self):
        text = 'dismissive language such as "leave this for now" or "outside scope"'
        assert find_shirking_phrase(text) is None

    def test_real_shirking_still_flagged(self):
        # Bare shirking with no meta-description context still fires
        assert find_shirking_phrase("This failure is unrelated to our changes.") is not None

    def test_scan_for_real_match_after_window_still_flagged(self):
        # Meta-description context > 40 chars before the match — should still flag.
        # "was already failing before our changes" is a real pattern match that
        # appears far enough from the "scan for" cue to escape the negation window.
        prefix = "scan for signs it skipped work " + ("x" * 50) + " "
        text = prefix + "was already failing before our changes."
        assert find_shirking_phrase(text) is not None


class TestHookSignatureExpansion:
    def test_outcome_ownership_rule_name_skipped(self):
        # If an assistant message contains the rule file name, it's self-referential
        from validate_no_shirking import _HOOK_SIGNATURES
        assert "outcome-ownership.md" in _HOOK_SIGNATURES
        assert "validate_no_shirking" in _HOOK_SIGNATURES


# ---------------------------------------------------------------------------
# Blocker-bead escape (c3i clause b)
# ---------------------------------------------------------------------------
#
# Per claude/rules/continuation-harness.md: "documented failure is also an
# outcome." An agent that genuinely cannot proceed and FILES A BLOCKER BEAD
# documenting why has produced a legitimate, sanctioned outcome — NOT shirking.
# The gate must recognize this as a first-class, agent-invokable escape
# (gate-design.md Rule 1: Repair) so it does not force a user round-trip for a
# sanctioned terminal state.
#
# docs/reconciliation-rules.md § "Conflict 1" describes the intended shape:
# the gate is authoritative on "did the agent emit a shirking phrase" (a
# linguistic fact); it is NOT authoritative on "is this work blocked" (a
# task-state fact owned by beads). A filed blocker bead is the authoritative
# record that the work is blocked.
#
# The escape must be TIGHT: a passing mention of the word "blocker" must NOT
# disable the gate (no blanket bypass). The signal required is an actual
# blocker-bead filing — `bd create --type=bug ...`, "filed blocker bead",
# "blocker bead <id>", or a concrete bead id with blocker framing.


class TestBlockerBeadEscapeUnit:
    """Unit tests for the blocker-bead-filing detector."""

    def test_bd_create_bug_detected(self):
        from validate_no_shirking import filed_blocker_bead
        assert filed_blocker_bead(
            "I cannot proceed: missing prod credentials. "
            "bd create --type=bug --title 'sync blocked on creds' "
            "and bd update <id> --status=blocked."
        ) is True

    def test_filed_blocker_bead_phrase_detected(self):
        from validate_no_shirking import filed_blocker_bead
        assert filed_blocker_bead(
            "This is a pre-existing failure I cannot fix without schema access. "
            "I've filed a blocker bead documenting the obstacle."
        ) is True

    def test_blocker_bead_with_id_detected(self):
        from validate_no_shirking import filed_blocker_bead
        assert filed_blocker_bead(
            "Filed blocker bead cake-ta5.7 — needs a human decision on the API contract."
        ) is True

    def test_concrete_bead_id_with_blocker_framing_detected(self):
        from validate_no_shirking import filed_blocker_bead
        assert filed_blocker_bead(
            "Created claude-workflow-setup-z9q as a blocker documenting why this "
            "cannot be completed in this session."
        ) is True

    # --- Guard: NO blanket bypass on a passing mention of "blocker" ---

    def test_passing_mention_of_blocker_not_detected(self):
        from validate_no_shirking import filed_blocker_bead
        # The word "blocker" appears, but no bead was filed.
        assert filed_blocker_bead(
            "This was already failing before our changes; it's a real blocker for the release."
        ) is False

    def test_blocked_status_without_bead_not_detected(self):
        from validate_no_shirking import filed_blocker_bead
        assert filed_blocker_bead(
            "The pipeline is broken and I'm blocked on it, so I'll leave this for now."
        ) is False

    def test_clean_completion_text_not_detected(self):
        from validate_no_shirking import filed_blocker_bead
        assert filed_blocker_bead("All tests pass. Fixed the bug.") is False


class TestMainBlockerBeadEscape:
    """Integration: a filed blocker bead releases the Stop block end-to-end."""

    def test_shirking_with_blocker_bead_allows_stop(self):
        """Escape control: shirking phrase + filed blocker bead → NOT flagged."""
        transcript = _make_transcript(
            "This is a pre-existing failure in the auth module, unrelated to our "
            "changes, and I cannot fix it without prod credentials I don't have. "
            "I've filed a blocker bead (bd create --type=bug) documenting the obstacle."
        )
        try:
            denied = _run_main("Stop", transcript_path=transcript)
            assert denied is False
        finally:
            Path(transcript).unlink(missing_ok=True)

    def test_genuine_shirking_without_blocker_bead_still_blocks(self):
        """Negative control: shirking phrase, no blocker bead → STILL flagged."""
        transcript = _make_transcript(
            "This is a pre-existing failure unrelated to our changes. "
            "I'll leave it for now and move on."
        )
        try:
            denied = _run_main("Stop", transcript_path=transcript)
            assert denied is True
        finally:
            Path(transcript).unlink(missing_ok=True)

    def test_passing_blocker_mention_with_shirking_still_blocks(self):
        """Guard control: 'blocker' mentioned in passing, no bead → STILL flagged."""
        transcript = _make_transcript(
            "This was already failing before our changes; it's a real blocker for "
            "the release, but that's outside the scope of this task."
        )
        try:
            denied = _run_main("Stop", transcript_path=transcript)
            assert denied is True
        finally:
            Path(transcript).unlink(missing_ok=True)

    def test_blocker_bead_escape_on_pretooluse(self):
        """Escape applies on the PreToolUse (commit) path too."""
        transcript = _make_transcript(
            "The failure is unrelated to my changes and needs schema access I lack. "
            "Filed blocker bead claude-workflow-setup-z9q documenting why."
        )
        try:
            denied = _run_main(
                "PreToolUse", command="git commit -m 'wip'", transcript_path=transcript
            )
            assert denied is False
        finally:
            Path(transcript).unlink(missing_ok=True)


class TestMetaDiscussionGuard:
    """858.5 / design Step 3 — UNQUOTED discussion of the DETECTOR ITSELF is guarded,
    but a real deflection (even one that names the gate in an earlier clause/sentence)
    still fires. The negative controls are the load-bearing never-suppress oracle.
    """

    # --- meta-FP: naming the detector, unquoted, same clause ⇒ ALLOWED ---
    def test_detector_named_unquoted_allowed(self) -> None:
        assert find_shirking_match(
            "validate_no_shirking fired on my explanation of why a CI failure looked unrelated"
        ) is None

    def test_the_hook_fires_on_unrelated_allowed(self) -> None:
        assert find_shirking_match(
            "the hook fires on phrases about a CI failure being unrelated"
        ) is None

    def test_false_positive_keyword_match_allowed(self) -> None:
        assert find_shirking_match(
            "this looks like a false positive — the keyword match caught 'pre-existing failure'"
        ) is None

    # --- never-suppress negative controls: real deflection STILL fires ---
    def test_real_preexisting_deflection_still_fires(self) -> None:
        """NC-5: no detector-naming cue ⇒ genuine deflection is NOT laundered."""
        assert find_shirking_match("This is a pre-existing failure, not from my change") is not None

    def test_real_unrelated_deflection_still_fires(self) -> None:
        assert find_shirking_match("All three jobs died OOM, unrelated to my fix") is not None

    def test_mixed_meta_then_shirk_same_message_still_fires(self) -> None:
        """NC-6: discusses the gate AND then shirks in a LATER clause ⇒ still fires."""
        assert find_shirking_match(
            "the hook flags category words; anyway this is a pre-existing failure, not mine"
        ) is not None

    def test_prior_sentence_cue_does_not_launder_later_shirk(self) -> None:
        """A detector cue in an EARLIER sentence must not guard a later asserted shirk."""
        assert find_shirking_match(
            "the hook is fine. This is a pre-existing failure, not mine"
        ) is not None
        assert find_shirking_match(
            "I discussed validate_no_shirking earlier. This OOM is unrelated to my change"
        ) is not None


class TestInfrastructureBlamePrecision:
    """Live FP 2026-07-01 (cake xubhk): the bare noun-phrase patterns for
    infrastructure-blame ("deploy(ment)? bug", "CI issue", ...) matched OWNERSHIP
    statements ("fixed the deployment bug") and meta-mentions, looping the Stop gate.
    Blame requires the dismissive copula framing ("it's / looks like / probably an
    environment issue"), not the mere noun phrase.
    """

    # --- precision: ownership / neutral mentions must NOT fire ---
    def test_ownership_of_deployment_bug_allowed(self) -> None:
        assert find_shirking_match(
            "I fixed the deployment bug and redeployed; all checks are green."
        ) is None

    def test_live_cake_meta_message_allowed(self) -> None:
        """The verbatim production FP: meta-discussion of the gate's own re-fire."""
        assert find_shirking_match(
            'it keeps re-scanning that earlier "deployment bug" phrase and flagging it'
            " as infrastructure-blame. It's a genuine false positive"
        ) is None

    def test_owned_environment_issue_allowed(self) -> None:
        assert find_shirking_match(
            "The environment issue I introduced in the Dockerfile is fixed now."
        ) is None

    def test_debugging_ci_issue_allowed(self) -> None:
        assert find_shirking_match(
            "Root-caused and fixed the CI issue in our workflow config."
        ) is None

    # --- never-suppress: dismissive blame framing must STILL fire ---
    def test_copula_environment_issue_still_fires(self) -> None:
        assert find_shirking_match(
            "The failure is an environment issue with the runner image."
        ) is not None

    def test_looks_like_ci_issue_still_fires(self) -> None:
        assert find_shirking_match(
            "Looks like a CI issue, the tests pass locally."
        ) is not None

    def test_probably_deployment_issue_still_fires(self) -> None:
        assert find_shirking_match(
            "That's probably a deployment issue on the platform side."
        ) is not None

    def test_pipeline_is_flaky_still_fires(self) -> None:
        assert find_shirking_match(
            "The pipeline is flaky today, my change is fine."
        ) is not None


class TestBidirectionalStrongCueGuard:
    """858.5 follow-through: a detector-naming cue AFTER the match, in the SAME
    sentence-clause, also guards — the live loop's meta-messages put the cue after
    the quoted phrase. Sentence/clause breaks between match and cue still un-guard
    (never-suppress: trailing gate-talk cannot launder an asserted shirk).
    """

    def test_cue_after_match_same_clause_guards(self) -> None:
        assert find_shirking_match(
            "the agent wrote \"it's probably an environment issue\" and the hook"
            " flagged it as infrastructure-blame — a false positive"
        ) is None

    def test_category_label_after_match_guards(self) -> None:
        assert find_shirking_match(
            'that "unrelated to my change" phrase was flagged as attribution-deflection'
        ) is None

    def test_cue_in_next_sentence_does_not_guard(self) -> None:
        """NC: shirk asserted, THEN gate-talk in a new sentence ⇒ still fires."""
        assert find_shirking_match(
            "This is a pre-existing failure. The hook may flag this as a false positive."
        ) is not None

    def test_cue_after_clause_break_does_not_guard(self) -> None:
        assert find_shirking_match(
            "All three jobs died OOM, unrelated to my fix; the hook will disagree"
        ) is not None
