"""Review/repair loops must name a round cap and an exit (escapement-maru).

Codex rollouts on 2026-10-06 ran review->repair->review lanes for ~20h
(1,589 send_message from one adversarial-reviewer). The reviewer's developer
message carried the agent-teams CONTINUATION DISCIPLINE block ("If you find
additional problems, FIX THEM ... done when the OUTCOME is verified"), and the
rules/skills said "loop-until-dry" / "loop until they're fixed" with no cap.

Codex has no hook on subagent messaging (escapement-2waa), so the cap is
instruction-only there. This oracle therefore reads the *rendered* text each
host actually receives, not the claude/ sources or a helper.
"""
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]

# What each host loads: plugin trees (Codex, Claude, Pi) plus Codex repo skills.
SURFACE_DIRS = [
    ROOT / "plugins" / "escapement",
    ROOT / "plugins" / "escapement-claude",
    ROOT / "plugins" / "escapement-pi",
    ROOT / ".agents" / "skills",
]
CODEX_RULE = ROOT / "plugins/escapement/claude/rules/agent-teams-default.md"
# The rule as each host renders it; Pi's copy is host-specific text, not a byte copy.
RENDERED_RULES = [
    CODEX_RULE,
    ROOT / "plugins/escapement-claude/rules/agent-teams-default.md",
    ROOT / "plugins/escapement-pi/claude/rules/agent-teams-default.md",
]
RULE_IDS = ["codex", "claude", "pi"]
CODEX_SKILLS = ROOT / "plugins/escapement/skills"

LOOP = re.compile(
    r"loop-until-dry|loop until (?:they|it)|re-enters the loop|re-review",
    re.IGNORECASE,
)
CAP = re.compile(r"2 review rounds|round cap", re.IGNORECASE)
EXIT = re.compile(r"bd create")


def _surface_markdown():
    for base in SURFACE_DIRS:
        yield from sorted(base.rglob("*.md"))


def _paragraphs(text):
    return [p for p in re.split(r"\n\s*\n", text) if p.strip()]


def test_surfaces_exist():
    # Positive control: an empty scan would pass every test below.
    files = list(_surface_markdown())
    assert CODEX_RULE in files
    assert (CODEX_SKILLS / "subagent-driven-development/SKILL.md") in files


def test_every_rendered_review_loop_names_its_cap_and_exit():
    uncapped = []
    for path in _surface_markdown():
        for para in _paragraphs(path.read_text()):
            if not LOOP.search(para):
                continue
            if CAP.search(para) and EXIT.search(para):
                continue
            uncapped.append(f"{path.relative_to(ROOT)}: {para.strip()[:120]!r}")
    assert not uncapped, "review loop without round cap + bd create exit:\n" + "\n".join(uncapped)


def _cap_section(text):
    m = re.search(r"### Review Round Cap\n(.*?)(?=\n#{2,3} )", text, re.DOTALL)
    assert m, "rendered rule lacks a '### Review Round Cap' section"
    return " ".join(m.group(1).split())


@pytest.mark.parametrize("rule", RENDERED_RULES, ids=RULE_IDS)
def test_rule_bounds_rounds_and_files_overflow_as_beads(rule):
    section = _cap_section(rule.read_text())
    assert "at most 2 review rounds" in section
    # Past the cap, findings become beads, not another repair round.
    assert re.search(r"remaining finding.*?`bd create`", section)
    assert "not another repair round" in section


@pytest.mark.parametrize("rule", RENDERED_RULES, ids=RULE_IDS)
def test_rule_keeps_one_repair_round_for_blocking_findings(rule):
    # Negative control: the cap must not let a blocker slip into a bead.
    section = _cap_section(rule.read_text())
    assert re.search(r"causally blocks the delegated outcome.*?one more repair round", section)


@pytest.mark.parametrize("rule", RENDERED_RULES, ids=RULE_IDS)
def test_subagent_continuation_block_defers_to_the_cap(rule):
    # The block every subagent receives said "FIX THEM" unconditionally; that
    # is what kept reviewers and repairers ping-ponging.
    text = rule.read_text()
    m = re.search(r"> \*\*CONTINUATION DISCIPLINE:\*\*(.*?)(?=\n[^>]|\Z)", text, re.DOTALL)
    assert m, "rendered rule lacks the subagent CONTINUATION DISCIPLINE block"
    block = " ".join(m.group(1).replace(">", " ").split())
    assert "2 review rounds" in block and "bd create" in block
