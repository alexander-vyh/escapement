"""Unit tests for discovery_input_gate.py.

The hook blocks Write/Edit of a solution artifact (proposal.md / design.md) under
an OpenSpec feature/epic change unless a confirmed problem-framing.md exists with
all six required fields *filled*.

Uniform rule: any unfilled field (missing header, empty body, or a TBD-style
marker) -> deny. There is no special-cased field and no "ask" path. A field that
genuinely does not apply is filled with "none - <reason>", which counts as filled.

Run from anywhere with:
  python -m pytest ~/.claude/hooks/tests/test_discovery_input_gate.py -v
"""

import io
import json
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
# Fixtures
# ---------------------------------------------------------------------------

COMPLETE_FRAMING = """# Problem Framing - my-feature

## Problem
Users cannot reset their password without contacting support.

## Why Now
Support ticket volume for password resets has tripled this quarter.

## Decision Authority
Jane Smith, PM

## Behavioral Population
End users who have forgotten their password.

## Riskiest Assumption
We are betting a self-service email flow covers 90% of cases. Wrong when support
volume does not drop. We would know within 2 weeks via ticket metrics.

## Success Criteria
Password-reset support tickets drop by 80% within one month.
"""

# Decision Authority and Behavioral Population answered with a considered "none".
# This is a VALID, filled framing - the document-if-none case.
FRAMING_NONE_WITH_REASON = """# Problem Framing - solo-parser

## Problem
The config parser silently drops unknown keys instead of erroring.

## Why Now
A dropped key caused a production misconfiguration last week.

## Decision Authority
none - solo project, I own it.

## Behavioral Population
none - standalone library, success is correctness, not adoption.

## Riskiest Assumption
We are betting strict-mode-by-default will not break existing callers. Wrong when
a caller relied on the silent drop. We would know within 2 weeks via the test
suite plus one release cycle.

## Success Criteria
Unknown keys raise a clear error; zero silent drops in the parse path.
"""

FRAMING_MISSING_HEADERS = """# Problem Framing - my-feature

## Problem
Users cannot reset their password.

## Why Now
Tickets tripled.

## Decision Authority
Jane Smith, PM
"""

FRAMING_AUTHORITY_TBD = COMPLETE_FRAMING.replace("Jane Smith, PM", "TBD")

FRAMING_WHY_NOW_TBD = COMPLETE_FRAMING.replace(
    "Support ticket volume for password resets has tripled this quarter.", "TODO")

FRAMING_AUTHORITY_EMPTY = COMPLETE_FRAMING.replace("Jane Smith, PM\n", "\n")


def _make_change(tmpdir, name="my-feature", schema="feature", framing=None):
    """Create openspec/changes/{name}/ with .openspec.yaml + optional problem-framing.md.

    Returns the absolute path to design.md within that change dir (not created).
    """
    change_dir = Path(tmpdir) / "openspec" / "changes" / name
    change_dir.mkdir(parents=True)
    if schema is not None:
        (change_dir / ".openspec.yaml").write_text(
            f"schema: {schema}\ncreated: 2026-05-14\n")
    if framing is not None:
        (change_dir / "problem-framing.md").write_text(framing)
    return str(change_dir / "design.md")


def _run_hook(hook_event="PreToolUse", tool_name="Write", file_path="",
              raw_stdin=None):
    """Run discovery_input_gate.main() and return (exit_code, stdout, stderr)."""
    import importlib
    mod = importlib.import_module("discovery_input_gate")

    if raw_stdin is None:
        payload = {"hook_event_name": hook_event, "tool_name": tool_name,
                   "tool_input": {"file_path": file_path}}
        stdin_data = json.dumps(payload)
    else:
        stdin_data = raw_stdin

    out, err = io.StringIO(), io.StringIO()
    try:
        with patch("sys.stdin", io.StringIO(stdin_data)), \
             patch("sys.stdout", out), patch("sys.stderr", err):
            mod.main()
        return 0, out.getvalue(), err.getvalue()
    except SystemExit as exc:
        return exc.code, out.getvalue(), err.getvalue()


def _decision(stdout):
    """Extract permissionDecision from a hook's JSON stdout, or None."""
    if not stdout.strip():
        return None
    return json.loads(stdout)["hookSpecificOutput"]["permissionDecision"]


# ===========================================================================
# Pure function: is_gated_artifact
# ===========================================================================

class TestIsGatedArtifact:
    def test_design_md_is_gated(self):
        from discovery_input_gate import is_gated_artifact
        assert is_gated_artifact("/x/openspec/changes/foo/design.md") \
            == "/x/openspec/changes/foo"

    def test_proposal_md_is_gated(self):
        from discovery_input_gate import is_gated_artifact
        assert is_gated_artifact("/x/openspec/changes/foo/proposal.md") \
            == "/x/openspec/changes/foo"

    def test_problem_framing_is_never_gated(self):
        """Writing the framing itself must always be allowed."""
        from discovery_input_gate import is_gated_artifact
        assert is_gated_artifact("/x/openspec/changes/foo/problem-framing.md") is None

    def test_tasks_md_not_gated(self):
        from discovery_input_gate import is_gated_artifact
        assert is_gated_artifact("/x/openspec/changes/foo/tasks.md") is None

    def test_specs_file_not_gated(self):
        from discovery_input_gate import is_gated_artifact
        assert is_gated_artifact("/x/openspec/changes/foo/specs/auth.md") is None

    def test_unrelated_file_not_gated(self):
        from discovery_input_gate import is_gated_artifact
        assert is_gated_artifact("/x/src/main.py") is None

    def test_design_md_outside_openspec_not_gated(self):
        from discovery_input_gate import is_gated_artifact
        assert is_gated_artifact("/x/docs/design.md") is None


# ===========================================================================
# Pure function: read_schema
# ===========================================================================

class TestReadSchema:
    def test_reads_feature(self):
        from discovery_input_gate import read_schema
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".openspec.yaml").write_text("schema: feature\ncreated: x\n")
            assert read_schema(tmp) == "feature"

    def test_reads_rapid(self):
        from discovery_input_gate import read_schema
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".openspec.yaml").write_text("schema: rapid\n")
            assert read_schema(tmp) == "rapid"

    def test_missing_yaml_returns_none(self):
        from discovery_input_gate import read_schema
        with tempfile.TemporaryDirectory() as tmp:
            assert read_schema(tmp) is None


# ===========================================================================
# Pure function: validate_framing  ->  {"exists": bool, "bad": [field names]}
# ===========================================================================

class TestValidateFraming:
    def test_complete_framing_has_no_bad_fields(self):
        from discovery_input_gate import validate_framing
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "problem-framing.md"
            p.write_text(COMPLETE_FRAMING)
            result = validate_framing(str(p))
        assert result["exists"] is True
        assert result["bad"] == []

    def test_none_with_reason_is_a_filled_field(self):
        """'none - <reason>' is a considered judgment, not an unfilled field."""
        from discovery_input_gate import validate_framing
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "problem-framing.md"
            p.write_text(FRAMING_NONE_WITH_REASON)
            result = validate_framing(str(p))
        assert result["exists"] is True
        assert result["bad"] == []

    def test_missing_file(self):
        from discovery_input_gate import validate_framing
        result = validate_framing("/nonexistent/problem-framing.md")
        assert result["exists"] is False

    def test_missing_headers_are_bad(self):
        from discovery_input_gate import validate_framing
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "problem-framing.md"
            p.write_text(FRAMING_MISSING_HEADERS)
            result = validate_framing(str(p))
        assert "Behavioral Population" in result["bad"]
        assert "Riskiest Assumption" in result["bad"]
        assert "Success Criteria" in result["bad"]
        # the three present-and-filled fields are NOT bad
        assert "Problem" not in result["bad"]

    def test_tbd_field_is_bad_no_special_casing(self):
        """A TBD field is bad regardless of WHICH field it is."""
        from discovery_input_gate import validate_framing
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "problem-framing.md"
            p.write_text(FRAMING_AUTHORITY_TBD)
            result = validate_framing(str(p))
        assert result["bad"] == ["Decision Authority"]
        # prove it's not authority-specific: a TBD Why Now is equally bad
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "problem-framing.md"
            p.write_text(FRAMING_WHY_NOW_TBD)
            result = validate_framing(str(p))
        assert result["bad"] == ["Why Now"]

    def test_empty_body_is_bad(self):
        from discovery_input_gate import validate_framing
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "problem-framing.md"
            p.write_text(FRAMING_AUTHORITY_EMPTY)
            result = validate_framing(str(p))
        assert result["bad"] == ["Decision Authority"]


# ===========================================================================
# Hook behavior - fast-path allows
# ===========================================================================

class TestFastPathAllows:
    def test_non_pretooluse_allows(self):
        code, out, _ = _run_hook(hook_event="PostToolUse",
                                 file_path="/x/openspec/changes/f/design.md")
        assert code == 0
        assert out == ""

    def test_non_write_edit_allows(self):
        code, out, _ = _run_hook(tool_name="Bash",
                                 file_path="/x/openspec/changes/f/design.md")
        assert code == 0
        assert out == ""

    def test_unrelated_file_allows(self):
        code, out, _ = _run_hook(file_path="/x/src/main.py")
        assert code == 0
        assert out == ""

    def test_problem_framing_write_allows(self):
        """Writing the framing itself is never gated."""
        with tempfile.TemporaryDirectory() as tmp:
            design = _make_change(tmp, schema="feature", framing=None)
            framing_path = str(Path(design).parent / "problem-framing.md")
            code, out, _ = _run_hook(file_path=framing_path)
        assert code == 0
        assert out == ""

    def test_invalid_json_stdin_allows(self):
        """Malformed stdin fails open."""
        code, _, _ = _run_hook(raw_stdin="not json at all")
        assert code == 0


# ===========================================================================
# Hook behavior - rapid schema is exempt
# ===========================================================================

class TestRapidExempt:
    def test_rapid_no_framing_allows(self):
        with tempfile.TemporaryDirectory() as tmp:
            design = _make_change(tmp, schema="rapid", framing=None)
            code, out, _ = _run_hook(file_path=design)
        assert code == 0
        assert out == ""


# ===========================================================================
# Hook behavior - feature/epic gate (uniform deny, no ask path)
# ===========================================================================

class TestFeatureGate:
    def test_feature_no_framing_denies(self):
        """Negative control: feature change, no framing -> DENY."""
        with tempfile.TemporaryDirectory() as tmp:
            design = _make_change(tmp, schema="feature", framing=None)
            code, out, _ = _run_hook(file_path=design)
        assert code == 2
        assert _decision(out) == "deny"

    def test_epic_no_framing_denies(self):
        with tempfile.TemporaryDirectory() as tmp:
            design = _make_change(tmp, schema="epic", framing=None)
            code, out, _ = _run_hook(file_path=design)
        assert code == 2
        assert _decision(out) == "deny"

    def test_feature_complete_framing_allows(self):
        """Positive control: feature change, complete framing -> ALLOW."""
        with tempfile.TemporaryDirectory() as tmp:
            design = _make_change(tmp, schema="feature", framing=COMPLETE_FRAMING)
            code, out, _ = _run_hook(file_path=design)
        assert code == 0
        assert out == ""

    def test_none_with_reason_framing_allows(self):
        """Positive control: 'none - reason' in authority/population -> ALLOW.

        This is the document-if-none case: a solo project with no distinct owner
        and a library with no behavioral population is a fully valid framing.
        """
        with tempfile.TemporaryDirectory() as tmp:
            design = _make_change(tmp, name="solo-parser", schema="feature",
                                  framing=FRAMING_NONE_WITH_REASON)
            code, out, _ = _run_hook(file_path=design)
        assert code == 0
        assert out == ""

    def test_feature_proposal_md_also_gated(self):
        with tempfile.TemporaryDirectory() as tmp:
            design = _make_change(tmp, schema="feature", framing=None)
            proposal = str(Path(design).parent / "proposal.md")
            code, out, _ = _run_hook(file_path=proposal)
        assert code == 2
        assert _decision(out) == "deny"

    def test_feature_edit_tool_also_gated(self):
        """Edit, not just Write, is gated."""
        with tempfile.TemporaryDirectory() as tmp:
            design = _make_change(tmp, schema="feature", framing=None)
            code, out, _ = _run_hook(tool_name="Edit", file_path=design)
        assert code == 2
        assert _decision(out) == "deny"

    def test_tbd_field_denies(self):
        """A TBD field denies - no 'ask' path, no special-casing."""
        with tempfile.TemporaryDirectory() as tmp:
            design = _make_change(tmp, schema="feature", framing=FRAMING_AUTHORITY_TBD)
            code, out, _ = _run_hook(file_path=design)
        assert code == 2
        assert _decision(out) == "deny"

    def test_non_authority_tbd_also_denies(self):
        """Proves uniformity: a TBD Why Now denies exactly like a TBD authority."""
        with tempfile.TemporaryDirectory() as tmp:
            design = _make_change(tmp, schema="feature", framing=FRAMING_WHY_NOW_TBD)
            code, out, _ = _run_hook(file_path=design)
        assert code == 2
        assert _decision(out) == "deny"

    def test_missing_headers_denies(self):
        """Missing field headers deny (previously 'ask' - now uniform deny)."""
        with tempfile.TemporaryDirectory() as tmp:
            design = _make_change(tmp, schema="feature",
                                  framing=FRAMING_MISSING_HEADERS)
            code, out, _ = _run_hook(file_path=design)
        assert code == 2
        assert _decision(out) == "deny"
        # the deny message names the specific missing fields
        reason = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
        assert "Riskiest Assumption" in reason

    def test_fragile_impl_rejected_empty_framing(self):
        """Fragile-impl guard: an existence-only check would pass an empty
        problem-framing.md. The content check must deny it."""
        with tempfile.TemporaryDirectory() as tmp:
            design = _make_change(tmp, schema="feature", framing="")
            code, out, _ = _run_hook(file_path=design)
        assert code == 2
        assert _decision(out) == "deny"


# ===========================================================================
# Hook behavior - fail-closed on unverifiable schema
# ===========================================================================

class TestFailClosed:
    def test_no_openspec_yaml_no_framing_denies(self):
        """Cannot read schema + no framing -> fail closed -> DENY."""
        with tempfile.TemporaryDirectory() as tmp:
            design = _make_change(tmp, schema=None, framing=None)
            code, out, _ = _run_hook(file_path=design)
        assert code == 2
        assert _decision(out) == "deny"

    def test_no_openspec_yaml_complete_framing_allows(self):
        """Cannot read schema, but a complete framing is present -> ALLOW."""
        with tempfile.TemporaryDirectory() as tmp:
            design = _make_change(tmp, schema=None, framing=COMPLETE_FRAMING)
            code, out, _ = _run_hook(file_path=design)
        assert code == 0
        assert out == ""
