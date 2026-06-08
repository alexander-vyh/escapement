"""Behavioral tests for openspec_task_reconciliation_gate.py.

Business invariant
------------------
When a bead claims traceability to an OpenSpec task via
``spec_id=openspec/changes/<change>/tasks.md#<anchor>``, closing the bead must
not silently leave that OpenSpec task unchecked. The Reticle `reticle-odwr`
incident showed the failure mode: all beads closed, but `openspec list` still
reported `0/N tasks` because `tasks.md` remained unchecked.

Independent oracle
------------------
The live bead record supplies the claimed `spec_id`; the on-disk `tasks.md`
checkbox state supplies completion truth for OpenSpec. A linked close is valid
only when the anchored task or task section is checked.

Controls
--------
- NEGATIVE: a linked section containing an unchecked task is denied.
- POSITIVE: the same linked section with all tasks checked is allowed.
- POSITIVE: non-`tasks.md` spec IDs are out of scope and do not block.

Fragile shortcut rejected: checking only that `spec_id` or `tasks.md` exists.
The negative control has both, and must still block because the checkbox is
unchecked.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

import pytest

_HOOKS_DIR = Path(__file__).resolve().parents[1]
_MODULE_PATH = _HOOKS_DIR / "openspec_task_reconciliation_gate.py"

_spec = importlib.util.spec_from_file_location("openspec_task_reconciliation_gate", _MODULE_PATH)
gate = importlib.util.module_from_spec(_spec)
sys.modules["openspec_task_reconciliation_gate"] = gate
_spec.loader.exec_module(gate)


TASKS_WITH_OPEN_SECTION = """\
## 1. Contract And Oracle

- [x] Inventory current evidence fields.
- [ ] Define the continuity record shape.

## 2. Replay

- [ ] Render proof output.
"""

TASKS_WITH_CLOSED_SECTION = """\
## 1. Contract And Oracle

- [x] Inventory current evidence fields.
- [x] Define the continuity record shape.

## 2. Replay

- [ ] Render proof output.
"""

TASKS_WITH_ITEM = """\
## 1. Contract And Oracle

- [x] Inventory current evidence fields.
- [ ] Define the continuity record shape.
"""


def _project(tmp_path: Path, tasks: str) -> Path:
    change = tmp_path / "openspec" / "changes" / "demo"
    change.mkdir(parents=True)
    (change / "tasks.md").write_text(tasks, encoding="utf-8")
    spec = change / "specs" / "demo.md"
    spec.parent.mkdir(parents=True)
    spec.write_text("### Requirement: Demo\n", encoding="utf-8")
    return tmp_path


def _issue(spec_id: str | None) -> dict:
    return {
        "id": "demo-1",
        "status": "in_progress",
        "title": "Demo task",
        "spec_id": spec_id,
    }


def _run_main(monkeypatch: pytest.MonkeyPatch, command: str, cwd: Path, issue: dict):
    monkeypatch.setattr(gate, "get_issue", lambda _issue_id: issue)

    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(cwd),
    }
    captured = io.StringIO()
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    monkeypatch.setattr(sys, "stdout", captured)

    code = None
    try:
        code = gate.main()
    except SystemExit as exc:
        code = exc.code

    text = captured.getvalue().strip()
    return code, json.loads(text) if text else None


def test_linked_unchecked_openspec_section_blocks_close(tmp_path, monkeypatch):
    root = _project(tmp_path, TASKS_WITH_OPEN_SECTION)
    issue = _issue("openspec/changes/demo/tasks.md#1-contract-and-oracle")

    decision, message = gate.evaluate("bd close demo-1", root, lambda _id: issue)

    assert decision == "deny"
    assert "1-contract-and-oracle" in message
    assert "unchecked" in message.lower()


def test_linked_checked_openspec_section_allows_close(tmp_path, monkeypatch):
    root = _project(tmp_path, TASKS_WITH_CLOSED_SECTION)
    issue = _issue("openspec/changes/demo/tasks.md#1-contract-and-oracle")

    decision, _message = gate.evaluate("bd close demo-1", root, lambda _id: issue)

    assert decision == "allow"


def test_linked_unchecked_openspec_item_blocks_close(tmp_path, monkeypatch):
    root = _project(tmp_path, TASKS_WITH_ITEM)
    issue = _issue("openspec/changes/demo/tasks.md#define-the-continuity-record-shape")

    decision, message = gate.evaluate("bd close demo-1", root, lambda _id: issue)

    assert decision == "deny"
    assert "Define the continuity record shape" in message


def test_non_tasks_spec_id_is_out_of_scope(tmp_path, monkeypatch):
    root = _project(tmp_path, TASKS_WITH_OPEN_SECTION)
    issue = _issue("openspec/changes/demo/specs/demo.md#demo")

    decision, _message = gate.evaluate("bd close demo-1", root, lambda _id: issue)

    assert decision == "allow"


def test_registered_hook_denies_unchecked_linked_task(tmp_path, monkeypatch):
    root = _project(tmp_path, TASKS_WITH_OPEN_SECTION)
    issue = _issue("openspec/changes/demo/tasks.md#1-contract-and-oracle")

    code, payload = _run_main(monkeypatch, "bd close demo-1", root, issue)

    assert code == 0
    assert payload["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "tasks.md" in payload["hookSpecificOutput"]["permissionDecisionReason"]
