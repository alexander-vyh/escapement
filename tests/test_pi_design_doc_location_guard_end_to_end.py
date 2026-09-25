"""Drive the rendered Pi extension through Pi's tool_result for a design doc
written to docs/plans/, and see the OpenSpec redirect reach the model in the
tool result it reads.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pi_extension_harness import Session, appended_text, git_repo, pi_env, rendered_plugin, run


@pytest.fixture(scope="module")
def plugin(tmp_path_factory) -> Path:
    return rendered_plugin(tmp_path_factory)


def _result_after(plugin: Path, tmp_path: Path, tool: str, arguments: dict) -> dict:
    repo = git_repo(tmp_path / "project", {"docs/plans/2026-09-widget-design.md": "# Design\n", "docs/notes.md": "notes\n"})
    session = Session(repo)
    session.tool_call(tool, arguments)
    (outcome,) = run(plugin, [session.tool_result(tool, arguments, "Wrote the file.")], pi_env(tmp_path))
    return outcome


def test_pi_design_doc_write_gets_openspec_redirect_in_result(plugin, tmp_path):
    outcome = _result_after(plugin, tmp_path, "write", {"path": "docs/plans/2026-09-widget-design.md", "content": "# Design\n"})

    assert outcome["result"]["content"][0]["text"] == "Wrote the file.", "the tool's own output stays first"
    added = appended_text(outcome["result"])
    assert "openspec/changes/" in added and "advisory" in added


def test_pi_design_doc_edit_gets_openspec_redirect_in_result(plugin, tmp_path):
    edit = {"path": "docs/plans/2026-09-widget-design.md", "edits": [{"oldText": "# Design", "newText": "# Widget design"}]}
    outcome = _result_after(plugin, tmp_path, "edit", edit)

    assert "openspec/changes/" in appended_text(outcome["result"])


def test_pi_other_doc_write_gets_no_redirect(plugin, tmp_path):
    """Negative control: a doc outside docs/plans/ is not a misplaced design."""
    outcome = _result_after(plugin, tmp_path, "write", {"path": "docs/notes.md", "content": "more notes\n"})

    assert outcome["result"] is None
