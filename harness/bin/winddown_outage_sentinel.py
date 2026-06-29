"""Deterministic sentinel for high-confidence wind-down text during judge outages."""

from __future__ import annotations

import re

_HIGH_CONFIDENCE_OUTAGE_WINDDOWN_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bopen follow-?ups\b(?=.{0,900}\bwant any of those\b)(?=.{0,900}\bstopping point\b)",
        r"\bor is this a (?:good|clean|natural|reasonable|honest) stopping point\b",
        (
            r"\bwant me to\b"
            r"(?=[^?]{0,650}\bor\b)"
            r"(?=[^?]{0,650}\b(?:open (?:a )?(?:draft )?pr|draft pr)\b)"
            r"(?=[^?]{0,650}\bfinish\b)"
            r"(?=[^?]{0,650}\bsave (?:a )?memory\b)"
        ),
    )
)


def high_confidence_outage_winddown(text: str) -> bool:
    """Return true for transcript-proven wind-down shapes.

    This is not a general classifier. The Stop hook calls it only after reversible
    work is already known to remain and the judge returns no usable verdict.
    """
    if not isinstance(text, str) or not text.strip():
        return False
    normalized = " ".join(text.split())
    return any(pattern.search(normalized) for pattern in _HIGH_CONFIDENCE_OUTAGE_WINDDOWN_PATTERNS)
