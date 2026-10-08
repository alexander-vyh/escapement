"""Host-canon contract for rules and slash commands (escapement-l4fv).

Rules (``agent-surfaces/rules``) and commands (``agent-surfaces/commands``) are
projected per host by ``tools/openspec_projection.py``. These tests pin what a
consumer on each host observes:

- the Claude projection IS the live ``claude/`` surface (canon is writer of record);
- a non-Claude projection never leaks a Claude-only primitive or a token the
  Codex validator rejects (the ``.agents/skills`` tree is read by Codex AND Pi);
- every host keeps the same section structure, so a variant cannot silently
  drop a section while swapping in host tools;
- a Pi prompt template forwards the user's arguments (Pi substitutes only the
  placeholders present; it does not append arguments like Claude does).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from openspec_projection import parse_canon, project_op  # noqa: E402
from render_agent_surfaces import CODEX_FORBIDDEN, CODEX_SKILL_FORBIDDEN  # noqa: E402

CANON_DIRS = ("agent-surfaces/rules", "agent-surfaces/commands")
CLAUDE_PRIMITIVES = re.compile(r"SendMessage|TeamCreate|\bAgent\(|team_name")
DETAIL_MARKER = re.compile(r"^<!-- escapement:detail:(start|end) -->$")


def _canons() -> list[Path]:
    return sorted(p for d in CANON_DIRS for p in (ROOT / d).glob("*.md"))


CANONS = _canons()
CANON_IDS = [f"{p.parent.name}/{p.stem}" for p in CANONS]


def _structure(text: str) -> list[str]:
    """Headings and detail markers outside fenced code, in document order."""
    out: list[str] = []
    fenced = False
    for line in text.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if fenced:
            continue
        if re.match(r"^#{1,6} ", line) or DETAIL_MARKER.match(line):
            out.append(line.rstrip())
    return out


def _hosts(canon: Path) -> dict[str, str]:
    return parse_canon(canon.read_text(encoding="utf-8"))["targets"]


def test_rule_and_command_canons_exist():
    assert {p.parent.name for p in CANONS} == {"rules", "commands"}


@pytest.mark.parametrize("canon", CANONS, ids=CANON_IDS)
def test_canon_reaches_a_non_claude_host(canon):
    assert set(_hosts(canon)) - {"claude"}, f"{canon.name} projects to Claude only"


@pytest.mark.parametrize("canon", CANONS, ids=CANON_IDS)
def test_claude_projection_is_the_live_claude_surface(canon):
    targets = _hosts(canon)
    live = (ROOT / targets["claude"]).read_text(encoding="utf-8")
    assert project_op(canon.read_text(encoding="utf-8"), "claude") == live


@pytest.mark.parametrize("canon", CANONS, ids=CANON_IDS)
def test_non_claude_projections_leak_no_claude_primitive(canon):
    text = canon.read_text(encoding="utf-8")
    for host in sorted(set(_hosts(canon)) - {"claude"}):
        rendered = project_op(text, host)
        for token in CODEX_FORBIDDEN + CODEX_SKILL_FORBIDDEN:
            assert token not in rendered, f"{canon.name} [{host}] carries {token!r}"
        leak = CLAUDE_PRIMITIVES.search(rendered)
        assert leak is None, f"{canon.name} [{host}] carries Claude primitive {leak.group(0)!r}"


@pytest.mark.parametrize("canon", CANONS, ids=CANON_IDS)
def test_every_host_keeps_the_same_sections(canon):
    text = canon.read_text(encoding="utf-8")
    hosts = sorted(_hosts(canon))
    claude = _structure(project_op(text, "claude"))
    for host in hosts:
        assert _structure(project_op(text, host)) == claude, (
            f"{canon.name} [{host}] section structure diverges from Claude"
        )


@pytest.mark.parametrize(
    "canon",
    [p for p in CANONS if p.parent.name == "commands"],
    ids=[i for i in CANON_IDS if i.startswith("commands/")],
)
def test_pi_prompt_forwards_user_arguments(canon):
    text = canon.read_text(encoding="utf-8")
    assert "pi" in _hosts(canon), f"{canon.name} has no Pi prompt target"
    rendered = project_op(text, "pi")
    assert re.search(r"\$ARGUMENTS|\$@|\$\{@", rendered), f"{canon.name} [pi] drops the user's arguments"
