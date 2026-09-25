"""Codex oracle for the apply_patch gates: discovery_input_gate, tdd-gate and
root_checkout_guard.

Codex writes every file through `apply_patch`: one call, the patch text in
`tool_input.command`, any number of files, paths relative to the payload's
`cwd`. All three facts were captured from Codex 0.156.1 (see _codex_host). Each
case runs the command the generated plugin registers for PreToolUse on
apply_patch, from the vendored plugin copy.

Every deny is judged by what Codex does with it: `permissionDecision: "deny"`
blocks the patch and shows the model the reason, so the reason must name the
repair. Every gate also has an allow control.
"""

from __future__ import annotations

import subprocess

from _codex_host import denial, is_allowed, isolated_env, patch_text, payload, run

EVENT = "PreToolUse"
PATCH = "pre_tool_use_apply_patch_add"

FILLED_FRAMING = """# Problem Framing - export

## Problem
Finance exports invoices by hand from the admin screen every month.

## Why Now
Month-end close slipped two days last quarter because of it.

## Decision Authority
Dana Ruiz, finance systems owner

## Behavioral Population
Finance operators running month-end close.

## Riskiest Assumption
A CSV export covers the ledger import; wrong if the ledger needs line tax detail.

## Success Criteria
Month-end export takes under five minutes with no manual edits.
"""


def _patch(cwd, *files, session: str | None = None) -> dict:
    extra = {"session_id": session} if session else {}
    return payload(PATCH, tool_input={"command": patch_text(*files)}, cwd=str(cwd), **extra)


# --- discovery_input_gate --------------------------------------------------


def _change(tmp_path, framing: str | None):
    change = tmp_path / "openspec" / "changes" / "invoice-export"
    change.mkdir(parents=True)
    (change / ".openspec.yaml").write_text("schema: spec-driven\n")
    if framing is not None:
        (change / "problem-framing.md").write_text(framing)


def test_codex_design_patch_without_framing_is_denied(tmp_path):
    _change(tmp_path, framing=None)
    # The gated artifact is the SECOND file: a gate reading only the first
    # target would let this draft through.
    data = _patch(tmp_path, ("Add", "notes.md"),
                  ("Add", "openspec/changes/invoice-export/design.md"))
    reason = denial(run(EVENT, "discovery_input_gate.py", data, isolated_env(tmp_path)))
    assert "problem-framing.md" in reason
    assert "/brainstorming" in reason, "the denial must name the way to a framing"


def test_codex_design_patch_with_filled_framing_is_allowed(tmp_path):
    _change(tmp_path, framing=FILLED_FRAMING)
    data = _patch(tmp_path, ("Add", "notes.md"),
                  ("Add", "openspec/changes/invoice-export/design.md"))
    assert is_allowed(run(EVENT, "discovery_input_gate.py", data, isolated_env(tmp_path)))


# --- tdd-gate --------------------------------------------------------------


def _code_project(tmp_path):
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "pyproject.toml").write_text("[project]\nname = 'invoices'\n")
    return repo


def test_codex_impl_patch_without_tests_is_denied_once_then_allowed(tmp_path):
    repo = _code_project(tmp_path)
    env = isolated_env(tmp_path)
    data = _patch(repo, ("Add", "src/export.py"), session="codex-session-tdd")

    reason = denial(run(EVENT, "tdd-gate.py", data, env))
    assert "src/export.py" in reason
    assert "apply the same patch again" in reason, "the override must be in the denial"

    # Re-applying is the override Claude's confirm prompt gives: it must pass.
    assert is_allowed(run(EVENT, "tdd-gate.py", data, env))


def test_codex_patch_that_writes_a_test_is_allowed(tmp_path):
    repo = _code_project(tmp_path)
    data = _patch(repo, ("Add", "src/export.py"), ("Add", "tests/test_export.py"),
                  session="codex-session-tdd-with-test")
    assert is_allowed(run(EVENT, "tdd-gate.py", data, isolated_env(tmp_path)))


# --- root_checkout_guard ---------------------------------------------------


def _primary_checkout(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".beads").mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("print('old')\n")
    return repo


def test_codex_relative_patch_into_primary_checkout_is_denied(tmp_path):
    repo = _primary_checkout(tmp_path)
    # A relative path, resolved against the payload cwd as Codex resolves it.
    data = _patch(repo, ("Update", "src/app.py"))
    reason = denial(run(EVENT, "root_checkout_guard.py", data, isolated_env(tmp_path)))
    assert str(repo / "src" / "app.py") in reason
    assert "create --repo" in reason, "must name the worktree repair"
    assert ".root-checkout-waiver" in reason, "must name the waiver escape"


def test_codex_patch_in_linked_worktree_is_allowed(tmp_path):
    main = tmp_path / "main"
    (main / ".git" / "worktrees" / "wt").mkdir(parents=True)
    (main / ".beads").mkdir()
    worktree = tmp_path / "wt"
    (worktree / "src").mkdir(parents=True)
    (worktree / ".git").write_text(f"gitdir: {main}/.git/worktrees/wt\n")
    (worktree / "src" / "app.py").write_text("print('old')\n")
    data = _patch(worktree, ("Update", "src/app.py"))
    assert is_allowed(run(EVENT, "root_checkout_guard.py", data, isolated_env(tmp_path)))


def test_codex_patch_writing_the_root_waiver_is_allowed(tmp_path):
    """The escape the denial names must be reachable with Codex's only edit tool."""
    repo = _primary_checkout(tmp_path)
    data = _patch(repo, ("Add", ".beads/.root-checkout-waiver"))
    assert is_allowed(run(EVENT, "root_checkout_guard.py", data, isolated_env(tmp_path)))
