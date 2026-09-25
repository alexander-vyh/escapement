"""Every multi-host skill canon must project a complete, host-clean skill.

For each ``agent-surfaces/skills/<id>.md`` canon:

- the Codex projection (read by both Codex and Pi from ``.agents/skills``)
  carries none of the Claude-only tokens the renderer rejects on Codex; and
- the Claude and Codex projections carry the same sections: the same heading
  sequence (level by level), with identical heading text wherever the canon's
  heading is shared rather than a slot. A port that drops, adds, or renames a
  section on one host fails here even when the other host is intact.
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

SKILL_CANON_DIR = ROOT / "agent-surfaces" / "skills"
CANONS = sorted(SKILL_CANON_DIR.glob("*.md"))
HOSTS = ("claude", "codex")

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")


def _headings(markdown: str) -> list[tuple[int, str]]:
    """(level, text) for every ATX heading outside fenced code blocks."""
    headings: list[tuple[int, str]] = []
    in_fence = False
    for line in markdown.splitlines():
        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = _HEADING_RE.match(line)
        if match:
            headings.append((len(match.group(1)), match.group(2)))
    return headings


def _body(projected: str) -> str:
    # Strip the emitted frontmatter block; headings live in the body.
    if projected.startswith("---\n"):
        return projected.split("\n---\n", 1)[1]
    return projected


def test_skill_canons_exist():
    assert CANONS, "no skill canons found under agent-surfaces/skills"


@pytest.mark.parametrize("canon_path", CANONS, ids=lambda p: p.stem)
def test_codex_projection_has_no_claude_only_tokens(canon_path):
    rendered = project_op(canon_path.read_text(encoding="utf-8"), "codex")
    leaked = [t for t in (*CODEX_SKILL_FORBIDDEN, *CODEX_FORBIDDEN) if t in rendered]
    assert not leaked, f"{canon_path.stem}: Codex/Pi surface leaks {leaked}"


@pytest.mark.parametrize("canon_path", CANONS, ids=lambda p: p.stem)
def test_hosts_share_every_section(canon_path):
    text = canon_path.read_text(encoding="utf-8")
    canon_headings = _headings(parse_canon(text)["body"])
    assert canon_headings, f"{canon_path.stem}: canon body has no headings"
    for host in HOSTS:
        projected = _headings(_body(project_op(text, host)))
        assert [lvl for lvl, _ in projected] == [lvl for lvl, _ in canon_headings], (
            f"{canon_path.stem}: {host} heading structure diverges from the canon"
        )
        for (_, got), (_, want) in zip(projected, canon_headings):
            if "{{slot:" not in want:
                assert got == want, f"{canon_path.stem}: {host} renamed section {want!r} -> {got!r}"
