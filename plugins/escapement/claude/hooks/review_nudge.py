#!/usr/bin/env python3
"""UserPromptSubmit hook: nudge toward /review when a prompt looks like a review request.

Fires on UserPromptSubmit (Claude Code, Codex; Pi runs it at before_agent_start).
If the prompt contains review-intent language (e.g., "review this PR", "code
review", "look at this PR"), it adds a nudge suggesting /review or manual team
dispatch to the turn's context. Advisory only.

Every host sends the prompt as the top-level `prompt` field and hands
`hookSpecificOutput.additionalContext` to the model; `systemMessage` alone only
reaches the user. This hook used to read `user_prompt`, so it never fired.

Input (via stdin):
  JSON with hook_event_name, prompt
Exit codes:
  0 — always (advisory only, never blocks)
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _host_output  # noqa: E402


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

    prompt = data.get("prompt")
    if not isinstance(prompt, str) or not prompt:
        return 0

    if not looks_like_review_request(prompt):
        return 0

    print(json.dumps(_host_output.advisory(NUDGE_MESSAGE, "UserPromptSubmit")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
