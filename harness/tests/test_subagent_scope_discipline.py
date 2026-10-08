"""Subagent prompts must keep the subagent inside its assigned outcome (escapement-ak96).

The CONTINUATION DISCIPLINE block pasted into every subagent prompt said "If you
find additional problems, FIX THEM". Subagents read that as licence to fix
anything they notice -- the rest of the epic, other beads, adjacent cleanup --
which contradicts "record adjacent discoveries without executing them" and fed
the unbounded review->repair loops of escapement-maru.

User direction (2026-10-08): fixing what is needed to accomplish the subagent's
instructed outcome is good; reading it as fixing everything in the wider bead
or epic is not.

Like test_review_round_cap, this reads the *rendered* text each host loads.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SURFACE_DIRS = [
    ROOT / "plugins" / "escapement",
    ROOT / "plugins" / "escapement-claude",
    ROOT / "plugins" / "escapement-pi",
    ROOT / ".agents" / "skills",
]

BLOCK_START = "> **CONTINUATION DISCIPLINE:**"
# "additional problems ... FIX THEM" with no scope limit in between.
UNSCOPED_FIX = re.compile(r"additional problems[^.]*?\bFIX\s+THEM\b", re.IGNORECASE)
# The scope rule: fix what blocks your own outcome; report, don't fix, the rest.
OWN_OUTCOME = re.compile(r"\byour (?:assigned|instructed) outcome\b", re.IGNORECASE)
REPORT_NOT_FIX = re.compile(r"report it[^.]*?do not fix it", re.IGNORECASE | re.DOTALL)


def _blocks():
    for base in SURFACE_DIRS:
        for path in sorted(base.rglob("*.md")):
            lines = path.read_text(encoding="utf-8").splitlines()
            for i, line in enumerate(lines):
                if line.startswith(BLOCK_START):
                    block = []
                    for nxt in lines[i:]:
                        if not nxt.startswith(">"):
                            break
                        block.append(nxt.lstrip("> "))
                    yield path, " ".join(block)


def _is_doer_block(text):
    # Reviewer blocks ("DO NOT rubber-stamp ...") judge work; they do not fix it.
    return "rubber-stamp" not in text


def _violations(text):
    found = []
    if UNSCOPED_FIX.search(text):
        found.append("unscoped 'additional problems, FIX THEM'")
    if not OWN_OUTCOME.search(text):
        found.append("no 'your assigned outcome' scope")
    if not REPORT_NOT_FIX.search(text):
        found.append("no 'report it ... do not fix it' rule for out-of-scope problems")
    return found


def test_blocks_found_on_every_host():
    # Positive control: an empty scan would pass every test below.
    paths = {str(p.relative_to(ROOT)) for p, _ in _blocks()}
    for host in ("plugins/escapement/", "plugins/escapement-claude/", "plugins/escapement-pi/"):
        assert any(p.startswith(host) for p in paths), f"no subagent prompt block under {host}"
    assert sum(1 for _, t in _blocks() if _is_doer_block(t)) >= 8


def test_old_wording_is_rejected():
    # Negative control: the shipped-before-ak96 text must fail the check.
    old = (
        "DO NOT wind down prematurely. DO NOT summarize remaining work and stop. "
        "If you find additional problems while implementing, FIX THEM. If a test "
        "fails, debug and fix it."
    )
    assert "unscoped 'additional problems, FIX THEM'" in _violations(old)


def test_scoped_wording_is_accepted():
    good = (
        "If a problem stands between you and your assigned outcome, fix it. Anything "
        "beyond that outcome -- other beads, the rest of the epic, adjacent bugs or "
        "cleanup -- is not yours: report it to your lead and do not fix it."
    )
    assert _violations(good) == []


@pytest.mark.parametrize(
    "path,text",
    [(p, t) for p, t in _blocks() if _is_doer_block(t)],
    ids=lambda v: str(v.relative_to(ROOT)) if isinstance(v, pathlib.Path) else "",
)
def test_every_subagent_block_is_scoped_to_its_outcome(path, text):
    assert _violations(text) == [], f"{path.relative_to(ROOT)}: {_violations(text)}"
