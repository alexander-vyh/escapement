"""Regression guard for the superpowers full-disconnect (epic claude-workflow-setup-e3o).

After disconnect, production skill/hook source must contain ZERO `superpowers:`
dependency references. Intentional negative-control references inside test files
are allowed (they assert the refs stay gone), and *.backup* skills are excluded.

This is the durable form of the disconnect's completeness assertion: if a
`superpowers:` reference ever leaks back into production source, this fails loudly.
"""
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[3]  # .../claude-workflow-setup
ROOTS = [REPO / "claude" / "skills", REPO / "claude" / "hooks"]
_PATTERN = re.compile(r"superpowers:")


def _offending_lines():
    hits = []
    for root in ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.suffix not in (".md", ".py"):
                continue
            s = str(path)
            if ".backup" in s or "/tests/" in s:
                continue
            for i, line in enumerate(path.read_text(errors="ignore").splitlines(), 1):
                if _PATTERN.search(line):
                    hits.append(f"{path}:{i}: {line.strip()}")
    return hits


def test_no_superpowers_dependency_refs_in_production_source():
    hits = _offending_lines()
    assert not hits, (
        "superpowers: dependency refs leaked back into production source "
        "(the repo is fully disconnected — see docs/analysis/superpowers-vendor-vs-wrap.md):\n"
        + "\n".join(hits)
    )
