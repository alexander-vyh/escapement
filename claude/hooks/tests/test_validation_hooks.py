"""Unit tests for the three validation hooks:
  - spec_id_enforcement.py (Control 1)
  - design_doc_location_guard.py (Control 2)
  - openspec_init_guard.py (Control 3)

Run from anywhere with:
  python -m pytest ~/.claude/hooks/tests/test_validation_hooks.py -v
"""

import io
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

_hooks_dir = Path.home() / ".claude" / "hooks"
if not _hooks_dir.exists():
    pytest.skip("~/.claude/hooks/ not found", allow_module_level=True)

if str(_hooks_dir) not in sys.path:
    sys.path.insert(0, str(_hooks_dir))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_hook(module_name: str, hook_event: str, tool_name: str = "Bash",
              command: str = "", file_path: str = "", extra: dict = None,
              cwd: str = "") -> tuple[int, str, str]:
    """Run a hook's main() and return (exit_code, stdout, stderr).

    exit_code: 0 for allow, 2 for deny.
    stdout: captured JSON output (if any).
    stderr: captured advisory/warning output (if any).
    """
    import importlib
    mod = importlib.import_module(module_name)

    payload = {"hook_event_name": hook_event, "tool_name": tool_name}
    if tool_name == "Bash":
        payload["tool_input"] = {"command": command}
    elif tool_name in ("Write", "Edit"):
        payload["tool_input"] = {"file_path": file_path}

    if cwd:
        payload["cwd"] = cwd

    if extra:
        payload.update(extra)

    stdin_data = json.dumps(payload)
    captured_out = io.StringIO()
    captured_err = io.StringIO()

    try:
        with patch("sys.stdin", io.StringIO(stdin_data)), \
             patch("sys.stdout", captured_out), \
             patch("sys.stderr", captured_err):
            mod.main()
        return 0, captured_out.getvalue(), captured_err.getvalue()
    except SystemExit as exc:
        return exc.code, captured_out.getvalue(), captured_err.getvalue()


# ===========================================================================
# Control 1: spec_id_enforcement
# ===========================================================================

class TestSpecIdEnforcement:
    """Tests for spec_id_enforcement.py."""

    def test_non_pretooluse_allows(self):
        """Non-PreToolUse events are fast-path allowed."""
        code, _, _ = _run_hook("spec_id_enforcement", "PostToolUse", command="bd create foo")
        assert code == 0

    def test_non_bash_allows(self):
        """Non-Bash tools are fast-path allowed."""
        code, _, _ = _run_hook("spec_id_enforcement", "PreToolUse", tool_name="Write",
                               command="bd create foo")
        assert code == 0

    def test_non_bd_create_allows(self):
        """Commands without 'bd create' are fast-path allowed."""
        code, _, _ = _run_hook("spec_id_enforcement", "PreToolUse", command="bd list")
        assert code == 0

    def test_bd_create_with_spec_id_allows(self):
        """bd create with --spec-id is allowed."""
        code, _, _ = _run_hook("spec_id_enforcement", "PreToolUse",
                               command="bd create 'task' --parent bd-abc --spec-id docs/plans/design.md")
        assert code == 0

    def test_bd_create_with_spec_id_equals_allows(self):
        """bd create with --spec-id=value is allowed."""
        code, _, _ = _run_hook("spec_id_enforcement", "PreToolUse",
                               command="bd create 'task' --parent bd-abc --spec-id=my-spec")
        assert code == 0

    def test_bd_create_without_parent_allows(self):
        """bd create without --parent is allowed (not under a molecule)."""
        code, _, _ = _run_hook("spec_id_enforcement", "PreToolUse",
                               command="bd create 'standalone task'")
        assert code == 0

    def test_bd_create_parent_not_mol_feature_allows(self):
        """bd create under a non-mol-feature parent is allowed."""
        with patch("spec_id_enforcement.is_mol_feature_parent", return_value=False):
            code, _, _ = _run_hook("spec_id_enforcement", "PreToolUse",
                                   command="bd create 'task' --parent bd-xyz")
        assert code == 0

    def test_bd_create_parent_mol_feature_no_spec_id_blocks(self):
        """bd create under mol-feature without --spec-id is blocked."""
        with patch("spec_id_enforcement.is_mol_feature_parent", return_value=True):
            code, out, _ = _run_hook("spec_id_enforcement", "PreToolUse",
                                     command="bd create 'task' --parent bd-mol123")
        assert code == 2
        data = json.loads(out)
        reason = data["hookSpecificOutput"]["permissionDecisionReason"]
        assert "--spec-id" in reason
        assert "mol-feature" in reason

    def test_invalid_json_stdin_allows(self):
        """Invalid JSON on stdin fails open."""
        import spec_id_enforcement
        with patch("sys.stdin", io.StringIO("not json")):
            result = spec_id_enforcement.main()
        assert result == 0

    def test_parse_flag_equals(self):
        """parse_flag handles --flag=value."""
        from spec_id_enforcement import parse_flag
        assert parse_flag("bd create --parent=bd-abc", "parent") == "bd-abc"

    def test_parse_flag_space(self):
        """parse_flag handles --flag value."""
        from spec_id_enforcement import parse_flag
        assert parse_flag("bd create --parent bd-abc", "parent") == "bd-abc"

    def test_parse_flag_missing(self):
        """parse_flag returns None for missing flag."""
        from spec_id_enforcement import parse_flag
        assert parse_flag("bd create foo", "parent") is None

    def test_check_issue_for_mol_feature_labels(self):
        """_check_issue_for_mol_feature detects mol-feature in labels."""
        from spec_id_enforcement import _check_issue_for_mol_feature
        assert _check_issue_for_mol_feature({"labels": ["mol-feature", "other"]})
        assert not _check_issue_for_mol_feature({"labels": ["bug", "chore"]})

    def test_check_issue_for_mol_feature_metadata(self):
        """_check_issue_for_mol_feature detects mol-feature in metadata formula."""
        from spec_id_enforcement import _check_issue_for_mol_feature
        assert _check_issue_for_mol_feature({"metadata": {"formula": "mol-feature"}})
        assert not _check_issue_for_mol_feature({"metadata": {"formula": "mol-rapid"}})


# ===========================================================================
# Control 2: design_doc_location_guard
# ===========================================================================

class TestDesignDocLocationGuard:
    """Tests for design_doc_location_guard.py."""

    def test_non_posttooluse_allows(self):
        """Non-PostToolUse events are fast-path allowed."""
        code, out, err = _run_hook("design_doc_location_guard", "PreToolUse",
                                   tool_name="Write", file_path="docs/plans/my-design.md")
        assert code == 0
        assert out == ""  # No stdout
        assert err == ""  # No stderr

    def test_non_write_edit_allows(self):
        """Non-Write/Edit tools are fast-path allowed."""
        code, out, err = _run_hook("design_doc_location_guard", "PostToolUse",
                                   tool_name="Bash", command="echo hi")
        assert code == 0
        assert out == ""
        assert err == ""

    def test_non_design_path_allows(self):
        """Paths not matching docs/plans/*design* are silently allowed."""
        code, out, err = _run_hook("design_doc_location_guard", "PostToolUse",
                                   tool_name="Write", file_path="src/main.py")
        assert code == 0
        assert out == ""
        assert err == ""

    def test_design_doc_path_warns(self):
        """Writing to docs/plans/*design* emits a warning on stderr."""
        code, out, err = _run_hook("design_doc_location_guard", "PostToolUse",
                                   tool_name="Write",
                                   file_path="docs/plans/2026-03-20-auth-design.md")
        assert code == 0  # Advisory only — never blocks
        assert out == ""  # No stdout JSON
        assert "openspec/changes/" in err

    def test_edit_design_doc_warns(self):
        """Editing docs/plans/*design* also warns on stderr."""
        code, out, err = _run_hook("design_doc_location_guard", "PostToolUse",
                                   tool_name="Edit",
                                   file_path="/Users/me/project/docs/plans/feature-design.md")
        assert code == 0
        assert out == ""
        assert "advisory" in err.lower()

    def test_plans_non_design_allows(self):
        """Files in docs/plans/ without 'design' in the name are silently allowed."""
        code, out, err = _run_hook("design_doc_location_guard", "PostToolUse",
                                   tool_name="Write",
                                   file_path="docs/plans/2026-03-20-migration-notes.md")
        assert code == 0
        assert out == ""
        assert err == ""

    def test_invalid_json_allows(self):
        """Invalid JSON on stdin fails open."""
        import design_doc_location_guard
        with patch("sys.stdin", io.StringIO("not json")):
            result = design_doc_location_guard.main()
        assert result == 0

    def test_is_design_doc_path_cases(self):
        """Pattern matching for various path formats."""
        from design_doc_location_guard import is_design_doc_path
        assert is_design_doc_path("docs/plans/my-design.md")
        assert is_design_doc_path("/abs/path/docs/plans/2026-design-auth.md")
        assert is_design_doc_path("docs/plans/DESIGN-review.md")  # case insensitive
        assert not is_design_doc_path("docs/plans/migration.md")
        assert not is_design_doc_path("src/design.py")
        assert not is_design_doc_path("openspec/changes/auth-design.md")


# ===========================================================================
# Control 3: openspec_init_guard
# ===========================================================================

class TestOpenspecInitGuard:
    """Tests for openspec_init_guard.py."""

    def test_non_pretooluse_allows(self):
        """Non-PreToolUse events are fast-path allowed."""
        code, _, _ = _run_hook("openspec_init_guard", "PostToolUse",
                               command="openspec list")
        assert code == 0

    def test_non_bash_allows(self):
        """Non-Bash tools are fast-path allowed."""
        code, _, _ = _run_hook("openspec_init_guard", "PreToolUse",
                               tool_name="Write", command="openspec list")
        assert code == 0

    def test_non_openspec_command_allows(self):
        """Commands without 'openspec' are fast-path allowed."""
        code, _, _ = _run_hook("openspec_init_guard", "PreToolUse",
                               command="ls -la")
        assert code == 0

    def test_openspec_init_always_allowed(self):
        """openspec init is always allowed even without openspec/."""
        # init is always-allowed before openspec_is_initialized is even called
        code, _, _ = _run_hook("openspec_init_guard", "PreToolUse",
                               command="openspec init", cwd="/tmp/no-project")
        assert code == 0

    def test_openspec_init_with_path_allowed(self):
        """openspec init <path> is always allowed."""
        code, _, _ = _run_hook("openspec_init_guard", "PreToolUse",
                               command="openspec init ./my-project", cwd="/tmp/no-project")
        assert code == 0

    def test_openspec_help_allowed(self):
        """openspec --help is always allowed."""
        code, _, _ = _run_hook("openspec_init_guard", "PreToolUse",
                               command="openspec --help", cwd="/tmp/no-project")
        assert code == 0

    def test_openspec_version_allowed(self):
        """openspec --version is always allowed."""
        code, _, _ = _run_hook("openspec_init_guard", "PreToolUse",
                               command="openspec --version", cwd="/tmp/no-project")
        assert code == 0

    def test_openspec_config_allowed(self):
        """openspec config is always allowed (global config, no project needed)."""
        code, _, _ = _run_hook("openspec_init_guard", "PreToolUse",
                               command="openspec config", cwd="/tmp/no-project")
        assert code == 0

    def test_openspec_list_blocks_without_init(self):
        """openspec list blocks when openspec/ doesn't exist in cwd from payload."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # tmpdir has no openspec/ subdirectory
            code, out, _ = _run_hook("openspec_init_guard", "PreToolUse",
                                     command="openspec list", cwd=tmpdir)
        assert code == 2
        data = json.loads(out)
        reason = data["hookSpecificOutput"]["permissionDecisionReason"]
        assert "openspec init" in reason

    def test_openspec_change_blocks_without_init(self):
        """openspec change blocks when openspec/ doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            code, _, _ = _run_hook("openspec_init_guard", "PreToolUse",
                                   command="openspec change create my-change", cwd=tmpdir)
        assert code == 2

    def test_openspec_list_allows_when_initialized(self):
        """openspec list is allowed when openspec/ exists in cwd from payload."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.makedirs(os.path.join(tmpdir, "openspec"))
            code, _, _ = _run_hook("openspec_init_guard", "PreToolUse",
                                   command="openspec list", cwd=tmpdir)
        assert code == 0

    def test_openspec_is_initialized_function(self):
        """openspec_is_initialized checks for real directory at given path."""
        from openspec_init_guard import openspec_is_initialized
        with tempfile.TemporaryDirectory() as tmpdir:
            assert not openspec_is_initialized(tmpdir)
            os.makedirs(os.path.join(tmpdir, "openspec"))
            assert openspec_is_initialized(tmpdir)

    def test_openspec_is_initialized_empty_path(self):
        """openspec_is_initialized returns False for empty path."""
        from openspec_init_guard import openspec_is_initialized
        assert not openspec_is_initialized("")

    def test_cwd_from_payload_used(self):
        """The hook reads cwd from the JSON payload, not os.getcwd()."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create openspec/ in tmpdir
            os.makedirs(os.path.join(tmpdir, "openspec"))
            # Even if os.getcwd() points elsewhere, cwd from payload is used
            code, _, _ = _run_hook("openspec_init_guard", "PreToolUse",
                                   command="openspec list", cwd=tmpdir)
        assert code == 0

    def test_invalid_json_allows(self):
        """Invalid JSON on stdin fails open."""
        import openspec_init_guard
        with patch("sys.stdin", io.StringIO("garbage")):
            result = openspec_init_guard.main()
        assert result == 0
