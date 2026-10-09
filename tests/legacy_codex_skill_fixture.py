"""Pinned historical deployment bytes, independent of evolving current skills."""

from __future__ import annotations

import hashlib
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "legacy-skills"
PRE_FINISH_CODEX_SKILL_SHA256 = (
    "f08ccbb6c66668db81a8a1fe19e1f2302be17a4a204f11dc43522a0b2031f1cb"
)
PREVIOUS_CODEX_SKILL_SHA256 = (
    "d175cacf8aff932af013d0d410a2e8324a505c35b7d7fd5301c34d78c0d22bcc"
)

HISTORICAL_CRLF_SHA256 = (
    "2096820ff0d7a712aa4b58ca2590979f80f2d0fd168a23bda788a024f47792e0"
)
HISTORICAL_LF_SHA256 = (
    "c65855a32ece63079c692332a968174748187b9fb8e1a57bf3803dcc76beb402"
)


def _fixture(name: str, expected: str) -> bytes:
    data = (FIXTURES / name).read_bytes()
    assert hashlib.sha256(data).hexdigest() == expected
    return data


def historical_legacy_skill_bytes(*, crlf: bool = True) -> bytes:
    data = _fixture("claude-beads-legacy.txt", HISTORICAL_LF_SHA256)
    if crlf:
        data = data.replace(b"\n", b"\r\n")
        assert hashlib.sha256(data).hexdigest() == HISTORICAL_CRLF_SHA256
    return data


def pre_finish_codex_skill_bytes() -> bytes:
    return _fixture("codex-beads-pre-finish.txt", PRE_FINISH_CODEX_SKILL_SHA256)


def previous_codex_skill_bytes() -> bytes:
    return _fixture("codex-beads-previous.txt", PREVIOUS_CODEX_SKILL_SHA256)
