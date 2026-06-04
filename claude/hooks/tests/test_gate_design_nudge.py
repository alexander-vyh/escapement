"""Behavioral tests for claude/hooks/gate_design_nudge.py.

This hook is the mechanical half of the gate-design rule->skill conversion
(option D+B). The full gate-design manual moved to an on-demand skill; the
3-rule checklist stays resident as a stub; and THIS PreToolUse nudge catches
the file-edit trigger that a resident checklist might not — when you Write/Edit
a gate-ish file, it injects a reminder to load the `gate-design` skill before
building the gate.

It is a NUDGE, not a gate: it must NEVER block an edit. The contract:

  Positive control — Writing/Editing a gate-ish path (a hook .py, a *gate*
  file, or settings.template.json) emits a non-blocking systemMessage that
  points at the gate-design skill. If this never fired, the conversion would
  silently drop gate-design discipline on the file-edit path (the whole point
  of option B).

  Negative control — Writing/Editing an ORDINARY file (app code, a README, a
  non-gate rule) emits NOTHING. This is load-bearing: a nudge that fires on
  every edit is noise, and noise gets ignored — the failure mode this control
  rejects is "classify everything as gate work."

  Non-blocking invariant — no positive case may emit permissionDecision=deny.
  A reminder that accidentally blocked an edit would be far worse than the
  always-on rule it replaced.

  Fail-open — malformed stdin / wrong tool → exit 0, no output.

Assertions target externally-observable output (the JSON the runtime acts on),
not private helpers.

Run from anywhere:
  python3 -m pytest claude/hooks/tests/test_gate_design_nudge.py -v
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_hooks_dir = Path(__file__).resolve().parent.parent
if str(_hooks_dir) not in sys.path:
    sys.path.insert(0, str(_hooks_dir))

import gate_design_nudge as hook  # noqa: E402


def _run(tool_name: str, file_path: str) -> tuple[int, dict, str]:
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": tool_name,
        "tool_input": {"file_path": file_path},
    }
    stdout_capture = io.StringIO()
    exit_code = 0
    with (
        patch("sys.stdin", io.StringIO(json.dumps(payload))),
        patch("sys.stdout", stdout_capture),
    ):
        try:
            ret = hook.main()
            exit_code = ret if ret is not None else 0
        except SystemExit as exc:
            exit_code = exc.code if isinstance(exc.code, int) else 1
    out = stdout_capture.getvalue().strip()
    parsed = json.loads(out) if out else {}
    return exit_code, parsed, out


# ---------------------------------------------------------------------------
# Positive control: gate-ish edits nudge toward the skill.
# ---------------------------------------------------------------------------

_GATE_PATHS = [
    "/Users/x/GitHub/claude-workflow-setup/claude/hooks/foo_gate.py",
    "/Users/x/GitHub/claude-workflow-setup/claude/hooks/some_guard.py",
    "claude/hooks/discovery-gate.py",
    "/repo/claude/settings.template.json",
    "/repo/some/path/spec_id_enforcement_gate.py",
]


@pytest.mark.parametrize("path", _GATE_PATHS)
@pytest.mark.parametrize("tool", ["Write", "Edit"])
def test_gate_path_nudges_toward_skill(tool, path):
    exit_code, parsed, raw = _run(tool, path)
    assert exit_code == 0
    msg = parsed.get("systemMessage", "")
    assert "gate-design" in msg, (
        f"a gate-ish edit must point at the gate-design skill; got: {raw!r}"
    )
    # Non-blocking invariant: a nudge must never deny.
    assert "permissionDecision" not in raw, (
        f"the nudge must NEVER block an edit; stdout was: {raw!r}"
    )


# ---------------------------------------------------------------------------
# Negative control: ordinary edits stay silent (the anti-noise control).
# ---------------------------------------------------------------------------

_NON_GATE_PATHS = [
    "/repo/lib/ai.js",
    "/repo/README.md",
    "/repo/reticle-db.js",
    "/repo/claude/rules/never-suppress.md",      # a non-gate rule edit
    "/repo/claude/skills/build/SKILL.md",
    "/repo/src/components/Button.tsx",
]


@pytest.mark.parametrize("path", _NON_GATE_PATHS)
@pytest.mark.parametrize("tool", ["Write", "Edit"])
def test_ordinary_path_is_silent(tool, path):
    exit_code, parsed, raw = _run(tool, path)
    assert exit_code == 0
    assert parsed == {}, (
        f"ordinary edits must not nudge (noise gets ignored); got: {raw!r}"
    )


# ---------------------------------------------------------------------------
# Settings registration: the nudge is wired on BOTH Write and Edit.
# ---------------------------------------------------------------------------

def test_nudge_registered_on_write_and_edit():
    template = Path(__file__).resolve().parents[2] / "claude" / "settings.template.json"
    if not template.is_file():
        for parent in Path(__file__).resolve().parents:
            cand = parent / "settings.template.json"
            if cand.is_file():
                template = cand
                break
    assert template.is_file(), f"settings template not found at {template}"
    settings = json.loads(template.read_text(encoding="utf-8"))
    matchers = set()
    for entry in settings.get("hooks", {}).get("PreToolUse", []):
        cmds = [h.get("command", "") for h in entry.get("hooks", [])]
        if any("gate_design_nudge.py" in c for c in cmds):
            matchers.add(entry.get("matcher", ""))
    assert {"Write", "Edit"} <= matchers, (
        f"gate_design_nudge.py must be wired on both Write and Edit; found: {matchers}"
    )


# ---------------------------------------------------------------------------
# Fail-open + wrong-tool.
# ---------------------------------------------------------------------------

def test_wrong_tool_is_silent():
    exit_code, parsed, _ = _run("Bash", "claude/hooks/foo_gate.py")
    assert exit_code == 0
    assert parsed == {}


def test_malformed_stdin_fails_open():
    stdout_capture = io.StringIO()
    exit_code = 0
    with (
        patch("sys.stdin", io.StringIO("nope{{{")),
        patch("sys.stdout", stdout_capture),
    ):
        try:
            ret = hook.main()
            exit_code = ret if ret is not None else 0
        except SystemExit as exc:
            exit_code = exc.code if isinstance(exc.code, int) else 1
    assert exit_code == 0
    assert stdout_capture.getvalue().strip() == ""
