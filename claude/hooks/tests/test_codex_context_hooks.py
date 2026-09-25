"""Codex oracle for the advisory context hooks: design_doc_location_guard and
test_reminder (PostToolUse on apply_patch), discovery-nudge and review_nudge
(UserPromptSubmit).

An advisory hook works only if its text reaches the model. Captured on Codex
0.156.1: PostToolUse `hookSpecificOutput.additionalContext` on an apply_patch
call reached the model verbatim, while a bare `systemMessage` only shows in the
UI. UserPromptSubmit sends the prompt as the top-level `prompt` field. So each
case feeds a captured payload to the command the generated plugin registers,
and reads the answer out of `additionalContext` under the right
`hookEventName`. Each hook also has a silent control, so a hook that always
nudges fails.
"""

from __future__ import annotations

import subprocess
import uuid

from _codex_host import context, isolated_env, patch_text, payload, run

POST = "PostToolUse"
PROMPT = "UserPromptSubmit"


def _patched(cwd, *files) -> dict:
    return payload("post_tool_use_apply_patch_add", cwd=str(cwd),
                   tool_input={"command": patch_text(*files)},
                   session_id=f"codex-{uuid.uuid4()}")


def _prompt(cwd, text: str) -> dict:
    return payload("user_prompt_submit", cwd=str(cwd), prompt=text)


# --- design_doc_location_guard ---------------------------------------------


def test_codex_design_doc_patch_gets_openspec_redirect_in_context(tmp_path):
    data = _patched(tmp_path, ("Add", "src/export.py"),
                    ("Add", "docs/plans/2026-09-24-export-design.md"))
    text = context(run(POST, "design_doc_location_guard.py", data, isolated_env(tmp_path)), POST)
    assert "openspec/changes/" in text


def test_codex_source_patch_gets_no_design_doc_redirect(tmp_path):
    data = _patched(tmp_path, ("Add", "src/export.py"), ("Update", "docs/plans/roadmap.md"))
    assert run(POST, "design_doc_location_guard.py", data, isolated_env(tmp_path)) is None


# --- test_reminder ---------------------------------------------------------


def _pytest_project(tmp_path):
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "pytest.ini").write_text("[pytest]\n")
    return repo


def test_codex_code_patch_gets_test_reminder_in_context(tmp_path):
    repo = _pytest_project(tmp_path)
    data = _patched(repo, ("Update", "README.md"), ("Update", "src/export.py"))
    text = context(run(POST, "test_reminder.py", data, isolated_env(tmp_path)), POST)
    assert "`pytest`" in text, "the reminder must name the detected test command"


def test_codex_docs_patch_gets_no_test_reminder(tmp_path):
    repo = _pytest_project(tmp_path)
    data = _patched(repo, ("Update", "README.md"), ("Add", "docs/usage.md"))
    assert run(POST, "test_reminder.py", data, isolated_env(tmp_path)) is None


# --- discovery-nudge -------------------------------------------------------

FEATURE_PROMPT = "Implement a new feature that exports invoices to CSV for finance"


def test_codex_feature_prompt_without_design_gets_discovery_nudge(tmp_path):
    output = run(PROMPT, "discovery-nudge.py", _prompt(tmp_path, FEATURE_PROMPT),
                 isolated_env(tmp_path))
    assert "/discovery" in context(output, PROMPT)


def test_codex_feature_prompt_with_recent_design_is_silent(tmp_path):
    design = tmp_path / "openspec" / "changes" / "invoice-export" / "design.md"
    design.parent.mkdir(parents=True)
    design.write_text("# Design\n")
    output = run(PROMPT, "discovery-nudge.py", _prompt(tmp_path, FEATURE_PROMPT),
                 isolated_env(tmp_path))
    assert output is None


# --- review_nudge ----------------------------------------------------------


def test_codex_review_prompt_gets_review_nudge(tmp_path):
    output = run(PROMPT, "review_nudge.py",
                 _prompt(tmp_path, "Please review this PR before we merge it"),
                 isolated_env(tmp_path))
    assert "/review" in context(output, PROMPT)


def test_codex_non_review_prompt_is_silent(tmp_path):
    output = run(PROMPT, "review_nudge.py",
                 _prompt(tmp_path, "Fix the failing parser test in src/parse.py"),
                 isolated_env(tmp_path))
    assert output is None
