#!/usr/bin/env python3
"""Continuation-harness wind-down rung — deterministic floor.

Detects a **wind-down / decision-punt offer** in an assistant's turn-final message
(e.g. "want me to wrap for the night, or keep going?"). When such an offer is emitted
AND reversible in-scope work remains, the Stop gate blocks it into continuation instead
of granting the `conversational` free-pass (would_block_stop.py:176-183) — closing the
hole that lets a no-contract wind-down stop freely.

DESIGN NOTES
- This is a CONSCIOUS, documented exception to would_block_stop's "no prose pattern
  matching" rule (would_block_stop.py:6). Wind-down is irreducibly linguistic, so it
  cannot be detected from filesystem state. The prose matching is quarantined HERE; the
  pure structural gate stays pure.
- This is the DETERMINISTIC FLOOR. A local-LLM judge (the SWE-PRM pattern) is intended to
  sit ON TOP as the primary classifier — `winddown_decision(..., is_offer=<llm_verdict>)`
  lets the model's verdict override the regex. The regex remains the fail-open fallback
  for when the local model is slow / down / stale.
- HONEST LIMITATION: the Stop hook fires AFTER the turn is rendered, so this rung forces
  *continuation*; it does NOT un-show the offer text. It converts "agent pauses and waits"
  into "agent offers but keeps going."
"""
from __future__ import annotations

import re
from typing import Optional, Tuple

# Wind-down / wrap / hand-off-for-now offer language. Centered on the STOP/WRAP concept,
# NOT on questions or implementation forks — "Postgres or SQLite?" must not match.
_WINDDOWN_PATTERNS = [
    re.compile(p, re.IGNORECASE) for p in (
        r"wrap (up|for the night|things up|it up|this up)",
        r"\b(we|i|let'?s|to) wrap\b",
        r"call it (a night|a day|here|a wrap)\b",
        r"that'?s a wrap\b",
        r"\bgood ?night\b",
        r"\bfor the night\b",
        r"pick (this|it|things) (back )?up (tomorrow|later|in the morning|next session|another (day|time))",
        r"session.?close",
        r"ready to push when you\b",
        r"push when you'?re ready",
        r"leave (it|this|things)\b[^.?!]*\b(night|morning|tomorrow|next session)\b",
        r"(want me to|should i|shall i|do you want me to|want me to go ahead and)\s+"
        r"(wrap|stop|pause|call it|push and (wrap|stop))",
        r"\bor (we (should |can )?)?(wrap|stop|pause|call it)\b",
        r"\bhand(ing)? (this|it|things) off (for|tonight|for the night)",
    )
]

# The denial. Per gate-design Rule 1 the escape path is IN the message: proceed with the
# reversible work + async-flag the human-only items; and the user's release valve ("stop")
# is preserved so the gate is not a trap.
RECOVERY_PROMPT = (
    "You ended your turn by offering to wind down (wrap / pause / 'which way?') while "
    "reversible in-scope work remains. Do NOT offer to wrap or ask which way — just "
    "PROCEED now with the next reversible task. If something is genuinely human-only or "
    "irreversible (a merge, a branch-protection toggle, a deploy), async-FLAG it as a "
    "note and KEEP WORKING the rest; one blocked item does not block the session. The "
    "user can still release you by saying 'stop'."
)


def is_winddown_offer(text: Optional[str]) -> bool:
    """True iff the text contains wind-down / wrap / decision-punt-to-stop language.

    Deliberately narrow: a legitimate clarifying question ("Auth.js or Lucia?") or an
    implementation fork ("(a) caching or (b) pagination?") has no wrap/stop offer and
    must return False (over-nagging legit questions is the failure mode to avoid).
    """
    if not text or not isinstance(text, str):
        return False
    return any(p.search(text) for p in _WINDDOWN_PATTERNS)


def winddown_decision(
    assistant_text: Optional[str],
    reversible_work_remains: bool,
    *,
    is_offer: Optional[bool] = None,
) -> Tuple[str, str]:
    """The rung. (decision, reason).

    `is_offer` lets a higher-confidence classifier (a local-LLM judge) override the
    regex floor. When None, the deterministic detector is used.
    """
    offer = is_winddown_offer(assistant_text) if is_offer is None else bool(is_offer)
    if not offer:
        return ("allow", "no_winddown_offer")
    if not reversible_work_remains:
        # Genuinely blocked on a human-only/irreversible item with nothing reversible
        # left: a legitimate stop. Nagging it is the over-correction the research warns
        # against (selective-quitting-improves-safety).
        return ("allow", "winddown_but_no_reversible_work")
    return ("block", "winddown_offer_work_remains")
