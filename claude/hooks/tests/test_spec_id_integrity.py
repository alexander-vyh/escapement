"""Behavioral tests for the spec-id referential-integrity preflight.

Bead: escapement-ao0.

Business invariant
------------------
work-breakdown bakes ``--spec-id=...specs/{cap}.md#{requirement}`` into beads
tasks. ``spec_id_enforcement`` validates that the anchor resolves to a real
``### Requirement: ...`` heading AT CREATION TIME. Nothing re-validates after a
later spec edit renames or deletes that heading. The preflight closes that gap:
given the set of (bead-id, spec-id) pairs currently in the tracker, it must
report exactly the beads whose ``file#anchor`` no longer resolves to a real
requirement heading, and exit non-zero iff at least one orphan exists.

Independent source of truth
---------------------------
The spec markdown files on disk. A spec-id is *resolved* iff the path exists
AND (if an anchor is present) some line in that file is
``### Requirement: <name>`` whose name matches the anchor (literal or
kebab->space normalised). A spec-id is *orphaned* otherwise.

Oracle quality
--------------
- POSITIVE CONTROL: a bead whose anchor matches a real heading must NOT be
  flagged (proves the checker does not flag everything / fail closed-blindly).
- NEGATIVE CONTROL: a bead whose anchor was renamed away must be flagged AND
  drive a non-zero exit (proves the checker actually catches the orphan — the
  whole reason the bead exists).
- The renamed-heading fixture is the exact scenario from the bead: same file,
  same path, only the heading text changed. An implementation that merely
  checks "the file exists" (a tempting shortcut) would pass the file but miss
  the orphan — the negative control rejects it.

These tests do NOT read the production source to assert behavior; they exercise
the public entry points (``check_spec_id`` and ``scan_spec_ids``) against
real on-disk fixtures and assert outcomes, not implementation details.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# Import the production module by path so the test runs regardless of cwd /
# sys.path layout. This is the file under test for bead ao0.
_BIN_DIR = Path(__file__).resolve().parents[2] / "bin"
_MODULE_PATH = _BIN_DIR / "spec_id_preflight.py"

# No skip guard: if the module under test is absent, this import MUST fail
# loudly so the done-oracle goes red. A skip here would let the oracle pass
# without the implementation existing (a suppressed failure).
_spec = importlib.util.spec_from_file_location("spec_id_preflight", _MODULE_PATH)
preflight = importlib.util.module_from_spec(_spec)
sys.modules["spec_id_preflight"] = preflight
_spec.loader.exec_module(preflight)


# ---------------------------------------------------------------------------
# Fixtures: a project tree with one spec file and several beads pointing at it
# ---------------------------------------------------------------------------

_SPEC_REL = "openspec/changes/demo/specs/widget.md"

_SPEC_BODY = """\
<!-- Spec: widget -->

## Purpose

The widget capability does widget things.

### Requirement: Render the widget

The widget SHALL render.

#### Scenario: it renders
- WHEN asked
- THEN it renders

### Requirement: Persist widget state

State SHALL persist.
"""


@pytest.fixture()
def project_dir(tmp_path: Path) -> Path:
    """A throwaway project root with one real spec file on disk."""
    spec_path = tmp_path / _SPEC_REL
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    spec_path.write_text(_SPEC_BODY, encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# check_spec_id — the pure resolution core
# ---------------------------------------------------------------------------

def test_resolving_anchor_is_not_orphaned(project_dir: Path) -> None:
    """POSITIVE CONTROL: an anchor matching a real heading resolves."""
    spec_id = f"{_SPEC_REL}#render-the-widget"
    resolved, _reason = preflight.check_spec_id(spec_id, project_dir)
    assert resolved is True


def test_renamed_heading_is_orphaned(project_dir: Path) -> None:
    """NEGATIVE CONTROL: the exact bug — a heading was renamed, so the
    baked-in anchor no longer resolves even though the file still exists."""
    # This anchor matched a heading at creation time, but the spec was later
    # edited and the heading is now "Render the widget" / "Persist widget
    # state" — "display-the-widget" no longer exists.
    spec_id = f"{_SPEC_REL}#display-the-widget"
    resolved, reason = preflight.check_spec_id(spec_id, project_dir)
    assert resolved is False
    assert reason  # a human-readable explanation is provided


def test_file_exists_does_not_imply_resolved(project_dir: Path) -> None:
    """Rejects the tempting 'file exists -> ok' shortcut implementation.

    The path resolves to a real file, but the anchor is gone. A checker that
    only validates the path would call this resolved; it must not."""
    spec_id = f"{_SPEC_REL}#anchor-that-was-renamed-away"
    resolved, _reason = preflight.check_spec_id(spec_id, project_dir)
    assert resolved is False


def test_missing_file_is_orphaned(project_dir: Path) -> None:
    spec_id = "openspec/changes/demo/specs/ghost.md#whatever"
    resolved, _reason = preflight.check_spec_id(spec_id, project_dir)
    assert resolved is False


def test_kebab_and_spaced_anchor_forms_both_resolve(project_dir: Path) -> None:
    """The anchor may be kebab-case (as baked by work-breakdown) or the raw
    space-separated requirement name; both must resolve."""
    for anchor in ("persist-widget-state", "Persist widget state"):
        spec_id = f"{_SPEC_REL}#{anchor}"
        resolved, _reason = preflight.check_spec_id(spec_id, project_dir)
        assert resolved is True, f"anchor {anchor!r} should resolve"


# ---------------------------------------------------------------------------
# scan_spec_ids — the driver that classifies a set of beads and sets exit code
# ---------------------------------------------------------------------------

def test_scan_flags_only_the_orphan(project_dir: Path) -> None:
    """Given a mix of resolving and orphaned beads, the scan reports exactly
    the orphan(s) and nothing else."""
    pairs = [
        ("bead-good-1", f"{_SPEC_REL}#render-the-widget"),
        ("bead-good-2", f"{_SPEC_REL}#persist-widget-state"),
        ("bead-orphan", f"{_SPEC_REL}#render-the-gadget"),  # renamed away
    ]
    orphans = preflight.scan_spec_ids(pairs, project_dir)
    orphan_ids = {bead_id for bead_id, _spec_id, _reason in orphans}
    assert orphan_ids == {"bead-orphan"}


def test_scan_all_resolving_returns_empty(project_dir: Path) -> None:
    """POSITIVE CONTROL at the scan level: when every spec-id resolves, the
    scan reports no orphans (it does not flag healthy beads)."""
    pairs = [
        ("bead-good-1", f"{_SPEC_REL}#render-the-widget"),
        ("bead-good-2", f"{_SPEC_REL}#persist-widget-state"),
    ]
    orphans = preflight.scan_spec_ids(pairs, project_dir)
    assert orphans == []


def test_run_exit_code_zero_when_clean(project_dir: Path) -> None:
    """The preflight exits 0 when there are no orphans."""
    pairs = [("bead-good", f"{_SPEC_REL}#render-the-widget")]
    code = preflight.run(pairs, project_dir)
    assert code == 0


def test_run_exit_code_nonzero_when_orphan(project_dir: Path) -> None:
    """The preflight exits non-zero when at least one bead is orphaned — this
    is what makes it usable as a gate/CI oracle."""
    pairs = [
        ("bead-good", f"{_SPEC_REL}#render-the-widget"),
        ("bead-orphan", f"{_SPEC_REL}#render-the-gadget"),
    ]
    code = preflight.run(pairs, project_dir)
    assert code != 0


def test_beads_without_spec_id_are_ignored(project_dir: Path) -> None:
    """Beads with no spec-id (empty / None) are not orphans — there is nothing
    to resolve. Only beads that DID bake in a spec-id can be orphaned."""
    pairs = [
        ("bead-no-spec", None),
        ("bead-empty-spec", ""),
        ("bead-good", f"{_SPEC_REL}#render-the-widget"),
    ]
    orphans = preflight.scan_spec_ids(pairs, project_dir)
    assert orphans == []
