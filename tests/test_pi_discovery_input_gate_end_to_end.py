"""Drive the rendered Pi extension through Pi writes of OpenSpec solution
artifacts, and see discovery_input_gate hold them until a filled problem
framing exists in the change directory.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pi_extension_harness import Session, git_repo, pi_env, rendered_plugin, run

CHANGE = "openspec/changes/add-widget"
FIELDS = ("Problem", "Why Now", "Decision Authority", "Behavioral Population", "Riskiest Assumption", "Success Criteria")


@pytest.fixture(scope="module")
def plugin(tmp_path_factory) -> Path:
    return rendered_plugin(tmp_path_factory)


def _framing(unfilled: str | None = None) -> str:
    return "\n".join(
        f"## {field}\n{'TBD' if field == unfilled else f'A considered answer about {field.lower()}.'}\n"
        for field in FIELDS
    )


def _project(tmp_path: Path, framing: str | None) -> Path:
    files = {f"{CHANGE}/.openspec.yaml": "schema: spec-driven\n", f"{CHANGE}/proposal.md": "# Proposal\n"}
    if framing is not None:
        files[f"{CHANGE}/problem-framing.md"] = framing
    return git_repo(tmp_path / "project", files)


def test_pi_design_write_without_framing_is_blocked(plugin, tmp_path):
    repo = _project(tmp_path, framing=None)
    session = Session(repo)
    write = {"path": str(repo / CHANGE / "design.md"), "content": "# Design\n"}

    (outcome,) = run(plugin, [session.tool_call("write", write)], pi_env(tmp_path))

    assert outcome["result"]["block"] is True
    reason = outcome["result"]["reason"]
    assert "problem-framing.md" in reason, "the block must name the framing it needs"
    assert "brainstorming skill" in reason, "the way to a framing must be one a Pi agent can take"
    assert "/brainstorming" not in reason


def test_pi_edit_with_unfilled_framing_is_blocked(plugin, tmp_path):
    repo = _project(tmp_path, framing=_framing(unfilled="Riskiest Assumption"))
    session = Session(repo)
    edit = {"path": f"{CHANGE}/proposal.md", "edits": [{"oldText": "# Proposal", "newText": "# Proposal: widgets"}]}

    (outcome,) = run(plugin, [session.tool_call("edit", edit)], pi_env(tmp_path))

    assert outcome["result"]["block"] is True
    reason = outcome["result"]["reason"]
    assert "Riskiest Assumption" in reason and "none - <reason>" in reason


def test_pi_design_write_with_filled_framing_is_allowed(plugin, tmp_path):
    """Negative control: a confirmed framing is exactly what the gate asks for."""
    repo = _project(tmp_path, framing=_framing())
    session = Session(repo)
    write = {"path": str(repo / CHANGE / "design.md"), "content": "# Design\n"}

    (outcome,) = run(plugin, [session.tool_call("write", write)], pi_env(tmp_path))

    assert outcome["result"] is None
