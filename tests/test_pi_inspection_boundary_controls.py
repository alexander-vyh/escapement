"""Independent path-boundary and ordinary writer controls for strict inspection."""
import json
from pathlib import Path

import pytest

from pi_extension_harness import Session, git, git_repo, pi_env, run
from test_pi_inspection_boundary_end_to_end import (
    assert_inspection_denied, inspection, plugin, read_call, write_call,
)


@pytest.mark.parametrize("neighbor", ["source", "report"])
def test_close_neighbor_never_acquires_evidence_or_mutates_another_report(plugin, inspection, neighbor):
    session, env, source, report, state = inspection
    [positive] = run(plugin, [read_call(session, source)], env)
    assert positive["read"] == "Useful finding: the candidate preserves invoice provenance."
    if neighbor == "source":
        outside = source.with_name(source.name + ".backup")
        outside.write_text("Unnominated private evidence.\n", encoding="utf-8")
        event = read_call(session, outside)
    else:
        outside = report.with_name(report.name + ".extra")
        outside.write_text("KEEP\n", encoding="utf-8")
        event = write_call(session, outside, "Unauthorized overwrite.\n")
    [outcome] = run(plugin, [event], env)
    assert_inspection_denied(outcome, report)
    assert "read" not in outcome and "executed" not in outcome
    assert outside.read_text(encoding="utf-8") == (
        "Unnominated private evidence.\n" if neighbor == "source" else "KEEP\n"
    )


@pytest.mark.parametrize("retarget", ["alias", "nominated"])
def test_resolved_source_alias_is_useful_but_retargeting_cannot_expand_scope(plugin, inspection, retarget):
    session, env, source, report, state = inspection
    alias = source.with_name("source-alias.md")
    alias.symlink_to(source)
    [positive] = run(plugin, [read_call(session, alias)], env)
    assert positive["read"] == "Useful finding: the candidate preserves invoice provenance."
    changed = alias if retarget == "alias" else source
    changed.unlink()
    changed.symlink_to(source.parent / "outside.md")
    [outcome] = run(plugin, [read_call(session, changed)], env)
    assert_inspection_denied(outcome, report)
    assert "read" not in outcome
    assert json.loads(state.read_text(encoding="utf-8"))["admitted"] == 1


@pytest.mark.parametrize("parent_kind", ["none", "legacy-missing", "actual-unactivated"])
def test_unactivated_root_and_children_can_perform_ordinary_mapped_write_and_edit(plugin, tmp_path, parent_kind):
    repo = git_repo(tmp_path / "repo", {"note.md": "VALUE = 1\n"})
    worktree = tmp_path / "writer"
    git(repo, "worktree", "add", "-b", "feature/ordinary-writer", str(worktree))
    parent_file = None
    if parent_kind == "legacy-missing":
        parent_file = str(tmp_path / "legacy-parent.jsonl")
    elif parent_kind == "actual-unactivated":
        parent_file = str(tmp_path / "actual-parent.jsonl")
        Path(parent_file).write_text(json.dumps(Session(worktree).header) + "\n", encoding="utf-8")
    session = Session(worktree, parent_session=parent_file)
    env = pi_env(tmp_path)
    env["ESCAPEMENT_INSPECTION_STATE_DIR"] = str(tmp_path / "unactivated-state")
    target = worktree / "note.md"
    [written] = run(plugin, [write_call(session, target, "VALUE = 2\n")], env)
    assert written["result"] is None, written
    assert target.read_text(encoding="utf-8") == "VALUE = 2\n"
    edited = session.tool_call("edit", {
        "path": str(target), "edits": [{"oldText": "VALUE = 2", "newText": "VALUE = 3"}],
    })
    edited["executor"] = {"kind": "replace", "path": str(target),
                          "before": "VALUE = 2", "after": "VALUE = 3"}
    [outcome] = run(plugin, [edited], env)
    assert outcome["result"] is None, outcome
    assert target.read_text(encoding="utf-8") == "VALUE = 3\n"
