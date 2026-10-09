"""Instruction oracle for delegated work, authored from the user's scope requirement.

Outcome: leads still use agents, but each child works only on its assignment;
review findings do not confer repair authority or ownership of another task.
The independent reference is the requirement below and its good/bad examples,
not an implementation helper or generated wording. Rendered host surfaces are
the observable output. This verifies instructions, NOT live model compliance.
An installed-host session replay remains necessary to establish that outcome.
"""

from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ("beads-execution", "dispatching-parallel-agents", "subagent-driven-development")
SURFACES = [
    ROOT / "plugins/escapement-claude/rules/agent-teams-default.md",
    ROOT / "plugins/escapement/claude/rules/agent-teams-default.md",
    ROOT / "plugins/escapement-pi/claude/rules/agent-teams-default.md",
    *[ROOT / "plugins/escapement-claude/skills" / name / "SKILL.md" for name in SKILLS],
    *[ROOT / "plugins/escapement/skills" / name / "SKILL.md" for name in SKILLS],
    # Pi package.json loads .agents/skills, as does the Codex repository surface.
    *[ROOT / ".agents/skills" / name / "SKILL.md" for name in SKILLS],
]

# Each requirement is a relationship, not a pinned sentence. Nearby unrelated
# mentions of "scope" or "review" are insufficient to satisfy the contract.
REQUIREMENTS = {
    "assigned outcome": r"(?:each|every|child|agent|dispatch|assignment)[^.]{0,160}(?:assigned|instructed) outcome",
    "scope and allowed effects": r"(?:state|define|name|include)[^.]{0,160}scope[^.]{0,160}(?:allowed|permitted|authorized) (?:effects|actions)",
    "completion and handoff": r"(?:completion|stop condition).{0,160}(?:handoff|hand.off|report back)",
    "review does not authorize repair": r"reviewers?.{0,160}report.{0,160}(?:do not|must not|never).{0,100}(?:repair|fix|implement)",
    "causal repairs stay in assignment": r"(?:causal(?:ly)?|block(?:s|ing)?).{0,160}(?:assigned|instructed) outcome.{0,160}(?:within|inside).{0,100}(?:scope|allowed|authorized)",
    "adjacent findings are reported": r"adjacent.{0,160}report.{0,160}(?:do not|must not|never).{0,80}(?:fix|repair|implement)",
    "queue is not authority": r"(?:bd ready|queue).{0,160}(?:only|filter|select).{0,100}(?:authorized|delegated) (?:tasks|work|beads)",
}


def violations(text):
    normalized = " ".join(text.replace("`", "").replace("*", "").split())
    missing = [name for name, pattern in REQUIREMENTS.items()
               if not re.search(pattern, normalized, re.IGNORECASE)]
    # An old directive elsewhere in a skill still competes with its new scope
    # paragraph. Merely appending good text must not launder that directive.
    if re.search(r"additional problems[^.]{0,150}\bFIX THEM\b", normalized, re.I):
        missing.append("unscoped fix-everything directive")
    if re.search(r"repeat until.{0,40}bd ready.{0,40}returns no tasks", normalized, re.I):
        missing.append("unbounded queue-draining directive")
    if re.search(r"(?:never|do not) (?:dispatch|use|spawn) agents", normalized, re.I):
        missing.append("blanket ban on agents")
    if re.search(r"do not repair any defects.{0,80}even causal blockers", normalized, re.I):
        missing.append("blanket ban on causal repair")
    # A universal copy-paste child prompt must carry its own reviewer exception;
    # a contract earlier in the file cannot repair the prompt a child receives.
    universal = re.search(
        r"### For Subagents[^\n]*\n\s*((?:>[^\n]*(?:\n|$))+)", text,
        re.IGNORECASE,
    )
    if universal:
        block = " ".join(universal.group(1).replace(">", " ").split())
        if re.search(r"\b(?:repair|fix) it\b", block, re.I) and not re.search(
            REQUIREMENTS["review does not authorize repair"], block, re.I
        ):
            missing.append("universal child prompt grants reviewers repair authority")
    if re.search(r"\*\*patch\*\*\s*→\s*resume implementer to fix", text, re.I):
        missing.append("quality finding label grants unconditional repair authority")
    if re.search(r"if.{0,25}defer or reject.{0,60}involve (?:the )?user", normalized, re.I):
        missing.append("deferred findings require unnecessary user intervention")
    return missing


# Independent positive example: agents remain useful, and causal repairs are
# expressly permitted. A blanket prohibition on agents or fixes is invalid.
GOOD = {
    "assigned outcome": "Every child receives its assigned outcome before dispatch.",
    "scope and allowed effects": "State the scope and allowed effects: files, commands, writes and checks.",
    "completion and handoff": "State completion criteria and the handoff to the lead.",
    "review does not authorize repair": "Reviewers report findings; they do not repair or implement without a new assignment.",
    "causal repairs stay in assignment": "Fix what causally blocks your assigned outcome only within the authorized scope and allowed effects.",
    "adjacent findings are reported": "For adjacent findings, report them and do not fix them.",
    "queue is not authority": "Use bd ready to select only authorized tasks; other ready beads remain unclaimed.",
}
GOOD_TEXT = "\n".join(GOOD.values()) + "\nUse parallel agents and independent QA when useful."


def test_scoped_qa_and_causal_repair_are_valid():
    assert violations(GOOD_TEXT) == []
    assert "Fix what causally blocks" in GOOD_TEXT
    assert "parallel agents and independent QA" in GOOD_TEXT


@pytest.mark.parametrize("requirement", list(GOOD))
def test_omitting_one_assignment_requirement_is_rejected(requirement):
    incomplete = "\n".join(text for name, text in GOOD.items() if name != requirement)
    assert requirement in violations(incomplete)


@pytest.mark.parametrize("old", [
    "If you find additional problems while implementing, FIX THEM.",
    "Repeat until bd ready returns no tasks.",
    "Never dispatch agents; do all work inline.",
    "Do not repair any defects, even causal blockers.",
    "### For Subagents (Include in Every Agent Prompt)\n\n"
    "> If a problem stands between you and your assigned outcome, repair it.\n",
    "- **patch** → resume implementer to fix, re-review.",
    "If `defer` or `reject` findings exist, involve the user.",
])
def test_old_scope_expansion_is_rejected_even_beside_good_guidance(old):
    assert violations(GOOD_TEXT + "\n" + old)


def test_role_scoped_child_prompt_and_causal_triage_remain_valid():
    scoped = (
        "### For Subagents (Include in Every Agent Prompt)\n\n"
        "> Reviewers report findings; they do not repair or implement.\n"
        "> If a problem blocks your assigned outcome, repair it within your allowed effects.\n"
        "\n- **In-scope causal patch** → resume implementer to fix.\n"
        "Record defer findings without blocking; escalate reject only for a consequential decision.\n"
    )
    assert violations(GOOD_TEXT + "\n" + scoped) == []


def test_all_declared_host_instruction_surfaces_exist():
    missing = [str(path.relative_to(ROOT)) for path in SURFACES if not path.is_file()]
    assert not missing, f"missing dispatched-agent instructions: {missing}"


@pytest.mark.parametrize("path", SURFACES, ids=lambda path: str(path.relative_to(ROOT)))
def test_rendered_dispatch_surfaces_bound_the_child_assignment(path):
    assert path.is_file(), f"missing instruction surface: {path}"
    problems = violations(path.read_text(encoding="utf-8"))
    assert not problems, f"{path.relative_to(ROOT)}: {problems}"
