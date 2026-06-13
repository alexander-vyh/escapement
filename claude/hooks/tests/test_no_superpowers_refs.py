"""Regression guard for the superpowers full-disconnect (epic claude-workflow-setup-e3o).

After disconnect, production skill/hook source must contain ZERO references to
`superpowers` — not just `superpowers:` dependency refs but ANY mention, since a
bare-prose reference (e.g. "wraps the superpowers skill") is equally a leak now
that the disconnect chose deletion+redirect with zero vendored copies.
Intentional negative-control references inside test files are allowed (they
assert the refs stay gone), and *.backup* skills are excluded.

This is the durable form of the disconnect's completeness assertion: if ANY
`superpowers` reference leaks back into production source, this fails loudly.

RETIREMENT (half-life answerability): retire this guard when `superpowers` is no
longer an installable marketplace skill that could be re-referenced — verify via
`claude plugin marketplace` (or the host's skill registry) no longer listing a
`superpowers` plugin. Until that structural condition holds, the guard stays; do
not retire it on age alone.
"""
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parents[3]  # repo root (escapement)
ROOTS = [REPO / "claude" / "skills", REPO / "claude" / "hooks"]
# Bare, case-insensitive: the claimed scope is "zero superpowers refs", so the
# pattern must match the whole word, not only the colon-suffixed dependency form.
_PATTERN = re.compile(r"\bsuperpowers\b", re.IGNORECASE)


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
        "superpowers references leaked back into production source "
        "(the repo is fully disconnected — see docs/analysis/superpowers-vendor-vs-wrap.md):\n"
        + "\n".join(hits)
    )
