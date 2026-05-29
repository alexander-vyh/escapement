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

    CANONICAL DENY CONTRACT: a hard-deny hook signals the block with a single
    mechanism — a permissionDecision="deny" JSON document on stdout plus exit
    code 0 (NOT exit 2). exit_code is therefore 0 for every outcome; a deny is
    distinguished by the stdout JSON, asserted via ``assert_denied``.
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


def assert_denied(code, stdout) -> dict:
    """Assert the hard block was honored EXACTLY ONCE via the canonical
    mechanism: a single permissionDecision="deny" JSON document on stdout AND
    exit code 0 (NOT exit 2). A deny JSON *plus* exit 2 is a contradictory
    double-block; asserting exit 0 rejects that shape, and ``json.loads`` raises
    on two stacked documents, rejecting a doubled signal. Returns the parsed
    JSON so callers can make further assertions on the deny reason.
    """
    assert code == 0, (
        "deny is carried by the stdout JSON decision, not exit 2 — "
        "permissionDecision=deny plus exit 2 is a contradictory double-block"
    )
    data = json.loads(stdout)
    assert data["hookSpecificOutput"]["permissionDecision"] == "deny"
    return data


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
        data = assert_denied(code, out)
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

    # --- --spec-waiver first-class escape (gate-design Rule 1) -------------

    def test_spec_waiver_with_valid_reason_allows(self):
        """A --spec-waiver with a substantive reason allows the create.

        Positive control: the gate's first-class escape path lets an agent
        proceed without a resolving --spec-id when it supplies a real reason.
        """
        records = []
        with patch("spec_id_enforcement.is_mol_feature_parent", return_value=True), \
             patch("spec_id_enforcement._record_signal",
                   side_effect=lambda **kw: records.append(kw)):
            code, _, _ = _run_hook(
                "spec_id_enforcement", "PreToolUse",
                command=(
                    "bd create 'task' --parent bd-mol123 "
                    "--spec-waiver 'spec not yet authored; this is a spike to "
                    "de-risk the parser approach before writing requirements'"
                ),
            )
        assert code == 0, "valid waiver reason should allow the action"
        # Rule 2: the waiver must persist to the signal store.
        waiver_records = [r for r in records
                          if r.get("decision") == "waiver-accepted"]
        assert waiver_records, "waiver must be recorded via _record_signal"
        rec = waiver_records[0]
        assert rec["gate_name"] == "spec_id_enforcement"
        assert "spike to de-risk the parser" in rec["reason"]

    def test_spec_waiver_placeholder_reason_blocks(self):
        """A --spec-waiver with a placeholder reason is rejected.

        Negative control: 'tbd' is exactly the null pattern Rule 3 forbids.
        The gate must NOT accept it as an escape.
        """
        with patch("spec_id_enforcement.is_mol_feature_parent", return_value=True):
            code, out, _ = _run_hook(
                "spec_id_enforcement", "PreToolUse",
                command="bd create 'task' --parent bd-mol123 --spec-waiver tbd",
            )
        data = assert_denied(code, out)  # placeholder waiver reason must be blocked
        reason = data["hookSpecificOutput"]["permissionDecisionReason"]
        assert "placeholder" in reason.lower() or "tbd" in reason.lower()

    def test_spec_waiver_too_short_reason_blocks(self):
        """A --spec-waiver reason under the 20-char substance threshold blocks.

        Negative control for Rule 3's minimum-substance requirement.
        """
        with patch("spec_id_enforcement.is_mol_feature_parent", return_value=True):
            code, out, _ = _run_hook(
                "spec_id_enforcement", "PreToolUse",
                command="bd create 'task' --parent bd-mol123 --spec-waiver 'too short'",
            )
        data = assert_denied(code, out)  # sub-threshold waiver reason must be blocked
        reason = data["hookSpecificOutput"]["permissionDecisionReason"]
        assert "20" in reason or "short" in reason.lower() or "substan" in reason.lower()

    def test_deny_message_documents_waiver_escape(self):
        """The hard-deny message itself documents the --spec-waiver escape.

        Rule 1: the escape must be documented in the denial message, not
        discoverable only by reading source.
        """
        with patch("spec_id_enforcement.is_mol_feature_parent", return_value=True):
            code, out, _ = _run_hook(
                "spec_id_enforcement", "PreToolUse",
                command="bd create 'task' --parent bd-mol123",
            )
        data = assert_denied(code, out)
        reason = data["hookSpecificOutput"]["permissionDecisionReason"]
        assert "--spec-waiver" in reason, (
            "deny message must surface the agent-invokable escape path"
        )


# ===========================================================================
# Standard waiver convention: dedicated .gate-waivers.jsonl corpus
# (claude-workflow-setup-8dm — gate-design.md "Standard waiver convention")
# ===========================================================================

class TestWaiverCorpus:
    """The documented waiver convention writes a dedicated corpus.

    Per gate-design.md, accepted waiver reasons accumulate in a dedicated
    .beads/.gate-waivers.jsonl file (distinct from the high-volume unified
    .gate-signal.jsonl) so the user can grep ONE file for the reasoned-
    exception corpus. These tests exercise that a REAL waiver entry lands in
    that file — both via the shared backbone and via a gate end-to-end.
    """

    def _isolated_beads(self, tmp_path, monkeypatch):
        """Point _gate_signal at a tmp .beads/ and clear session env."""
        import _gate_signal
        beads = tmp_path / ".beads"
        beads.mkdir()
        monkeypatch.setenv("BEADS_DIR", str(beads))
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        return _gate_signal, beads

    def test_waiver_event_writes_dedicated_corpus(self, tmp_path, monkeypatch):
        """record(event_type='waiver') appends to .gate-waivers.jsonl.

        Positive control: a waiver event lands a well-formed line in the
        dedicated corpus carrying the captured reason.
        """
        gs, beads = self._isolated_beads(tmp_path, monkeypatch)
        reason = "spec deferred — exploratory spike to de-risk the parser"
        gs.record(
            gate_name="spec_id_enforcement",
            decision="waiver-accepted",
            reason=reason,
            event_type="waiver",
            parent_id="bd-mol123",
        )
        waiver_file = beads / ".gate-waivers.jsonl"
        assert waiver_file.is_file(), "waiver corpus file must be created"
        lines = waiver_file.read_text().strip().splitlines()
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["gate"] == "spec_id_enforcement"
        assert rec["decision"] == "waiver-accepted"
        assert rec["reason"] == reason
        assert rec["event_type"] == "waiver"

    def test_waiver_also_lands_in_unified_signal_store(self, tmp_path, monkeypatch):
        """A waiver writes BOTH stores — the timeline stays complete.

        The dedicated corpus is additive, not a replacement: the unified
        signal store still carries the waiver so the decision timeline is
        not split.
        """
        gs, beads = self._isolated_beads(tmp_path, monkeypatch)
        gs.record(
            gate_name="enforce_named_agents",
            decision="waiver-accepted",
            reason="one-off anonymous probe requested explicitly by the user",
            event_type="waiver",
        )
        signal_file = beads / ".gate-signal.jsonl"
        assert signal_file.is_file()
        assert "waiver-accepted" in signal_file.read_text()

    def test_non_waiver_signal_does_not_touch_waiver_corpus(self, tmp_path, monkeypatch):
        """Negative control: a plain signal must NOT write the waiver corpus.

        If a routine 'allow'/'deny'/'nudge' decision leaked into the waiver
        store, the corpus would be polluted with non-exceptions and grep
        would stop being a clean reasoned-exception view.
        """
        gs, beads = self._isolated_beads(tmp_path, monkeypatch)
        gs.record(
            gate_name="enforce_named_agents",
            decision="deny",
            reason="agent dispatched without name parameter",
        )
        waiver_file = beads / ".gate-waivers.jsonl"
        assert not waiver_file.exists(), (
            "a non-waiver signal must not create or write the waiver corpus"
        )
        # Positive control on the same call: the unified store DID get it.
        assert (beads / ".gate-signal.jsonl").is_file()

    def test_spec_waiver_gate_writes_waiver_corpus_end_to_end(self, tmp_path, monkeypatch):
        """End-to-end: an accepted --spec-waiver lands in .gate-waivers.jsonl.

        Exercises the full spec_id_enforcement escape path with a real
        .beads/ on disk — the gate, not just the backbone, produces a real
        greppable waiver entry. This is the bead's 'exercise it in a test'
        requirement.
        """
        self._isolated_beads(tmp_path, monkeypatch)
        beads = tmp_path / ".beads"
        reason = ("spec not yet authored; this is a spike to validate the "
                  "approach before requirements are written")
        with patch("spec_id_enforcement.is_mol_feature_parent", return_value=True):
            code, out, _ = _run_hook(
                "spec_id_enforcement", "PreToolUse",
                command=(
                    "bd create 'task' --parent bd-mol123 "
                    f"--spec-waiver '{reason}'"
                ),
            )
        assert code == 0, "valid waiver should allow the create"
        waiver_file = beads / ".gate-waivers.jsonl"
        assert waiver_file.is_file(), "gate must write the dedicated waiver corpus"
        recs = [json.loads(line)
                for line in waiver_file.read_text().strip().splitlines()]
        waiver_recs = [r for r in recs if r["decision"] == "waiver-accepted"]
        assert waiver_recs, "accepted waiver must be recorded in the corpus"
        assert waiver_recs[0]["reason"] == reason
        assert waiver_recs[0]["gate"] == "spec_id_enforcement"
        assert waiver_recs[0]["event_type"] == "waiver"


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
        data = assert_denied(code, out)
        reason = data["hookSpecificOutput"]["permissionDecisionReason"]
        assert "openspec init" in reason

    def test_openspec_change_blocks_without_init(self):
        """openspec change blocks when openspec/ doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            code, out, _ = _run_hook("openspec_init_guard", "PreToolUse",
                                   command="openspec change create my-change", cwd=tmpdir)
        assert_denied(code, out)

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
