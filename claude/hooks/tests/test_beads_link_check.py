"""Behavioral tests for the beads-openspec-link-check walking skeleton.

OpenSpec change: openspec/changes/beads-openspec-link-check.

Business invariant
------------------
For one OpenSpec change, the command answers — from live Beads state — whether
each Bead's ``spec_id`` link is honest (resolves to a live OpenSpec anchor). It
MUST fail closed (non-zero exit) on, and only on, a closed two-member set of
link-integrity violations: an orphaned ``spec_id`` (target file/anchor missing)
and a present-but-unresolved ``spec_id`` (anchor renamed). Every other state —
blocked work, a requirement with no linked Beads, and a Bead that merely
*mentions* a change path in prose without a ``spec_id`` (silence, not a claim) —
is ADVISORY and MUST exit zero. The command writes no file and mutates nothing.

Independent source of truth
---------------------------
The OpenSpec spec markdown on disk (its ``### Requirement: <name>`` anchors) and
the Beads issue records. Resolution semantics are the repo's existing
``spec_id_preflight.check_spec_id`` — reused, not re-defined, so there is one
definition of "resolves" in the repo.

Oracle quality (the fragile implementations these tests reject)
--------------------------------------------------------------
- POSITIVE CONTROL: a Bead whose ``spec_id`` resolves is counted toward coverage
  and is NOT a violation (rejects a checker that flags everything / fails closed
  blindly).
- NEGATIVE CONTROL #1 (orphan): a Bead whose ``spec_id`` file is gone is a
  violation and drives a non-zero exit.
- NEGATIVE CONTROL #2 (renamed anchor, present-but-unresolved): same file, only
  the heading renamed — a violation and non-zero exit. Rejects the "file exists =
  OK" shortcut, which is a false GREEN strictly worse than an orphan.
- LIE/SILENCE DISCRIMINATOR: a Bead with NO ``spec_id`` whose description merely
  pastes the change path is NOT counted as linked AND is NOT a violation AND does
  NOT change the exit code. Rejects (a) grep-mention-counted-as-link and (b) the
  redraft's own introduced bug of fail-closing on free prose (which would earn a
  ``|| true`` and disable the gate).
- PROGRESS-NOT-A-LIE: blocked work and missing coverage are advisory, exit zero.
  Rejects conflating "not done yet" with "the link lies".
- DETERMINISM: stdout is byte-identical across two runs on identical inputs;
  volatile metadata (a generated-at timestamp) is on stderr, so stdout carries no
  exclusion hatch.
- NON-DURABILITY: the command creates no file (the authority boundary is enforced
  by absence of a durable artifact, not by a disclaimer string).
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

# Import the production module by path, regardless of cwd. No skip guard: if the
# module is absent the import MUST fail loudly so the done-oracle goes red.
_BIN_DIR = Path(__file__).resolve().parents[2] / "bin"
_MODULE_PATH = _BIN_DIR / "beads_link_check.py"
_spec = importlib.util.spec_from_file_location("beads_link_check", _MODULE_PATH)
blc = importlib.util.module_from_spec(_spec)
sys.modules["beads_link_check"] = blc
_spec.loader.exec_module(blc)


CHANGE = "demo-change"


def _make_project(tmp_path: Path) -> Path:
    """Create a project dir with one change whose spec has two requirements."""
    spec_dir = tmp_path / "openspec" / "changes" / CHANGE / "specs" / "demo-cap"
    spec_dir.mkdir(parents=True)
    (spec_dir / "spec.md").write_text(
        "## ADDED Requirements\n\n"
        "### Requirement: Alpha behavior\n\n"
        "The system SHALL do alpha.\n\n"
        "#### Scenario: alpha happens\n\n"
        "- **WHEN** x\n- **THEN** y\n\n"
        "### Requirement: Beta behavior\n\n"
        "The system SHALL do beta.\n\n"
        "#### Scenario: beta happens\n\n"
        "- **WHEN** x\n- **THEN** y\n",
        encoding="utf-8",
    )
    return tmp_path


def _spec_path(anchor: str) -> str:
    return f"openspec/changes/{CHANGE}/specs/demo-cap/spec.md#{anchor}"


def _issue(bead_id: str, *, spec_id=None, status="open", description=""):
    issue = {"id": bead_id, "status": status, "description": description}
    if spec_id is not None:
        issue["spec_id"] = spec_id
    return issue


# ---------------------------------------------------------------------------
# Pure-core tests: build_report(issues, change, project_dir)
# ---------------------------------------------------------------------------

def test_resolving_link_counts_and_is_not_a_violation(tmp_path):
    """POSITIVE CONTROL: a resolving spec_id is coverage, not a violation."""
    proj = _make_project(tmp_path)
    issues = [_issue("bd-1", spec_id=_spec_path("Alpha behavior"))]
    report = blc.build_report(issues, CHANGE, proj)

    assert report.exit_code == 0
    assert report.integrity_violations == []
    # Alpha is covered by bd-1; Beta has no linked bead -> missing coverage.
    assert "bd-1" in report.coverage.get("alpha behavior", [])
    assert "beta behavior" in report.missing_coverage


def test_orphaned_spec_id_is_a_violation_and_fails_closed(tmp_path):
    """NEGATIVE CONTROL #1: missing file -> violation, non-zero exit."""
    proj = _make_project(tmp_path)
    issues = [
        _issue("bd-1", spec_id=_spec_path("Alpha behavior")),
        _issue("bd-2", spec_id=f"openspec/changes/{CHANGE}/specs/gone/spec.md#Alpha behavior"),
    ]
    report = blc.build_report(issues, CHANGE, proj)

    assert report.exit_code != 0
    violated = {v.bead_id for v in report.integrity_violations}
    assert "bd-2" in violated
    assert "bd-1" not in violated


def test_renamed_anchor_is_a_violation_not_a_false_green(tmp_path):
    """NEGATIVE CONTROL #2: present-but-unresolved anchor -> violation."""
    proj = _make_project(tmp_path)
    # Anchor that does not exist as a heading in the (present) spec file.
    issues = [_issue("bd-9", spec_id=_spec_path("Gamma behavior"))]
    report = blc.build_report(issues, CHANGE, proj)

    assert report.exit_code != 0
    violated = {v.bead_id for v in report.integrity_violations}
    assert "bd-9" in violated
    # It must NOT be counted as coverage for any requirement (false green).
    for beads in report.coverage.values():
        assert "bd-9" not in beads


def test_description_only_mention_is_advisory_not_a_lie(tmp_path):
    """LIE/SILENCE DISCRIMINATOR: prose mention, no spec_id -> advisory, exit 0."""
    proj = _make_project(tmp_path)
    issues = [
        _issue("bd-1", spec_id=_spec_path("Alpha behavior")),
        _issue(
            "bd-prose",
            spec_id=None,
            description=f"see openspec/changes/{CHANGE}/specs/demo-cap/spec.md for context",
        ),
    ]
    report = blc.build_report(issues, CHANGE, proj)

    # The prose-only bead is NOT a violation and does NOT change the exit code.
    assert report.exit_code == 0
    violated = {v.bead_id for v in report.integrity_violations}
    assert "bd-prose" not in violated
    # It is NOT counted as linked coverage.
    for beads in report.coverage.values():
        assert "bd-prose" not in beads
    # It is surfaced as an advisory unlinked mention.
    assert "bd-prose" in {a.bead_id for a in report.advisory_unlinked}


def test_blocked_work_is_advisory_exit_zero(tmp_path):
    """PROGRESS-NOT-A-LIE: a blocked bead with a resolving link is advisory."""
    proj = _make_project(tmp_path)
    issues = [_issue("bd-1", spec_id=_spec_path("Alpha behavior"), status="blocked")]
    report = blc.build_report(issues, CHANGE, proj)

    assert report.exit_code == 0
    assert "bd-1" in {a.bead_id for a in report.advisory_blocked}


def test_missing_coverage_is_advisory_not_inferred(tmp_path):
    """A requirement with no linked bead is advisory; coverage is not inferred."""
    proj = _make_project(tmp_path)
    report = blc.build_report([], CHANGE, proj)

    assert report.exit_code == 0
    assert set(report.missing_coverage) == {"alpha behavior", "beta behavior"}


# ---------------------------------------------------------------------------
# CLI tests: exit code, determinism, stdout/stderr split, non-durability
# ---------------------------------------------------------------------------

def _run_cli(proj: Path, issues: list, tmp_path: Path):
    issues_file = tmp_path / "issues.json"
    issues_file.write_text(json.dumps(issues), encoding="utf-8")
    return subprocess.run(
        [
            sys.executable, str(_MODULE_PATH),
            "--change", CHANGE,
            "--project-dir", str(proj),
            "--issues-file", str(issues_file),
        ],
        capture_output=True, text=True,
    )


def test_cli_exits_nonzero_on_integrity_violation(tmp_path):
    proj = _make_project(tmp_path)
    issues = [_issue("bd-9", spec_id=_spec_path("Gamma behavior"))]
    result = _run_cli(proj, issues, tmp_path)
    assert result.returncode != 0
    # The denial names the clearing action, not just the upstream layer.
    assert "bd update" in result.stdout or "anchor" in result.stdout


def test_cli_exits_zero_on_advisory_only(tmp_path):
    proj = _make_project(tmp_path)
    issues = [_issue("bd-1", spec_id=_spec_path("Alpha behavior"), status="blocked")]
    result = _run_cli(proj, issues, tmp_path)
    assert result.returncode == 0


def test_cli_stdout_is_deterministic_timestamp_on_stderr(tmp_path):
    proj = _make_project(tmp_path)
    issues = [
        _issue("bd-2", spec_id=_spec_path("Beta behavior")),
        _issue("bd-1", spec_id=_spec_path("Alpha behavior")),
    ]
    r1 = _run_cli(proj, issues, tmp_path)
    r2 = _run_cli(proj, issues, tmp_path)
    assert r1.returncode == 0 and r2.returncode == 0
    # stdout byte-identical across runs: no volatile field, records sorted.
    assert r1.stdout == r2.stdout
    # No ISO-ish year leaks into stdout (timestamp must be on stderr).
    assert "2026-" not in r1.stdout


def test_cli_writes_no_file(tmp_path):
    """NON-DURABILITY: the command creates no file under the change dir."""
    proj = _make_project(tmp_path)
    change_dir = proj / "openspec" / "changes" / CHANGE
    before = {p for p in change_dir.rglob("*")}
    issues = [_issue("bd-1", spec_id=_spec_path("Alpha behavior"))]
    _run_cli(proj, issues, tmp_path)
    after = {p for p in change_dir.rglob("*")}
    assert before == after


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
