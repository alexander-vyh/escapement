"""Behavioral tests for epic_coverage_gate.py (bead claude-workflow-setup-g0u).

The gate fires as PreToolUse on `bd close <epic>` and blocks the close if the
epic (a) carries no own acceptance oracle, or (b) names seams in its
scope-coverage manifest that map to no closed child. This is the runtime form
of the cake-ta5.1 lesson: parent completion != all children closed.

Oracle design (TDD, gate-design.md Rules 1-3):

  - POSITIVE control: a fully-covered epic with its own acceptance oracle and
    every named seam mapped to a closed child must be ALLOWED. Proves the gate
    does not block legitimate closes (a gate that blocks everything is useless).

  - NEGATIVE control (the bug this gate exists to catch): the literal cake-ta5.1
    shape — an epic that names a seam (`create_parser`) whose only covering
    child is still OPEN while all the other children are closed — must be
    BLOCKED. This is the false-close the gate must refuse.

  - NEGATIVE control: an epic with NO own acceptance oracle (only child-count as
    its proxy) must be BLOCKED even when every seam is covered. Closing on child
    count alone is exactly the failure mode.

  - ESCAPE control (Rule 1): a reasoned --epic-coverage-waiver bypasses the
    finding; a placeholder / too-short / id-echo waiver does NOT (Rule 3).

  - These are NOT implementation-echo tests: they assert the externally visible
    decision (allow vs deny) given bd issue data, mocking only the bd data
    boundary (get_issue / get_children). They do not assert on private regexes
    or internal call counts.

The bd data layer (subprocess to `bd show` / `bd children`) is the I/O boundary;
it is patched so the test is hermetic and does not depend on a live beads DB.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# Import the production module by path so the test runs regardless of cwd.
# No skip guard: if the module is absent the import MUST fail loudly so the
# done-oracle goes red rather than silently passing (a suppressed failure).
_HOOKS_DIR = Path(__file__).resolve().parents[1]
_MODULE_PATH = _HOOKS_DIR / "epic_coverage_gate.py"

_spec = importlib.util.spec_from_file_location("epic_coverage_gate", _MODULE_PATH)
gate = importlib.util.module_from_spec(_spec)
sys.modules["epic_coverage_gate"] = gate
_spec.loader.exec_module(gate)


# ---------------------------------------------------------------------------
# Fixtures: epic descriptions and child sets
# ---------------------------------------------------------------------------

# A well-formed epic: own acceptance oracle (Done-when + not-when-children) AND
# a structured seam manifest naming three seams.
EPIC_DESC_FULL = """\
Extract the monolith into seams.

Seams:
- parser: extract create_parser / argparse setup
- dispatch: extract the command dispatch table
- handlers: extract per-command handler functions

Done when: the refactored CLI passes its golden-output test for every
subcommand, not when all children are closed.
"""

# The cake-ta5.1 shape: same manifest, oracle present, but the 'parser' seam's
# covering child is still OPEN (the 1,867-LOC create_parser never got extracted)
# while the rest are closed.
EPIC_DESC_LEAKY = EPIC_DESC_FULL

# An epic with full seam coverage but NO own acceptance oracle — only an
# implicit child-count proxy. Must be blocked on finding (a).
EPIC_DESC_NO_ORACLE = """\
Extract the monolith into seams.

Seams:
- parser: extract create_parser / argparse setup
- dispatch: extract the command dispatch table

This epic is done once the child tasks below are complete.
"""

# An epic with an oracle and no seam manifest at all — coverage check (b) has
# nothing to enforce, so the only gate is (a), which passes.
EPIC_DESC_ORACLE_NO_SEAMS = """\
Tidy up the build scripts.

verify: make lint && make test
"""


def _epic(issue_id: str, description: str, issue_type: str = "epic") -> dict:
    return {
        "id": issue_id,
        "title": f"{issue_id} epic",
        "issue_type": issue_type,
        "description": description,
        "status": "open",
    }


def _child(title: str, status: str = "closed", seam: str | None = None) -> dict:
    c = {"title": title, "status": status}
    if seam is not None:
        c["metadata"] = {"seam": seam}
    return c


def _install_bd(monkeypatch, issue: dict, children: list[dict]) -> None:
    """Patch the bd data boundary so evaluate() runs hermetically."""
    monkeypatch.setattr(gate, "get_issue", lambda _id: issue)
    monkeypatch.setattr(gate, "get_children", lambda _id: list(children))


# ===========================================================================
# POSITIVE CONTROL — a fully-covered epic with its own oracle is ALLOWED
# ===========================================================================

def test_fully_covered_epic_with_oracle_is_allowed(monkeypatch):
    issue = _epic("proj-1", EPIC_DESC_FULL)
    children = [
        _child("Extract parser create_parser argparse"),
        _child("Extract dispatch command table"),
        _child("Extract handlers per-command functions"),
    ]
    _install_bd(monkeypatch, issue, children)

    decision, _msg = gate.evaluate("bd close proj-1")
    assert decision == "allow", (
        "a fully-covered epic with its own acceptance oracle must close freely; "
        f"got {decision!r}"
    )


def test_seam_covered_via_metadata_tag_is_allowed(monkeypatch):
    # Coverage may be asserted via a child's seam: metadata, not just its title.
    issue = _epic("proj-9", EPIC_DESC_FULL)
    children = [
        _child("Refactor argument handling", seam="parser"),
        _child("Refactor command routing", seam="dispatch"),
        _child("Refactor command bodies", seam="handlers"),
    ]
    _install_bd(monkeypatch, issue, children)

    decision, _msg = gate.evaluate("bd close proj-9")
    assert decision == "allow"


# ===========================================================================
# NEGATIVE CONTROL — the cake-ta5.1 false-close is BLOCKED
# ===========================================================================

def test_uncovered_seam_blocks_close(monkeypatch):
    # 'parser' seam's covering child is still OPEN; the rest are closed.
    issue = _epic("proj-2", EPIC_DESC_LEAKY)
    children = [
        _child("Extract parser create_parser argparse", status="open"),
        _child("Extract dispatch command table", status="closed"),
        _child("Extract handlers per-command functions", status="closed"),
    ]
    _install_bd(monkeypatch, issue, children)

    decision, msg = gate.evaluate("bd close proj-2")
    assert decision.startswith("deny"), (
        "an epic whose named seam maps to no CLOSED child must be blocked "
        f"(cake-ta5.1 false-close); got {decision!r}"
    )
    assert "parser" in msg.lower(), "denial must name the uncovered seam"


def test_epic_without_own_oracle_blocks_close(monkeypatch):
    # Every seam covered, but the epic has only a child-count proxy, no oracle.
    issue = _epic("proj-3", EPIC_DESC_NO_ORACLE)
    children = [
        _child("Extract parser create_parser argparse"),
        _child("Extract dispatch command table"),
    ]
    _install_bd(monkeypatch, issue, children)

    decision, msg = gate.evaluate("bd close proj-3")
    assert decision.startswith("deny"), (
        "closing an epic on child-count alone (no own acceptance oracle) must "
        f"be blocked; got {decision!r}"
    )
    assert "oracle" in msg.lower()


# ===========================================================================
# ESCAPE CONTROL (Rule 1) — a reasoned waiver bypasses; bad reasons do not
# ===========================================================================

def test_reasoned_waiver_allows_close(monkeypatch):
    issue = _epic("proj-4", EPIC_DESC_LEAKY)
    children = [
        _child("Extract parser create_parser argparse", status="open"),
        _child("Extract dispatch command table", status="closed"),
        _child("Extract handlers per-command functions", status="closed"),
    ]
    _install_bd(monkeypatch, issue, children)

    cmd = (
        "bd close proj-4 --epic-coverage-waiver "
        "'parser seam intentionally deferred to follow-up epic proj-99; the "
        "delivered scope passes its own golden-output oracle'"
    )
    decision, _msg = gate.evaluate(cmd)
    assert decision == "waiver-accepted", (
        f"a substantive waiver must bypass the coverage finding; got {decision!r}"
    )


def test_placeholder_waiver_is_rejected(monkeypatch):
    issue = _epic("proj-5", EPIC_DESC_LEAKY)
    children = [_child("Extract parser create_parser argparse", status="open")]
    _install_bd(monkeypatch, issue, children)

    decision, msg = gate.evaluate("bd close proj-5 --epic-coverage-waiver 'tbd'")
    assert decision.startswith("deny"), (
        "a placeholder waiver reason must NOT bypass the gate (Rule 3); "
        f"got {decision!r}"
    )
    assert "placeholder" in msg.lower()


def test_too_short_waiver_is_rejected(monkeypatch):
    issue = _epic("proj-6", EPIC_DESC_LEAKY)
    children = [_child("Extract parser create_parser argparse", status="open")]
    _install_bd(monkeypatch, issue, children)

    decision, msg = gate.evaluate("bd close proj-6 --epic-coverage-waiver 'too short'")
    assert decision.startswith("deny")
    assert "short" in msg.lower()


def test_waiver_echoing_epic_id_is_rejected(monkeypatch):
    issue = _epic("proj-7", EPIC_DESC_LEAKY)
    children = [_child("Extract parser create_parser argparse", status="open")]
    _install_bd(monkeypatch, issue, children)

    decision, _msg = gate.evaluate("bd close proj-7 --epic-coverage-waiver 'proj-7'")
    assert decision.startswith("deny"), (
        "a waiver that merely echoes the epic id carries no signal (Rule 3)"
    )


# ===========================================================================
# SCOPE / FAIL-OPEN controls
# ===========================================================================

def test_non_epic_close_is_allowed(monkeypatch):
    # The gate only fires on epics; a regular task close passes untouched.
    issue = _epic("proj-8", EPIC_DESC_NO_ORACLE, issue_type="task")
    _install_bd(monkeypatch, issue, [])

    decision, _msg = gate.evaluate("bd close proj-8")
    assert decision == "allow"


def test_oracle_without_seam_manifest_is_allowed(monkeypatch):
    # An oracle-bearing epic with no seam manifest has nothing for check (b);
    # check (a) passes, so the close is allowed.
    issue = _epic("proj-10", EPIC_DESC_ORACLE_NO_SEAMS)
    _install_bd(monkeypatch, issue, [])

    decision, _msg = gate.evaluate("bd close proj-10")
    assert decision == "allow"


def test_unfetchable_issue_fails_open(monkeypatch):
    monkeypatch.setattr(gate, "get_issue", lambda _id: None)
    monkeypatch.setattr(gate, "get_children", lambda _id: None)

    decision, _msg = gate.evaluate("bd close proj-missing")
    assert decision == "allow", "gate must fail-open when bd data is unavailable"


def test_non_close_command_is_allowed(monkeypatch):
    # extract_close_target returns None for a non-close command.
    decision, _msg = gate.evaluate("bd update proj-1 --claim")
    assert decision == "allow"


# ===========================================================================
# Seam-key word-boundary control — 'parse' must not match 'reparser'
# ===========================================================================

def test_seam_match_is_word_boundary_not_substring(monkeypatch):
    desc = "Seams:\n- parse: parse the input\n\nverify: make test\n"
    issue = _epic("proj-11", desc)
    # The only child mentions 'reparser', which contains 'parse' as a substring
    # but is NOT the 'parse' seam. Substring matching would wrongly mark it
    # covered; word-boundary matching correctly leaves 'parse' uncovered.
    children = [_child("Build the reparser module")]
    _install_bd(monkeypatch, issue, children)

    decision, msg = gate.evaluate("bd close proj-11")
    assert decision.startswith("deny"), (
        "seam 'parse' must not be considered covered by a child titled "
        f"'reparser' (substring false-positive); got {decision!r}"
    )
    assert "parse" in msg.lower()


# ===========================================================================
# Signal persistence (Rule 2) — main() records the decision
# ===========================================================================

def test_deny_records_signal(monkeypatch):
    issue = _epic("proj-12", EPIC_DESC_NO_ORACLE)
    children = [
        _child("Extract parser create_parser argparse"),
        _child("Extract dispatch command table"),
    ]
    _install_bd(monkeypatch, issue, children)

    recorded = {}

    def _fake_record(**kwargs):
        recorded.update(kwargs)

    monkeypatch.setattr(gate, "_record_signal", _fake_record)

    import io
    import json as _json

    stdin_payload = _json.dumps({
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "bd close proj-12"},
    })
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_payload))

    captured: dict = {}

    def _fake_print(payload, *_a, **_k):
        captured["stdout"] = payload

    monkeypatch.setattr("builtins.print", _fake_print)

    with pytest.raises(SystemExit) as exc:
        gate.main()

    # Single-signal contract (fxh.7): a structured deny is emitted as
    # permissionDecision="deny" JSON on stdout with exit 0 — NOT exit 2.
    # exit 2 alongside a deny-JSON is the contradictory double-block fxh.7
    # removed from every other hook; this gate must match that contract.
    assert exc.value.code == 0, (
        "a structured deny must exit 0 (single-signal); the deny lives in the "
        f"permissionDecision JSON, not the exit code; got code {exc.value.code!r}"
    )
    payload = _json.loads(captured["stdout"])
    decision_out = payload["hookSpecificOutput"]["permissionDecision"]
    assert decision_out == "deny", (
        "the block must be carried by permissionDecision='deny' on stdout; "
        f"got {decision_out!r}"
    )
    assert recorded.get("gate_name") == gate.GATE_NAME
    assert recorded.get("decision") == "deny"


# ===========================================================================
# INTEGRATION — gate behaves end-to-end when invoked AS REGISTERED
#
# The unit tests above exercise evaluate(); these drive main() with a real
# PreToolUse stdin payload, which is exactly how the hook registration
# (settings.template.json's Bash(bd close:*) matcher) invokes the gate. This is
# the behavioral oracle proving the wired gate denies an uncovered-seam epic and
# allows a fully-covered one — the gap the evaluate()-only tests did not close.
# ===========================================================================

def _run_main_via_stdin(monkeypatch, command: str):
    """Drive gate.main() with a PreToolUse payload; return (exit_code, stdout).

    stdout is the parsed JSON dict the gate printed, or None if it printed
    nothing (the allow path is silent).
    """
    import io
    import json as _json

    captured: dict = {}

    def _fake_print(payload, *_a, **_k):
        captured["stdout"] = payload

    monkeypatch.setattr("builtins.print", _fake_print)

    stdin_payload = _json.dumps({
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
    })
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_payload))

    code = None
    try:
        code = gate.main()
    except SystemExit as exc:  # deny() raises SystemExit
        code = exc.code

    out = captured.get("stdout")
    parsed = _json.loads(out) if out is not None else None
    return code, parsed


def test_integration_uncovered_seam_epic_is_denied(monkeypatch):
    # cake-ta5.1 shape via the registered entry point: the 'parser' seam's only
    # covering child is still OPEN. The gate must DENY with exit 0 + deny-JSON.
    issue = _epic("proj-int-1", EPIC_DESC_LEAKY)
    children = [
        _child("Extract parser create_parser argparse", status="open"),
        _child("Extract dispatch command table", status="closed"),
        _child("Extract handlers per-command functions", status="closed"),
    ]
    _install_bd(monkeypatch, issue, children)

    code, payload = _run_main_via_stdin(monkeypatch, "bd close proj-int-1")

    assert code == 0, f"single-signal deny exits 0; got {code!r}"
    assert payload is not None, "a deny must print permissionDecision JSON"
    out = payload["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"
    assert "parser" in out["permissionDecisionReason"].lower(), (
        "the denial must name the uncovered seam"
    )


def test_integration_fully_covered_epic_is_allowed(monkeypatch):
    # Fully-covered epic with its own oracle: the registered gate must ALLOW
    # (exit 0, silent — no permissionDecision JSON).
    issue = _epic("proj-int-2", EPIC_DESC_FULL)
    children = [
        _child("Extract parser create_parser argparse"),
        _child("Extract dispatch command table"),
        _child("Extract handlers per-command functions"),
    ]
    _install_bd(monkeypatch, issue, children)

    code, payload = _run_main_via_stdin(monkeypatch, "bd close proj-int-2")

    assert code == 0, f"allow exits 0; got {code!r}"
    assert payload is None, (
        "a fully-covered epic close must pass silently (no deny JSON); "
        f"got {payload!r}"
    )


def test_integration_oracle_no_seams_epic_is_allowed(monkeypatch):
    # An epic carrying its own acceptance oracle and naming no seams has nothing
    # for check (b); check (a) passes — the registered gate must ALLOW silently.
    issue = _epic("proj-int-3", EPIC_DESC_ORACLE_NO_SEAMS)
    _install_bd(monkeypatch, issue, [])

    code, payload = _run_main_via_stdin(monkeypatch, "bd close proj-int-3")

    assert code == 0
    assert payload is None, "an oracle-bearing, seam-free epic must close silently"
