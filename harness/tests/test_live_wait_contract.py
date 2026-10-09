"""Instruction contract for economical live waits, not a model-behavior test.

The user requires one bounded observation with existing host tools while the
turn stays active, followed by verification or scoped repair. The independent
reference is the relations and examples below, not a runtime implementation.
Rendered instructions are the observable output. Actual model compliance and
host lifecycle behavior require separate installed-host session evidence.
"""

from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[2]
SURFACES = [
    # OMP native-loads AGENTS.md; PI.md intentionally contains only its adapter
    # delta (include_shared_fragments=false; render_agent_surfaces.py). AGENTS
    # plus the Pi outcome rule are the actual shared onboarding oracle.
    ROOT / "AGENTS.md",
    ROOT / "CLAUDE.md",
    ROOT / "plugins/escapement-claude/rules/outcome-ownership.md",
    ROOT / "plugins/escapement/claude/rules/outcome-ownership.md",
    ROOT / "plugins/escapement-pi/claude/rules/outcome-ownership.md",
]
RELATIONS = {
    "one bounded watcher": r"(?:(?:one|single) bounded watcher[^.]{0,160}(?:existing|host|native) tools|(?:existing|host|native) tools[^.]{0,160}(?:one|single) bounded watcher)",
    "same live handle in active turn": r"(?:await|wait)[^.]{0,100}same live handle[^.]{0,100}(?:active turn|turn active)",
    "no status-only final": r"(?:do not|never|not|no)[^.]{0,80}status.only final",
    "no automatic goal reentry": r"(?:do not|never|not|no)[^.]{0,80}(?:automatic|auto)[ -]goal re.?entr",
    "completion verifies outcome": r"complet(?:ion|es?|ed)[^.]{0,100}verif[^.]{0,80}outcome",
    "failure diagnoses and repairs scope": r"fail(?:ure|s|ed)[^.]{0,100}(?:scoped|in.scope)[^.]{0,80}diagnos[^.]{0,80}repair",
    "deadline inspects underlying operation": r"(?:observation deadline|observation timeout)[^.]{0,100}inspect[^.]{0,100}(?:same|underlying) operation[^.]{0,160}(?:do not|never|without|no) restart",
    "wait is interruptible": r"(?:wait|watcher)[^.]{0,100}interruptible",
    "host exit limitation": r"(?:(?:host|session)[^.]{0,80}(?:exits|ends|exit)[^.]{0,120}(?:cannot|does not|no automatic)[^.]{0,80}(?:resume|wake|re.?enter)|(?:cannot|does not|no automatic)[^.]{0,80}(?:resume|wake|re.?enter)[^.]{0,120}(?:host|session)[^.]{0,80}(?:exits|ends|exit))",
}


def violations(text):
    normalized = " ".join(text.replace("`", "").replace("*", "").split())
    problems = [name for name, pattern in RELATIONS.items()
                if not re.search(pattern, normalized, re.I)]
    # A top-level live-wait contract must not mask a competing instruction
    # elsewhere telling the agent to end or manufacture another observer.
    if re.search(r"end (?:the )?turn while (?:the )?operation is live", normalized, re.I):
        problems.append("live operation permits ending turn")
    if re.search(r"(?:start|create) (?:a )?new watcher (?:on|after|for) every timeout", normalized, re.I):
        problems.append("timeout multiplies watchers")
    if re.search(r"observation timeout means[^.]{0,100}operation failed[^.]{0,100}restart it", normalized, re.I):
        problems.append("observation timeout is misclassified as operation failure")
    return problems


GOOD = {
    "one bounded watcher": "Use one bounded watcher through existing tools.",
    "same live handle in active turn": "Await the same live handle within the active turn.",
    "no status-only final": "Do not issue status-only final answers while waiting.",
    "no automatic goal reentry": "Do not use automatic goal reentry as a waiting mechanism.",
    "completion verifies outcome": "On completion, verify the user outcome.",
    "failure diagnoses and repairs scope": "On failure, perform scoped diagnosis and repair.",
    "deadline inspects underlying operation": "At an observation deadline inspect the same underlying operation; do not restart the watcher just because time expired.",
    "wait is interruptible": "Keep the wait interruptible for new user input.",
    "host exit limitation": "If the host session exits, it cannot automatically resume this live wait.",
}
GOOD_TEXT = "\n".join(GOOD.values())


def test_existing_tools_and_single_interruptible_wait_are_valid():
    assert violations(GOOD_TEXT) == []


@pytest.mark.parametrize("relation", list(GOOD))
def test_removing_a_wait_relationship_is_rejected(relation):
    incomplete = "\n".join(value for name, value in GOOD.items() if name != relation)
    assert relation in violations(incomplete)


@pytest.mark.parametrize("bad", [
    "End the turn while the operation is live and let another goal entry check it.",
    "Start a new watcher after every timeout.",
    "Observation timeout means the underlying operation failed; restart it.",
])
def test_competing_live_wait_instructions_cannot_hide_beside_good_contract(bad):
    assert violations(GOOD_TEXT + "\n" + bad)


def test_live_wait_surfaces_are_present():
    assert all(path.is_file() for path in SURFACES)


@pytest.mark.parametrize("path", SURFACES, ids=lambda path: str(path.relative_to(ROOT)))
def test_each_host_receives_the_live_wait_contract(path):
    assert path.is_file(), f"missing host instructions: {path}"
    problems = violations(path.read_text(encoding="utf-8"))
    assert not problems, f"{path.relative_to(ROOT)}: {problems}"
