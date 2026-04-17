#!/usr/bin/env python3
"""Claude Code hook: block outcome-shirking ("pre-existing failure" evasion).

Fires as:
  • PreToolUse  — on git commit / gh pr create / git push
  • Stop        — when the agent declares itself done

When the agent recently used dismissive language about test/job failures
("pre-existing", "not in anything I changed", "unrelated to our changes"),
this hook blocks the finishing action and forces the agent to either:
  1. Fix the failing test/job, OR
  2. Obtain explicit user approval to proceed with a known failure.

Input (via stdin):
  JSON with hook_event_name, tool_name, tool_input, transcript_path
Exit codes:
  0 — allow
  2 — block (JSON output explains why)
"""

import json
import re
import sys
from pathlib import Path
from typing import NoReturn

# ---------------------------------------------------------------------------
# Shirking patterns — all case-insensitive
# ---------------------------------------------------------------------------
_PATTERNS: list[str] = [
    # Classic "pre-existing" language
    r"pre[- ]?existing\s+(?:failure|issue|bug|problem|test|error)",
    r"(?:appears?|seems?|looks?|is)\s+(?:to\s+be\s+)?a\s+pre[- ]?existing",
    r"(?:let\s+me\s+check|check(?:ing)?)\s+if\s+(?:this\s+is\s+)?(?:a\s+)?pre[- ]?existing",
    # "not in anything I changed / touched"
    r"not\s+in\s+anything\s+I\s+(?:changed|modified|touched|wrote)",
    r"not\s+in\s+(?:the\s+)?(?:files?|code)\s+I\s+(?:changed|modified|touched)",
    # "unrelated" — only in dismissive contexts (not bare "unrelated modules" etc.)
    r"\bunrelated\s+(?:to\s+(?:this|the|my|our)|issue|bug|problem|failure|change)\b",
    r"\bnot\s+related\s+(?:to\s+(?:this|the|my|our)|issue|bug|problem|failure|change)\b",
    r"not\s+(?:related|relevant)\s+to\s+(?:our|my|this|the)\s+changes?",
    r"not\s+(?:caused\s+by|from|part\s+of)\s+(?:our|my|this|the)\s+changes?",
    # "was already failing / broken"
    r"was\s+already\s+(?:failing|broken)",
    r"(?:failing|failed|broken)\s+before\s+(?:our|my|this|the)\s+changes?",
    r"(?:failing|failed|broken)\s+(?:before|prior\s+to)\s+(?:my|our|this)",
    # "completely different problem" / "separate issue from …"
    r"completely\s+different\s+(?:problem|issue|bug|failure)",
    r"separate\s+(?:issue|problem|bug|failure)\s+(?:from|to|than)",
    # "I didn't change/touch that test file"
    r"I\s+didn['\u2019]?t\s+(?:change|touch|modify|write|create)\s+.{1,80}(?:test|file|module)",
    r"didn['\u2019]?t\s+touch\s+.{1,80}(?:test|file|module)",
    # "test failure is unrelated"
    r"test\s+(?:failure|error)\s+(?:is|was|seems?|appears?)\s+(?:unrelated|separate|not\s+related)",
    # Attribution deflection
    r"not\s+(?:my|our)\s+(?:problem|issue|fault|change|doing|code|responsibility|bug|job|concern|area)",
    r"(?:that['\u2019]?s|this\s+is)\s+(?:a\s+)?(?:separate|different|unrelated)\s+(?:bug|issue|problem|failure)",
    # Acceptance evasion — explicitly deciding to live with failures and move on
    r"note\s+(?:this\s+|it\s+)?and\s+move\s+(?:on|past)",
    r"just\s+accept\s+the\s+(?:errors?|failures?|issues?)",
    r"accept\s+the\s+(?:errors?|failures?|issues?)\s+until",
    # Infrastructure / CI blame — externalizing to other systems
    r"CI\s+(?:infra(?:structure)?\s+)?(?:issue|problem|failure|error|bug)",
    r"(?:infra(?:structure)?|pipeline|build\s+system|environment|deploy(?:ment)?|runner)\s+(?:issue|problem|failure|error|bug)",
    r"(?:the\s+)?(?:CI|pipeline|build|runner)\s+(?:is|seems?|appears?)\s+(?:broken|flaky|unstable|down)",
    # "works locally" — implying the problem is elsewhere
    r"works?\s+(?:fine\s+)?(?:locally|on\s+(?:my|our)\s+(?:machine|environment|setup|end))",
    r"pass(?:es|ing)?\s+(?:fine\s+)?locally",
    # Deferral — punting to future work instead of fixing now
    r"(?:needs?|requires?)\s+(?:a\s+)?separate\s+(?:investigation|fix|ticket|PR|issue|effort|task|attention)",
    r"(?:can|will|should)\s+(?:be\s+)?(?:fixed|addressed|resolved|handled|investigated)\s+(?:later|separately|in\s+(?:a\s+)?(?:follow[- ]?up|separate|different|another))",
    r"(?:leav(?:e|ing)|left)\s+(?:this|that|it)\s+(?:for\s+now|as[- ]?is|alone)",
    # Scope limitation
    r"(?:outside|beyond|out\s+of)\s+(?:the\s+)?scope(?:\s+of)?",
    # Dismissing as flaky / known
    r"(?:it'?s|that'?s|this\s+is|just)\s+(?:an?\s+)?(?:flaky|intermittent|transient|sporadic)\s+(?:test|failure|check|build)",
    r"(?:this\s+is|that'?s|it'?s)\s+a\s+(?:known|existing|tracked)\s+(?:issue|bug|problem)",
]

COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in _PATTERNS]

# Bash commands that represent "I'm done" — trigger the PreToolUse path
FINISHING_COMMANDS = ["git commit", "gh pr create", "gh pr merge", "git push"]

# How far back in the transcript to look (characters)
TRANSCRIPT_WINDOW = 25_000

# Signatures of this hook's own block messages AND meta-discussion about the hook.
# Messages containing any of these are skipped to prevent self-referential triggers
# (e.g., the agent quoting or explaining the hook's behavior).
_HOOK_SIGNATURES = frozenset({
    "OUTCOME OWNERSHIP VIOLATION",
    "VERIFICATION REQUIRED",
    "FIX THE FAILURES NOW:",
    "RUN VERIFICATION NOW:",
})

# ---------------------------------------------------------------------------
# User approval patterns — detect when the user explicitly said "go ahead"
# (The hook tells agents to "obtain explicit user approval", so we must
#  honour that approval when we see it.)
# ---------------------------------------------------------------------------
_APPROVAL_PATTERNS: list[str] = [
    r"\byes\b",
    r"\bapproved?\b",
    r"\bproceed\b",
    r"\bgo\s+ahead\b",
    r"\blgtm\b",
    r"\bthat'?s\s+(?:fine|ok(?:ay)?)\b",
]
_COMPILED_APPROVAL = [re.compile(p, re.IGNORECASE) for p in _APPROVAL_PATTERNS]


# ---------------------------------------------------------------------------
# Verification evidence (Level 3: require proof of outcome)
# ---------------------------------------------------------------------------

_CODE_MOD_TOOLS = frozenset({
    "Edit", "Write", "NotebookEdit",
    "mcp__serena__replace_symbol_body",
    "mcp__serena__insert_after_symbol",
    "mcp__serena__insert_before_symbol",
    "mcp__serena__rename_symbol",
})

_VERIFICATION_COMMANDS: list[str] = [
    r"\bpytest\b",
    r"\brspec\b",
    r"\bjest\b",
    r"\bmocha\b",
    r"\bvitest\b",
    r"\bcargo\s+test\b",
    r"\bgo\s+test\b",
    r"\bnpm\s+test\b",
    r"\bnpm\s+run\s+test",
    r"\byarn\s+test\b",
    r"\bpnpm\s+test\b",
    r"\bmake\s+test\b",
    r"\bjust\s+test\b",
    r"\bjust\s+check\b",
    r"\bjust\s+smoke\b",
    r"\bbundle\s+exec\s+rspec\b",
    r"\buv\s+run\s+pytest\b",
    r"\bdotnet\s+test\b",
    r"\bruff\s+check\b",
    r"\bmypy\b",
    r"\bpyright\b",
    r"\btsc\b",
    r"\beslint\b",
    r"\brubocop\b",
    r"\bflake8\b",
    r"\bjust\s+pre-commit\b",
    r"\bjust\s+fix\b",
]

_COMPILED_VERIFICATION = [re.compile(p, re.IGNORECASE) for p in _VERIFICATION_COMMANDS]


_VERIFICATION_BLOCK = """\
🔍 VERIFICATION REQUIRED — you modified code but didn't verify the outcome.

{reason}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RUN VERIFICATION NOW:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Run the test suite or relevant verification command
2. Confirm it produces the expected result
3. If tests fail — fix them, don't dismiss them
4. Then you may stop

Do NOT stop without running tests after code changes.\
"""


def _deny_verification(reason: str) -> dict:
    # Verification gate only fires on Stop — use top-level format
    return {
        "decision": "block",
        "reason": _VERIFICATION_BLOCK.format(reason=reason),
    }


def block_verification(reason: str) -> NoReturn:
    print(json.dumps(_deny_verification(reason)))
    sys.exit(2)


def check_verification_evidence(transcript_path: str) -> str | None:
    """Check that code modifications were followed by verification or user approval.

    Returns None if OK (no code mods, verification ran, or user approved).
    Returns a reason string if verification is missing.
    """
    path = Path(transcript_path)
    if not path.exists():
        return None

    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    tail = raw[-TRANSCRIPT_WINDOW:] if len(raw) > TRANSCRIPT_WINDOW else raw

    last_code_mod_line = -1
    last_verification_line = -1
    last_user_approval_line = -1

    for line_num, line in enumerate(tail.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg = entry.get("message", entry)
        if not isinstance(msg, dict):
            continue

        role = msg.get("role", "")
        content = msg.get("content", [])

        if role == "assistant" and isinstance(content, list):
            for blk in content:
                if not isinstance(blk, dict) or blk.get("type") != "tool_use":
                    continue
                tool_name = blk.get("name", "")
                tool_input = blk.get("input", {})
                if tool_name in _CODE_MOD_TOOLS:
                    last_code_mod_line = line_num
                elif tool_name == "Bash" and isinstance(tool_input, dict):
                    cmd = tool_input.get("command", "")
                    if any(p.search(cmd) for p in _COMPILED_VERIFICATION):
                        last_verification_line = line_num

        elif role == "user":
            text_parts: list[str] = []
            if isinstance(content, str):
                text_parts.append(content)
            elif isinstance(content, list):
                for blk in content:
                    if isinstance(blk, dict) and blk.get("type") == "text":
                        text_parts.append(blk.get("text", ""))
                    elif isinstance(blk, str):
                        text_parts.append(blk)
            text = " ".join(text_parts)
            if any(ap.search(text) for ap in _COMPILED_APPROVAL):
                last_user_approval_line = line_num

    if last_code_mod_line < 0:
        return None  # No code modifications — nothing to verify

    if last_verification_line > last_code_mod_line:
        return None  # Verification ran after last code mod

    if last_user_approval_line > last_code_mod_line:
        return None  # User approved after last code mod

    if last_verification_line < 0:
        return "No verification commands were run after code modifications."

    return "Code was modified after the last verification run — re-verify."


# ---------------------------------------------------------------------------
# Transcript reading
# ---------------------------------------------------------------------------

def read_recent_agent_text(transcript_path: str) -> str:
    """Extract text from recent assistant turns in the JSONL transcript."""
    path = Path(transcript_path)
    if not path.exists():
        return ""

    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""

    tail = raw[-TRANSCRIPT_WINDOW:] if len(raw) > TRANSCRIPT_WINDOW else raw

    chunks: list[str] = []
    for line in tail.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            # Non-JSON line — include as-is; pattern may appear in raw text
            chunks.append(line)
            continue

        # Support both {"type":"assistant","message":{…}} and {"role":"assistant",…}
        msg = entry.get("message", entry)
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue

        content = msg.get("content", [])
        if isinstance(content, str):
            chunks.append(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    chunks.append(block.get("text", ""))
                elif isinstance(block, str):
                    chunks.append(block)

    return "\n".join(chunks)


def read_recent_messages(transcript_path: str) -> list[tuple[str, str]]:
    """Extract (role, text) pairs from recent transcript entries, in order.

    Unlike read_recent_agent_text, this preserves *both* assistant and user
    messages so we can detect user approval after a shirking phrase.
    """
    path = Path(transcript_path)
    if not path.exists():
        return []

    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    tail = raw[-TRANSCRIPT_WINDOW:] if len(raw) > TRANSCRIPT_WINDOW else raw

    messages: list[tuple[str, str]] = []
    for line in tail.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg = entry.get("message", entry)
        if not isinstance(msg, dict):
            continue

        role = msg.get("role", "")
        if role not in ("assistant", "user"):
            continue

        text_parts: list[str] = []
        content = msg.get("content", [])
        if isinstance(content, str):
            text_parts.append(content)
        elif isinstance(content, list):
            for blk in content:
                if isinstance(blk, dict) and blk.get("type") == "text":
                    text_parts.append(blk.get("text", ""))
                elif isinstance(blk, str):
                    text_parts.append(blk)

        if text_parts:
            messages.append((role, "\n".join(text_parts)))

    return messages


# ---------------------------------------------------------------------------
# Code-block stripping — avoid false positives from quoted code/patterns
# ---------------------------------------------------------------------------

_FENCED_BLOCK = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_INLINE_CODE = re.compile(r"`[^`]+`")


def _strip_code_spans(text: str) -> str:
    """Remove fenced code blocks and inline code spans from text."""
    text = _FENCED_BLOCK.sub("", text)
    text = _INLINE_CODE.sub("", text)
    return text


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def find_shirking_phrase(text: str) -> str | None:
    """Return a context snippet around the first shirking match, or None."""
    stripped = _strip_code_spans(text)
    for pattern in COMPILED_PATTERNS:
        m = pattern.search(stripped)
        if m:
            start = max(0, m.start() - 40)
            end = min(len(stripped), m.end() + 80)
            return stripped[start:end].strip()
    return None


# ---------------------------------------------------------------------------
# Blocking
# ---------------------------------------------------------------------------

_BLOCK_BODY = """\
🚨 OUTCOME OWNERSHIP VIOLATION — you dismissed failures instead of fixing them.

You said something like:
  «{phrase}»

"Pre-existing" is not an excuse. "Not my code" is not an excuse.
You own the OUTCOME, not just your diff.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FIX THE FAILURES NOW:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. Run the failing test(s) to see the actual errors
2. Read the failing test code to understand what it expects
3. Fix the code or the test — whichever is wrong
4. Re-run until green
5. Then you may stop

Do NOT punt failures to the user — fix them yourself.
Do NOT rephrase the problem and try to stop again.
Do NOT move on to other work — fix THIS first.

You may ONLY stop without fixing if you are genuinely blocked
on something you cannot solve (missing credentials, need
infrastructure access, need a human decision about product
requirements). Test failures are never that.\
"""


def _deny_output(event_name: str, phrase: str) -> dict:
    reason = _BLOCK_BODY.format(phrase=phrase)
    if event_name == "PreToolUse":
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
    # Stop events use top-level decision/reason
    return {
        "decision": "block",
        "reason": reason,
    }


def block(event_name: str, phrase: str) -> NoReturn:
    print(json.dumps(_deny_output(event_name, phrase)))
    sys.exit(2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0

    # Prevent infinite loops: if a Stop hook already triggered continuation, allow stop
    if data.get("stop_hook_active"):
        return 0

    hook_event = data.get("hook_event_name", "") or data.get("hookEventName", "")
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
    transcript_path = data.get("transcript_path", "")

    # Decide whether this invocation is relevant
    if hook_event == "PreToolUse":
        if tool_name != "Bash":
            return 0
        if not any(cmd in command for cmd in FINISHING_COMMANDS):
            return 0
    elif hook_event == "Stop":
        pass  # always check
    else:
        return 0

    if not transcript_path:
        return 0

    # ── Phase 1: Shirking phrase detection ────────────────────────────────
    messages = read_recent_messages(transcript_path)

    if messages:
        last_shirking_idx: int | None = None
        last_shirking_phrase: str | None = None

        for i, (role, text) in enumerate(messages):
            if role != "assistant":
                continue
            # Skip messages that quote this hook's own block output —
            # otherwise the hook permanently poisons its own transcript.
            if any(sig in text for sig in _HOOK_SIGNATURES):
                continue
            phrase = find_shirking_phrase(text)
            if phrase:
                last_shirking_idx = i
                last_shirking_phrase = phrase

        if last_shirking_phrase is not None:
            # Check for user approval after the last shirking phrase
            approved = False
            for i in range(last_shirking_idx + 1, len(messages)):
                role, text = messages[i]
                if role == "user":
                    for ap in _COMPILED_APPROVAL:
                        if ap.search(text):
                            approved = True
                            break
                    if approved:
                        break

            if not approved:
                block(hook_event, last_shirking_phrase)

    # ── Phase 2: Verification evidence (Stop only) ────────────────────────
    if hook_event == "Stop":
        verification_issue = check_verification_evidence(transcript_path)
        if verification_issue:
            block_verification(verification_issue)

    return 0


if __name__ == "__main__":
    sys.exit(main())
