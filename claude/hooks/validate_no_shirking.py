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

# Shared signal capture per claude/rules/gate-design.md Rule 2.
sys.path.insert(0, str(Path(__file__).parent))
try:
    from _gate_signal import record as _record_signal
except ImportError:  # pragma: no cover
    def _record_signal(*_args, **_kwargs) -> None:
        return None

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

# Categories aligned by index with _PATTERNS. Used by the denial to name
# *which kind* of shirking matched and by gate_signal_query.py to count
# fire frequency per category (the half-life mechanism per gate-design.md
# Operating Rule 1: query the signal log to see which patterns fire most
# and prune the dead ones).
_CATEGORIES: list[str] = [
    "pre-existing",            # pre-existing failure/issue/bug...
    "pre-existing",            # appears to be a pre-existing
    "pre-existing",            # checking if this is pre-existing
    "attribution-deflection",  # not in anything I changed
    "attribution-deflection",  # not in the files I changed
    "unrelated",               # unrelated to this/my/our
    "unrelated",               # not related to ...
    "unrelated",               # not related/relevant to our changes
    "unrelated",               # not caused by our changes
    "pre-existing",            # was already failing/broken
    "pre-existing",            # failing before our changes
    "pre-existing",            # failing prior to my
    "unrelated",               # completely different problem
    "unrelated",               # separate issue from/to/than
    "attribution-deflection",  # I didn't change/touch ...
    "attribution-deflection",  # didn't touch ...
    "unrelated",               # test failure is unrelated
    "attribution-deflection",  # not my/our problem/issue/...
    "unrelated",               # that's a separate/different/unrelated bug
    "acceptance-evasion",      # note this and move on
    "acceptance-evasion",      # just accept the errors
    "acceptance-evasion",      # accept the errors until
    "infrastructure-blame",    # CI issue/problem/...
    "infrastructure-blame",    # infra/pipeline/build/environment issue
    "infrastructure-blame",    # CI/pipeline/build/runner is broken/flaky
    "infrastructure-blame",    # works locally
    "infrastructure-blame",    # passes locally
    "deferral",                # needs separate investigation/fix/...
    "deferral",                # will be fixed later/separately
    "deferral",                # leaving this for now / as-is
    "scope-limitation",        # outside/beyond/out of scope
    "dismissal",               # it's a flaky test/failure
    "dismissal",               # this is a known/existing/tracked issue
]

# Sanity check: categories must align with patterns. This is a startup
# assertion — if someone edits one list without the other, the hook
# fails loudly rather than silently miscategorizing.
assert len(_CATEGORIES) == len(_PATTERNS), (
    f"_CATEGORIES ({len(_CATEGORIES)}) must align with _PATTERNS ({len(_PATTERNS)})"
)

# Map each category to a one-line description used in the denial,
# pointing the agent at where the rationale lives.
_CATEGORY_RATIONALE: dict[str, str] = {
    "pre-existing": "claiming a failure pre-dates your change deflects ownership; even if true, the failure is in your delivery window now.",
    "attribution-deflection": "'I didn't touch that' deflects ownership; if the failure surfaces from your work, it's yours to either fix or escalate.",
    "unrelated": "declaring a failure unrelated assumes the boundary you're drawing is the boundary that matters.",
    "infrastructure-blame": "blaming CI / pipeline / 'works locally' externalizes a problem the outcome still requires resolved.",
    "deferral": "punting to 'later' or a 'separate ticket' is wind-down disguised as scoping.",
    "scope-limitation": "'out of scope' is a real defense sometimes — but only if the genuinely-out-of-scope work was filed; otherwise it's deferral.",
    "acceptance-evasion": "explicitly choosing to live with failures is the most direct form of the anti-pattern.",
    "dismissal": "'flaky' or 'known issue' may be true, but the burden is on you to confirm — not assume.",
}

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
    # Self-referential names: a message that mentions this hook or the rule
    # file it enforces is discussing the gate, not shirking through it.
    "outcome-ownership.md",
    "validate_no_shirking",
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
_TILDE_FENCE = re.compile(r"~~~[\s\S]*?~~~", re.MULTILINE)
_INLINE_CODE = re.compile(r"`[^`]+`")
# Quoting/example markup: content the agent is showing or that the harness
# injected, not asserting. Strip the whole tagged span (and its contents) so a
# shirking phrase quoted as an example or inside a system reminder does not fire.
_QUOTED_TAGS = re.compile(
    r"<(system-reminder|example)>[\s\S]*?</\1>",
    re.IGNORECASE,
)


def _strip_code_spans(text: str) -> str:
    """Remove fenced code blocks, inline code spans, and quoted markup.

    Both ``` and ~~~ fences are stripped, along with the contents of
    <system-reminder> and <example> tags — these hold quoted or injected
    content, not the agent's own assertions, so a shirking phrase inside
    them is not the agent shirking.
    """
    text = _FENCED_BLOCK.sub("", text)
    text = _TILDE_FENCE.sub("", text)
    text = _QUOTED_TAGS.sub("", text)
    text = _INLINE_CODE.sub("", text)
    return text


# ---------------------------------------------------------------------------
# Negation / meta-description guard
# ---------------------------------------------------------------------------
#
# A shirking phrase that the agent *disavows* ("I will NOT claim it's
# pre-existing") or *describes* ("scan for phrases like 'not my problem'") is
# not the agent shirking. These cues, when they appear in the short window of
# text immediately before a match, mark the match as disavowal/description
# rather than assertion. The window is bounded (GUARD_WINDOW) so that a real
# shirking assertion appearing far enough after a descriptive cue still fires
# (see test_scan_for_real_match_after_window_still_flagged).

GUARD_WINDOW = 40

# Negation cues: the phrase is being denied, forbidden, or made conditional.
# Checked only in the short window immediately before a match — "I will NOT
# claim it's pre-existing" disavows; "is pre-existing" asserts. Bare "like" /
# "such as" are deliberately NOT here: "looks like a pre-existing failure" is a
# real assertion (those belong to the quoted meta-description path below).
_NEGATION_CUES = re.compile(
    r"\b(?:not|n['’]?t|avoid|never|don['’]?t|doesn['’]?t|"
    r"won['’]?t|without|if|unless|whether)\b",
    re.IGNORECASE,
)

# Clause boundaries. English negation scopes within its own clause: in
# "I do not have time, leaving this for now" the "not" negates "have time",
# and the comma ends that clause — the deferral that follows is a fresh,
# unconditional assertion. So a negation cue only disavows the matched phrase
# when NO clause break sits between the cue and the match.
_CLAUSE_BREAK = re.compile(r"[,;:—–]|--")

# Meta-description cues: the phrase is being named as an example of the kind of
# thing to look for, not used as an assertion. Unlike negation, these are
# checked across the whole preceding text (not a fixed window) but ONLY when
# the match itself is wrapped in quotation marks — quoting is the structural
# signal that the phrase is mentioned, not used. An unquoted shirking
# assertion after a meta-cue ("scan for signs ... it was already failing")
# still fires.
_META_CUES = re.compile(
    r"\b(?:scan(?:ning)?\s+for|look(?:ing)?\s+for|check(?:ing)?\s+for|"
    r"search(?:ing)?\s+for|watch(?:ing)?\s+for|detect(?:ing|s)?|"
    r"phrases?\s+like|patterns?\s+like|signs?\s+(?:of|it)|"
    r"language\s+(?:such\s+as|like)|such\s+as\b)",
    re.IGNORECASE,
)

# Straight and curly double-quote characters used to delimit quoted examples.
_QUOTE_CHARS = "\"“”"


def _inside_quotes(stripped: str, match_start: int) -> bool:
    """True if the match begins inside an open double-quoted span.

    Counts unbalanced double-quote characters before the match: an odd count
    means the match sits inside a quotation (a mentioned phrase), an even
    count means it is unquoted (an asserted phrase).
    """
    quote_count = sum(stripped[:match_start].count(q) for q in _QUOTE_CHARS)
    return quote_count % 2 == 1


def _negation_guards(window: str) -> bool:
    """True if a negation cue in the window actually scopes the match.

    A negation only disavows the matched phrase when it is in the SAME clause —
    i.e. no clause break (comma, semicolon, colon, em/en-dash, `--`) sits
    between the cue and the match. We test the nearest (last) cue in the
    window: if a clause break follows it, that cue belongs to an earlier clause
    and does not guard the match ("I do not have time, leaving this for now").
    """
    last = None
    for m in _NEGATION_CUES.finditer(window):
        last = m
    if last is None:
        return False
    # Text between the end of the cue and the match (the window ends at match).
    return _CLAUSE_BREAK.search(window[last.end():]) is None


def _is_guarded(stripped: str, match_start: int) -> bool:
    """True if the match at match_start is disavowed or described, not asserted.

    Two independent guards:
      * Negation — a negation cue in the GUARD_WINDOW chars before the match
        AND in the same clause (no clause break between cue and match) means
        the phrase is being denied or made conditional.
      * Meta-description — the match is inside quotes AND a meta-cue appears
        anywhere before it, meaning the phrase is named as an example.
    """
    window = stripped[max(0, match_start - GUARD_WINDOW):match_start]
    if _negation_guards(window):
        return True
    if _inside_quotes(stripped, match_start) and _META_CUES.search(stripped[:match_start]):
        return True
    return False


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def find_shirking_phrase(text: str) -> str | None:
    """Return a context snippet around the first shirking match, or None.

    Kept for backward compatibility; new code should call find_shirking_match
    which also returns the category.
    """
    result = find_shirking_match(text)
    return result[0] if result else None


def find_shirking_match(text: str) -> tuple[str, str] | None:
    """Return (phrase_context, category) on the first match, or None.

    The category is one of the keys in _CATEGORY_RATIONALE — names the
    *kind* of shirking matched (pre-existing, attribution-deflection,
    unrelated, infrastructure-blame, deferral, scope-limitation,
    acceptance-evasion, dismissal). The denial uses it to name what
    was matched and link to the rationale; the signal log uses it for
    half-life analysis.
    """
    stripped = _strip_code_spans(text)
    for category, pattern in zip(_CATEGORIES, COMPILED_PATTERNS):
        for m in pattern.finditer(stripped):
            # Skip matches that are disavowed ("I will NOT claim...") or
            # described ("scan for phrases like ..."); keep scanning in case a
            # later, un-guarded match of the same pattern is a real assertion.
            if _is_guarded(stripped, m.start()):
                continue
            start = max(0, m.start() - 40)
            end = min(len(stripped), m.end() + 80)
            return stripped[start:end].strip(), category
    return None


# ---------------------------------------------------------------------------
# Blocking
# ---------------------------------------------------------------------------

_BLOCK_BODY = """\
🚨 OUTCOME OWNERSHIP VIOLATION ({category}) — you dismissed failures instead of fixing them.

You said something like:
  «{phrase}»

Why this counts as {category}: {rationale}

See `claude/rules/outcome-ownership.md` for the full anti-pattern catalog.
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
requirements). Test failures are never that.

The escape: if you believe this match is a false positive, the user
can release with "yes" / "proceed" / "lgtm" / "approved" / "go ahead".
That release is captured in the signal log as labeled training data —
if a particular category keeps producing false positives, the patterns
for that category get pruned in the next half-life review.\
"""


def _deny_output(event_name: str, phrase: str, category: str = "uncategorized") -> dict:
    rationale = _CATEGORY_RATIONALE.get(category, "review `outcome-ownership.md` for the rationale.")
    reason = _BLOCK_BODY.format(phrase=phrase, category=category, rationale=rationale)
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


def block(event_name: str, phrase: str, category: str = "uncategorized") -> NoReturn:
    _record_signal(
        gate_name="validate_no_shirking",
        decision="deny",
        reason=f"shirking phrase matched (category: {category})",
        category=category,
        phrase=phrase[:200],
        hook_event=event_name,
    )
    print(json.dumps(_deny_output(event_name, phrase, category)))
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

        last_shirking_category = None
        for i, (role, text) in enumerate(messages):
            if role != "assistant":
                continue
            # Skip messages that quote this hook's own block output —
            # otherwise the hook permanently poisons its own transcript.
            if any(sig in text for sig in _HOOK_SIGNATURES):
                continue
            match = find_shirking_match(text)
            if match:
                phrase, category = match
                last_shirking_idx = i
                last_shirking_phrase = phrase
                last_shirking_category = category

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

            if approved:
                # User released — capture this as labeled signal. Recurring
                # false-positive categories surface here over time.
                _record_signal(
                    gate_name="validate_no_shirking",
                    decision="waiver-accepted",
                    reason=f"user released after match (category: {last_shirking_category})",
                    category=last_shirking_category or "uncategorized",
                    phrase=last_shirking_phrase[:200],
                    hook_event=hook_event,
                )
            else:
                block(hook_event, last_shirking_phrase, last_shirking_category or "uncategorized")

    # ── Phase 2: Verification evidence (Stop only) ────────────────────────
    if hook_event == "Stop":
        verification_issue = check_verification_evidence(transcript_path)
        if verification_issue:
            block_verification(verification_issue)

    return 0


if __name__ == "__main__":
    sys.exit(main())
