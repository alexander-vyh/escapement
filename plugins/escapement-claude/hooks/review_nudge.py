#!/usr/bin/env python3
"""Claude Code hook: nudge toward /review when a prompt looks like a review request.

Fires on UserPromptSubmit. If the prompt contains review-intent language
(e.g., "review this PR", "code review", "look at this PR"), emits a
systemMessage suggesting /review or manual team dispatch. Advisory only.

Input (via stdin):
  JSON with hook_event_name, session_id, user_prompt
Exit codes:
  0 — always (advisory only, never blocks)
"""

import json
import re
import sys


# ---------------------------------------------------------------------------
# Review-intent detection
# ---------------------------------------------------------------------------

# Word-boundary patterns that signal a review request.
# Using \b to avoid false positives like "preview", "reviewer" in unrelated contexts.
REVIEW_PATTERNS = [
    re.compile(r'\breview\b', re.IGNORECASE),
    re.compile(r'\bPR\b'),                          # case-sensitive — "PR" is an acronym
    re.compile(r'\bpull\s+request\b', re.IGNORECASE),
    re.compile(r'\bcode\s+review\b', re.IGNORECASE),
    re.compile(r'\bcheck\s+this\b', re.IGNORECASE),
    re.compile(r'\blook\s+at\s+this\s+PR\b', re.IGNORECASE),
    re.compile(r'\breview\s+#\d+', re.IGNORECASE),
]

# Phrases that look like review language but are not review requests.
# These are checked as substrings (lowercased) before pattern matching.
FALSE_POSITIVE_NOISE = [
    "preview",
    "in review",          # status report, not a request
    "peer review process", # discussing process
    "/review",            # already invoking the skill — don't double-nudge
]

NUDGE_MESSAGE = (
    "Review request detected. Consider using /review to dispatch parallel "
    "review agents, or dispatch a team manually with adversarial-reviewer "
    "+ test-quality-reviewer."
)


def looks_like_review_request(prompt: str) -> bool:
    """Return True if the prompt appears to be asking for code review."""
    stripped = prompt.strip()

    # Too short — likely a bare "/review" command or fragment
    if len(stripped) < 10:
        return False

    lower = stripped.lower()

    # Check for false-positive noise
    for noise in FALSE_POSITIVE_NOISE:
        if noise in lower:
            return False

    # Check for review-intent patterns
    for pattern in REVIEW_PATTERNS:
        if pattern.search(stripped):
            return True

    return False


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    hook_event = data.get("hook_event_name", "") or data.get("hookEventName", "")
    if hook_event != "UserPromptSubmit":
        return 0

    prompt = (
        data.get("user_prompt", "")
        or data.get("tool_input", {}).get("prompt", "")
    )
    if not prompt:
        return 0

    if not looks_like_review_request(prompt):
        return 0

    # Emit advisory system message
    json.dump({"systemMessage": NUDGE_MESSAGE}, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
