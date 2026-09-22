#!/usr/bin/env python3
"""No shipped hook may emit `permissionDecision: "ask"`.

Retired in escapement-e9v.12. The evidence, so this is not reintroduced by
someone who only reads the Claude Code hook API and sees three legal values:

  - Across 106,724 rows of `.gate-signal.jsonl`, `ask` fired 15,315 times and
    captured 17 rationales. `deny` plus a named waiver captured 4,621. The ask
    class produced almost no labeled decision data, which is the entire point
    of gate signal (gate-design.md Rule 2).
  - No host writes an approve/refuse row for an ask, so the class cannot be
    evaluated at the half-life review. You cannot prune what you cannot count.
  - Pi has no prompt primitive. Its adapter maps any non-allow decision to a
    hard block, so an `ask` there is a `deny` with no waiver flag — and when
    the session-keyed fire-once dedup broke (escapement-kdrc, per-call ids),
    that deny became unclearable and a real session bypassed every Bash gate
    by shelling out through a non-Bash tool surface.

The rule that replaced it: a gate decides mechanically and denies with a named
waiver escape, or it does not exist. Advisory prose addressed to an agent's
memory is not a mechanism.

If you are here because a gate needs a human judgment call it cannot make:
that is the signal to delete the gate, not to re-add the class.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# The wire value, in every spelling a hook could realistically emit it:
# a JSON literal, a dict literal, or an assignment feeding either.
_ASK_WIRE = re.compile(
    r"""permissionDecision["']?\s*[:=]\s*f?["']ask["']"""
    r"""|["']ask["']\s*(?:,|\})\s*(?:#.*)?$""",
    re.MULTILINE,
)


def _hook_sources() -> list[Path]:
    """Every Python hook that ships to a host, source tree and rendered trees."""
    paths = sorted((ROOT / "claude" / "hooks").glob("*.py"))
    paths += sorted((ROOT / "plugins").rglob("hooks/*.py"))
    return [p for p in paths if p.is_file()]


@pytest.mark.parametrize("hook", _hook_sources(), ids=lambda p: str(p.relative_to(ROOT)))
def test_hook_does_not_emit_the_ask_decision(hook: Path) -> None:
    text = hook.read_text(encoding="utf-8", errors="replace")
    offenders = [
        f"{hook.relative_to(ROOT)}:{text[: m.start()].count(chr(10)) + 1}: {m.group(0)!r}"
        for m in _ASK_WIRE.finditer(text)
        if "permissionDecision" in text[max(0, m.start() - 200) : m.end()]
    ]
    assert not offenders, (
        "the ask decision class is retired; a gate decides mechanically and "
        "denies with a waiver escape, or it does not exist:\n  "
        + "\n  ".join(offenders)
    )


def test_pi_adapter_rejects_an_ask_decision_as_invalid() -> None:
    """The Pi adapter must treat `ask` as a malformed decision, not as a block.

    Silently promoting it to a block is what made the class survive unnoticed
    on a host that cannot render a prompt.
    """
    index = (ROOT / "agent-surfaces" / "hosts" / "pi" / "extensions" / "index.ts").read_text()
    decision_allowlist = re.search(
        r"hook\.permissionDecision !== .*?\)\s*\{", index, re.DOTALL
    )
    assert decision_allowlist, "could not locate the Pi decision allowlist"
    assert '"ask"' not in decision_allowlist.group(0), (
        "Pi's decision allowlist still accepts `ask`; it must fail validation "
        "so no dispatcher can smuggle the retired class through"
    )
