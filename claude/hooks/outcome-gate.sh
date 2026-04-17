#!/bin/bash
# DEPRECATED 2026-03-12 — superseded by validate_no_shirking.py
# That hook now covers all patterns from this script plus:
#   - Infrastructure/CI blame, deferral, scope limitation, flaky/known dismissal
#   - Verification evidence gate (requires tests after code modifications)
# Kept for reference only. Removed from settings.json Stop hooks.
#
# Original purpose:
# outcome-gate.sh — Stop hook that catches blame-shifting and premature completion
# Fires when the agent tries to stop responding. Blocks if the agent appears to be
# declaring done while attributing issues to other code.

INPUT=$(cat)

# Safety: if stop hook already triggered continuation, allow stopping to prevent loops
STOP_HOOK_ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active // false')
if [ "$STOP_HOOK_ACTIVE" = "true" ]; then
  exit 0
fi

# Read the transcript to get the last assistant message
TRANSCRIPT=$(echo "$INPUT" | jq -r '.transcript_path // empty')
if [ -z "$TRANSCRIPT" ] || [ ! -f "$TRANSCRIPT" ]; then
  exit 0  # Can't read transcript, allow stop
fi

# Extract the last assistant message text from the JSONL transcript
# Look at last 50 lines to catch the most recent assistant turn
LAST_MSG=$(tail -50 "$TRANSCRIPT" | \
  jq -r 'select(.type == "assistant") | .message.content[]? | select(.type == "text") | .text' 2>/dev/null | \
  tail -1)

if [ -z "$LAST_MSG" ]; then
  exit 0  # No message found, allow stop
fi

# Check for blame-shifting / scope-limiting patterns
# These are phrases that indicate the agent is drawing a line around "its" work
# instead of owning the full outcome
PATTERNS=(
  "pre-existing"
  "not from this change"
  "not related to (this|our|my) change"
  "completely different problem"
  "a different (issue|problem|bug)"
  "separate (issue|problem|bug)"
  "out of scope"
  "beyond the scope"
  "not (my|our) (problem|issue|responsibility)"
  "someone else"
  "existing (issue|bug|problem)"
  "unrelated (issue|bug|problem|to)"
  "that's a .* problem"
  "exposed a .* bug"
)

COMBINED=$(printf "%s|" "${PATTERNS[@]}")
COMBINED=${COMBINED%|}  # Remove trailing pipe

if echo "$LAST_MSG" | grep -qiE "$COMBINED"; then
  echo "OUTCOME GATE: Your last response contains language that distances you from the outcome (blame-shifting, scope-limiting, or attributing issues to other code). The user wants the actual business outcome delivered. If something blocks that outcome — regardless of whose code the bug is in — fix it and keep working. Do not declare done until the desired outcome is actually happening." >&2
  exit 2
fi

exit 0
