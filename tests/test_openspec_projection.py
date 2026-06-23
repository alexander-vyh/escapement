"""Acceptance tests for the named-slot OpenSpec projector (escapement-mol-741.15).

Proves, for the ``archive`` op, that ONE canonical body at
``agent-surfaces/openspec/archive.md`` projects into BOTH host surfaces with
host-conditional slot selection:

(a) Claude surface carries the ``subagent_type`` general-purpose Task dispatch.
(b) Codex surface carries ZERO ``Task``/``subagent_type``/``AskUserQuestion`` tokens.
(c) Both surfaces carry the create/update/close-bead tracking step.
(d) Re-rendering after the shared steps are reordered/renumbered still places
    each slot variant correctly (named, positionally-independent slots).
(e) Deleting a rendered surface and re-running the projector reproduces it
    byte-for-byte.

archive is chosen (NOT apply) because only archive exercises host-conditional
dispatch + the Codex forbidden-token wall + interleaved overlay at once.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from openspec_projection import (  # noqa: E402
    CANON_DIR,
    ProjectionError,
    parse_canon,
    project_op,
    projection_targets,
)

CANON_ARCHIVE = ROOT / CANON_DIR / "archive.md"

# Tokens the Codex skill validator forbids (render_agent_surfaces.CODEX_SKILL_FORBIDDEN).
CODEX_FORBIDDEN_TOKENS = ("TodoWrite", "AskUserQuestion", "Task tool", "subagent_type")


@pytest.fixture()
def canon_text() -> str:
    return CANON_ARCHIVE.read_text(encoding="utf-8")


# --- (a) Claude carries the Task/subagent_type dispatch (positive control) ----
def test_claude_archive_contains_subagent_task_dispatch(canon_text):
    rendered = project_op(canon_text, "claude")
    assert "subagent_type" in rendered
    assert "Task tool" in rendered
    assert 'subagent_type: "general-purpose"' in rendered


# --- (b) Codex carries NONE of the forbidden tokens (negative control) --------
def test_codex_archive_contains_no_forbidden_tokens(canon_text):
    rendered = project_op(canon_text, "codex")
    for token in CODEX_FORBIDDEN_TOKENS:
        assert token not in rendered, f"Codex surface must not contain {token!r}"


def test_codex_projection_is_clean_by_selection_not_stripping(canon_text):
    """The forbidden token must be ABSENT from the codex slot variant itself --
    i.e. the slot SELECTED the codex text, it was not stripped from the Claude
    text after the fact."""
    parsed = parse_canon(canon_text)
    sync = parsed["slots"]["sync_resolution"]
    assert "subagent_type" in sync["claude"]
    assert "subagent_type" not in sync["codex"]


# --- (c) Both surfaces carry the bead tracking step ---------------------------
def test_both_surfaces_contain_bead_tracking_step(canon_text):
    claude = project_op(canon_text, "claude")
    codex = project_op(canon_text, "codex")
    for rendered in (claude, codex):
        low = rendered.lower()
        assert "bead" in low
        assert "create a bead" in low
        assert "close the bead" in low


# --- (d) Slots are positionally independent (the SC8 restructure proof) -------
def _renumber_and_shuffle_steps(canon_text: str) -> str:
    """Simulate an upstream restructure: reverse the numbered top-level steps
    (so step 1 becomes the last, etc.) and renumber them. Slot placeholders ride
    with their surrounding step text -- a positional patch keyed on line number
    would misapply after this."""
    lines = canon_text.splitlines()
    # locate frontmatter end
    fence = [i for i, ln in enumerate(lines) if ln.strip() == "---"]
    body_start = fence[1] + 1
    head = lines[:body_start]
    body = lines[body_start:]

    # A "step block" starts at a top-level numbered heading line "N. **...".
    step_start = re.compile(r"^\d+\.\s+\*\*")
    blocks: list[list[str]] = []
    preamble: list[str] = []
    cur: list[str] | None = None
    for ln in body:
        if step_start.match(ln):
            if cur is not None:
                blocks.append(cur)
            cur = [ln]
        elif cur is None:
            preamble.append(ln)
        else:
            cur.append(ln)
    if cur is not None:
        blocks.append(cur)

    # The remainder after the last step (Output/Guardrails) -- detect the first
    # block that is no longer a step continuation: we treat everything inside the
    # last numbered block until a non-indented, non-numbered "**" header as tail.
    # Simpler: split tail off the final block at the first line that starts a
    # top-level "**Output" or "**Guardrails" section.
    tail: list[str] = []
    if blocks:
        last = blocks[-1]
        cut = None
        for idx, ln in enumerate(last):
            if idx > 0 and (ln.startswith("**Output") or ln.startswith("**Guardrails")):
                cut = idx
                break
        if cut is not None:
            tail = last[cut:]
            blocks[-1] = last[:cut]

    blocks.reverse()
    # renumber
    renumbered: list[str] = []
    for n, block in enumerate(blocks, start=1):
        first = re.sub(r"^\d+\.", f"{n}.", block[0], count=1)
        renumbered.append(first)
        renumbered.extend(block[1:])

    new_body = preamble + renumbered + tail
    return "\n".join(head + new_body)


def test_slots_survive_a_step_restructure(canon_text, tmp_path):
    restructured = _renumber_and_shuffle_steps(canon_text)

    # Sanity: the restructure actually moved things (steps reordered) and kept
    # all slot placeholders present so the projector still has work to do.
    assert restructured != canon_text
    for slot in ("selection_prompt", "sync_resolution", "artifact_confirm"):
        assert f"{{{{slot:{slot}}}}}" in restructured

    claude = project_op(restructured, "claude")
    codex = project_op(restructured, "codex")

    # Slot content still lands on the right host after the reorder.
    assert 'subagent_type: "general-purpose"' in claude
    for token in CODEX_FORBIDDEN_TOKENS:
        assert token not in codex
    # bead step survived the reorder on both hosts.
    assert "create a bead" in claude.lower()
    assert "create a bead" in codex.lower()
    # No raw placeholder leaked through.
    assert "{{slot:" not in claude
    assert "{{slot:" not in codex


# --- (e) Re-render is byte-stable (delete + reproduce) ------------------------
def test_projection_is_byte_stable(canon_text):
    first = project_op(canon_text, "claude")
    second = project_op(canon_text, "claude")
    assert first == second
    first_codex = project_op(canon_text, "codex")
    assert project_op(canon_text, "codex") == first_codex


def test_delete_and_reproduce_byte_for_byte(tmp_path):
    """Render both surfaces into a temp tree, delete them, re-render, assert
    byte-identical reproduction -- the deterministic-re-render check."""
    fake_root = tmp_path / "repo"
    (fake_root / CANON_DIR).mkdir(parents=True)
    (fake_root / CANON_DIR / "archive.md").write_text(
        CANON_ARCHIVE.read_text(encoding="utf-8"), encoding="utf-8"
    )

    # First projection -> write the host targets.
    targets = projection_targets(fake_root)
    assert len(targets) == 2  # claude + codex
    first_bytes: dict[Path, str] = {}
    for path, content in targets.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        first_bytes[path] = content

    # Delete every rendered surface.
    for path in first_bytes:
        path.unlink()
        assert not path.exists()

    # Re-render and compare byte-for-byte.
    second = projection_targets(fake_root)
    assert set(second) == set(first_bytes)
    for path, content in second.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        assert content == first_bytes[path], f"re-render drifted for {path}"


# --- fail-closed: a slot missing a host variant must error, not leak ----------
def test_missing_host_variant_fails_closed():
    bad = (
        "---\n"
        "op: demo\n"
        "slots:\n"
        "  only_claude:\n"
        '    claude: "claude text"\n'
        "targets:\n"
        "  claude: out/claude.md\n"
        "  codex: out/codex.md\n"
        "frontmatter:\n"
        "  claude:\n"
        '    name: "demo"\n'
        "  codex:\n"
        '    name: "demo"\n'
        "---\n"
        "Body {{slot:only_claude}}\n"
    )
    project_op(bad, "claude")  # ok
    with pytest.raises(ProjectionError):
        project_op(bad, "codex")  # codex has no variant -> fail closed


def test_unresolved_placeholder_fails_closed():
    bad = (
        "---\n"
        "op: demo\n"
        "slots:\n"
        "  known:\n"
        '    claude: "x"\n'
        "targets:\n"
        "  claude: out/claude.md\n"
        "frontmatter:\n"
        "  claude:\n"
        '    name: "demo"\n'
        "---\n"
        "Body {{slot:unknown}}\n"
    )
    with pytest.raises(ProjectionError):
        project_op(bad, "claude")
