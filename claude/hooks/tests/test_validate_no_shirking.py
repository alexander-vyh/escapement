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
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

_hooks_dir = Path.home() / ".claude" / "hooks"
if not _hooks_dir.exists():
    pytest.skip("~/.claude/hooks/ not found", allow_module_level=True)

if str(_hooks_dir) not in sys.path:
    sys.path.insert(0, str(_hooks_dir))

from validate_no_shirking import (  # noqa: E402
    check_verification_evidence,
    find_shirking_phrase,
    read_recent_agent_text,
)


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

    def test_works_locally(self) -> None:
        assert find_shirking_phrase("It works fine locally") is not None

    def test_works_on_my_machine(self) -> None:
        assert find_shirking_phrase("It works on my machine") is not None

    def test_passes_locally(self) -> None:
        assert find_shirking_phrase("The test passes locally") is not None

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


class TestVerificationEvidence:
    """Tests for the verification-evidence gate on Stop."""

    def test_no_code_mod_allows(self) -> None:
        """No code modifications → nothing to verify → allow."""
        path = _make_tool_transcript([
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "1", "name": "Bash", "input": {"command": "ls -la"}}
            ]},
        ])
        try:
            assert check_verification_evidence(path) is None
        finally:
            Path(path).unlink(missing_ok=True)

    def test_code_mod_without_verification_blocks(self) -> None:
        """Edit tool used but no test run → should block."""
        path = _make_tool_transcript([
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "1", "name": "Edit", "input": {
                    "file_path": "foo.py", "old_string": "a", "new_string": "b"
                }}
            ]},
            {"role": "assistant", "content": [
                {"type": "text", "text": "Done! I've fixed the issue."}
            ]},
        ])
        try:
            result = check_verification_evidence(path)
            assert result is not None
            assert "verification" in result.lower() or "No" in result
        finally:
            Path(path).unlink(missing_ok=True)

    def test_code_mod_with_pytest_allows(self) -> None:
        """Edit followed by pytest → allow."""
        path = _make_tool_transcript([
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "1", "name": "Edit", "input": {
                    "file_path": "foo.py", "old_string": "a", "new_string": "b"
                }}
            ]},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "2", "name": "Bash", "input": {
                    "command": "pytest tests/ -v"
                }}
            ]},
        ])
        try:
            assert check_verification_evidence(path) is None
        finally:
            Path(path).unlink(missing_ok=True)

    def test_verification_before_code_mod_blocks(self) -> None:
        """Tests ran BEFORE the last edit → stale verification → block."""
        path = _make_tool_transcript([
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "1", "name": "Bash", "input": {
                    "command": "pytest tests/"
                }}
            ]},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "2", "name": "Edit", "input": {
                    "file_path": "foo.py", "old_string": "a", "new_string": "b"
                }}
            ]},
        ])
        try:
            result = check_verification_evidence(path)
            assert result is not None
        finally:
            Path(path).unlink(missing_ok=True)

    def test_user_approval_after_code_mod_allows(self) -> None:
        """User said 'yes' after code change → skip verification."""
        path = _make_tool_transcript([
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "1", "name": "Edit", "input": {
                    "file_path": "foo.py", "old_string": "a", "new_string": "b"
                }}
            ]},
            {"role": "user", "content": [
                {"type": "text", "text": "yes, that looks good, go ahead"}
            ]},
        ])
        try:
            assert check_verification_evidence(path) is None
        finally:
            Path(path).unlink(missing_ok=True)

    # --- docs/prose edits are NOT code modifications (false-positive fix) -----
    # Source: 2026-06-01 — validate_no_shirking fired "you modified code but
    # didn't verify" after a markdown-only memory edit. Mirrors the docs/prose
    # exemption in claude/rules/tdd-enforcement.md. Behavioral config stays
    # NON-exempt per that same rule.

    def test_docs_only_md_edit_allows(self) -> None:
        """NEGATIVE CONTROL (the bug): a markdown-only edit must not demand verification."""
        path = _make_tool_transcript([
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "1", "name": "Edit", "input": {
                    "file_path": "/Users/x/.claude/projects/p/memory/note.md",
                    "old_string": "a", "new_string": "b"
                }}
            ]},
            {"role": "assistant", "content": [
                {"type": "text", "text": "Updated the memory note."}
            ]},
        ])
        try:
            assert check_verification_evidence(path) is None, (
                "a markdown-only edit must not be treated as a code modification"
            )
        finally:
            Path(path).unlink(missing_ok=True)

    def test_write_prose_files_allow(self) -> None:
        """Write to .md / .txt / .rst docs → not a code mod."""
        for fp in ("README.md", "notes.txt", "guide.rst"):
            path = _make_tool_transcript([
                {"role": "assistant", "content": [
                    {"type": "tool_use", "id": "1", "name": "Write", "input": {
                        "file_path": fp, "content": "prose"
                    }}
                ]},
            ])
            try:
                assert check_verification_evidence(path) is None, (
                    f"Write to prose file {fp} must not require verification"
                )
            finally:
                Path(path).unlink(missing_ok=True)

    def test_docs_edit_then_code_edit_still_blocks(self) -> None:
        """POSITIVE CONTROL: a docs edit must not mask a later real code edit."""
        path = _make_tool_transcript([
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "1", "name": "Edit", "input": {
                    "file_path": "CHANGELOG.md", "old_string": "a", "new_string": "b"
                }}
            ]},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "2", "name": "Edit", "input": {
                    "file_path": "app.py", "old_string": "x", "new_string": "y"
                }}
            ]},
        ])
        try:
            assert check_verification_evidence(path) is not None, (
                "a real .py edit after a docs edit must still demand verification"
            )
        finally:
            Path(path).unlink(missing_ok=True)

    def test_behavioral_config_edit_still_blocks(self) -> None:
        """POSITIVE CONTROL: .yml CI config is NOT exempt (tdd-enforcement.md)."""
        path = _make_tool_transcript([
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "1", "name": "Edit", "input": {
                    "file_path": ".github/workflows/ci.yml", "old_string": "a", "new_string": "b"
                }}
            ]},
        ])
        try:
            assert check_verification_evidence(path) is not None, (
                "behavioral config must still require verification — only prose/docs is exempt"
            )
        finally:
            Path(path).unlink(missing_ok=True)

    def test_nonexistent_transcript_allows(self) -> None:
        assert check_verification_evidence("/tmp/nonexistent_xyzzy.jsonl") is None

    def test_write_tool_detected_as_code_mod(self) -> None:
        """Write tool should count as code modification."""
        path = _make_tool_transcript([
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "1", "name": "Write", "input": {
                    "file_path": "new_file.py", "content": "print('hello')"
                }}
            ]},
        ])
        try:
            assert check_verification_evidence(path) is not None
        finally:
            Path(path).unlink(missing_ok=True)

    def test_serena_replace_detected_as_code_mod(self) -> None:
        """Serena symbol replacement should count as code modification."""
        path = _make_tool_transcript([
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "1", "name": "mcp__serena__replace_symbol_body", "input": {
                    "symbol": "foo", "body": "new body"
                }}
            ]},
        ])
        try:
            assert check_verification_evidence(path) is not None
        finally:
            Path(path).unlink(missing_ok=True)

    def test_rspec_counts_as_verification(self) -> None:
        path = _make_tool_transcript([
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "1", "name": "Edit", "input": {
                    "file_path": "foo.rb", "old_string": "a", "new_string": "b"
                }}
            ]},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "2", "name": "Bash", "input": {
                    "command": "bundle exec rspec spec/"
                }}
            ]},
        ])
        try:
            assert check_verification_evidence(path) is None
        finally:
            Path(path).unlink(missing_ok=True)

    def test_uv_run_pytest_counts_as_verification(self) -> None:
        path = _make_tool_transcript([
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "1", "name": "Edit", "input": {
                    "file_path": "foo.py", "old_string": "a", "new_string": "b"
                }}
            ]},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "2", "name": "Bash", "input": {
                    "command": "uv run pytest tests/ -v"
                }}
            ]},
        ])
        try:
            assert check_verification_evidence(path) is None
        finally:
            Path(path).unlink(missing_ok=True)

    def test_just_test_counts_as_verification(self) -> None:
        path = _make_tool_transcript([
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "1", "name": "Edit", "input": {
                    "file_path": "foo.py", "old_string": "a", "new_string": "b"
                }}
            ]},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "2", "name": "Bash", "input": {
                    "command": "just test"
                }}
            ]},
        ])
        try:
            assert check_verification_evidence(path) is None
        finally:
            Path(path).unlink(missing_ok=True)

    def test_just_check_counts_as_verification(self) -> None:
        path = _make_tool_transcript([
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "1", "name": "Edit", "input": {
                    "file_path": "foo.py", "old_string": "a", "new_string": "b"
                }}
            ]},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "2", "name": "Bash", "input": {
                    "command": "just check"
                }}
            ]},
        ])
        try:
            assert check_verification_evidence(path) is None
        finally:
            Path(path).unlink(missing_ok=True)

    def test_ruff_check_counts_as_verification(self) -> None:
        path = _make_tool_transcript([
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "1", "name": "Edit", "input": {
                    "file_path": "foo.py", "old_string": "a", "new_string": "b"
                }}
            ]},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "2", "name": "Bash", "input": {
                    "command": "ruff check src/"
                }}
            ]},
        ])
        try:
            assert check_verification_evidence(path) is None
        finally:
            Path(path).unlink(missing_ok=True)

    def test_multiple_edits_last_matters(self) -> None:
        """Multiple edits — verification must come after the LAST one."""
        path = _make_tool_transcript([
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "1", "name": "Edit", "input": {
                    "file_path": "foo.py", "old_string": "a", "new_string": "b"
                }}
            ]},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "2", "name": "Bash", "input": {
                    "command": "pytest tests/"
                }}
            ]},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "3", "name": "Edit", "input": {
                    "file_path": "bar.py", "old_string": "x", "new_string": "y"
                }}
            ]},
        ])
        try:
            result = check_verification_evidence(path)
            assert result is not None  # Verification was before the last edit
        finally:
            Path(path).unlink(missing_ok=True)

    def test_only_text_no_tools_allows(self) -> None:
        """Transcript with only text messages — no code mods, no block."""
        path = _make_tool_transcript([
            {"role": "assistant", "content": [
                {"type": "text", "text": "Here's my analysis of the code."}
            ]},
            {"role": "user", "content": [
                {"type": "text", "text": "Thanks!"}
            ]},
        ])
        try:
            assert check_verification_evidence(path) is None
        finally:
            Path(path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Integration: verification gate in main() Stop flow
# ---------------------------------------------------------------------------


class TestMainStopVerification:
    """Integration tests for Phase 2 (verification) in the Stop event."""

    def test_stop_with_unverified_edit_blocks(self) -> None:
        """Agent edited code but never ran tests → Stop should block."""
        path = _make_tool_transcript([
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "1", "name": "Edit", "input": {
                    "file_path": "foo.py", "old_string": "a", "new_string": "b"
                }}
            ]},
            {"role": "assistant", "content": [
                {"type": "text", "text": "All done, the fix is in place."}
            ]},
        ])
        try:
            denied = _run_main("Stop", transcript_path=path)
            assert denied is True
        finally:
            Path(path).unlink(missing_ok=True)

    def test_stop_with_verified_edit_allows(self) -> None:
        """Agent edited code AND ran tests → Stop should allow."""
        path = _make_tool_transcript([
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "1", "name": "Edit", "input": {
                    "file_path": "foo.py", "old_string": "a", "new_string": "b"
                }}
            ]},
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "2", "name": "Bash", "input": {
                    "command": "pytest tests/ -v"
                }}
            ]},
            {"role": "assistant", "content": [
                {"type": "text", "text": "All tests pass."}
            ]},
        ])
        try:
            denied = _run_main("Stop", transcript_path=path)
            assert denied is False
        finally:
            Path(path).unlink(missing_ok=True)

    def test_stop_no_edits_allows(self) -> None:
        """No code modifications → Stop should allow."""
        path = _make_tool_transcript([
            {"role": "assistant", "content": [
                {"type": "text", "text": "The architecture looks sound."}
            ]},
        ])
        try:
            denied = _run_main("Stop", transcript_path=path)
            assert denied is False
        finally:
            Path(path).unlink(missing_ok=True)

    def test_pretooluse_skips_verification(self) -> None:
        """Verification gate only fires on Stop, not PreToolUse."""
        path = _make_tool_transcript([
            {"role": "assistant", "content": [
                {"type": "tool_use", "id": "1", "name": "Edit", "input": {
                    "file_path": "foo.py", "old_string": "a", "new_string": "b"
                }}
            ]},
            {"role": "assistant", "content": [
                {"type": "text", "text": "Committing the fix."}
            ]},
        ])
        try:
            # PreToolUse for git commit — no shirking, no verification gate
            denied = _run_main("PreToolUse", command="git commit -m 'fix'", transcript_path=path)
            assert denied is False
        finally:
            Path(path).unlink(missing_ok=True)


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
        from validate_no_shirking import read_recent_messages, _HOOK_SIGNATURES
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
