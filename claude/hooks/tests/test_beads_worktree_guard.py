"""Behavioral tests for claude/hooks/beads_worktree_guard.py.

This hook protects one business outcome: in a beads-managed project, a worktree
is never created with bare ``git worktree add`` — which produces a broken
worktree (empty ``.beads/`` with no Dolt database, ``bd`` commands failing).
The agent is mechanically redirected to ``bd worktree create``, which wires up
the ``.beads/redirect`` so the worktree shares the main repo's database.

Unlike no_direct_send_guard (which ALWAYS denies, because its tools are
inherently blocked), this guard is CONDITIONAL: it must deny ``git worktree
add`` only when the command runs inside a beads project, and let it pass
through everywhere else. That conditionality is where a fragile implementation
hides, so the controls are built around it:

  Negative control — ``git worktree add`` with a ``.beads/`` directory present
  is DENIED via the canonical single-mechanism contract (permissionDecision=
  "deny" JSON on stdout, exit 0 — NOT exit 2), and the denial names the
  concrete ``bd worktree create`` command to use instead (gate-design Rule 1:
  the escape path lives in the denial). If the hook allowed this through, the
  broken-worktree state the guard exists to prevent would recur.

  Positive control — the SAME command with NO ``.beads/`` present must be
  ALLOWED (exit 0, no decision). This is the load-bearing control: it fails the
  tempting-but-wrong "always deny git worktree add" implementation, which would
  break worktree creation in every non-beads repo on the machine.

  Walk-up control — ``.beads/`` in a PARENT directory while the command runs
  from a subdirectory must still DENY. Worktree commands are not always run
  from the repo root; an exact-cwd-only beads check would pass the simple
  negative control yet silently fail real usage.

  Settings registration — the guard is wired in settings.template.json on the
  ``Bash(git worktree add:*)`` matcher (scoped so it fires only on that command
  prefix — zero overhead on every other Bash call). Asserted against the real
  template, not the hook's internals, so a de-registration regression bites.

Assertions target externally-observable behavior (exit code, the JSON decision
the runtime acts on, the settings registration) — not private helpers — so
they are not implementation echoes.

Run from anywhere:
  python3 -m pytest claude/hooks/tests/test_beads_worktree_guard.py -v
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

import beads_worktree_guard as hook  # noqa: E402


_SETTINGS_TEMPLATE = (
    Path(__file__).resolve().parents[2] / "claude" / "settings.template.json"
)
if not _SETTINGS_TEMPLATE.is_file():
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "settings.template.json"
        if candidate.is_file():
            _SETTINGS_TEMPLATE = candidate
            break

_EXPECTED_MATCHER = "Bash(git worktree add:*)"


def _run(command: str, cwd: Path) -> tuple[int, dict, str]:
    """Drive the hook's main() with a Bash PreToolUse payload.

    Returns (exit_code, parsed_stdout_json, raw_stdout). A deny is signaled by
    a permissionDecision="deny" JSON document on stdout plus exit 0 (NOT exit
    2). An allow is exit 0 with empty stdout.
    """
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(cwd),
    }
    stdout_capture = io.StringIO()
    exit_code = 0
    with (
        patch("sys.stdin", io.StringIO(json.dumps(payload))),
        patch("sys.stdout", stdout_capture),
        patch.object(hook, "_record_signal", lambda *a, **k: None),
    ):
        try:
            ret = hook.main()
            exit_code = ret if ret is not None else 0
        except SystemExit as exc:
            exit_code = exc.code if isinstance(exc.code, int) else 1

    out = stdout_capture.getvalue().strip()
    parsed = json.loads(out) if out else {}
    return exit_code, parsed, out


def _make_beads_project(tmp_path: Path) -> Path:
    (tmp_path / ".beads").mkdir()
    return tmp_path


# ---------------------------------------------------------------------------
# Negative control: git worktree add in a beads project is denied + redirected.
# ---------------------------------------------------------------------------

def test_worktree_add_in_beads_project_is_denied_and_redirected(tmp_path):
    proj = _make_beads_project(tmp_path)
    exit_code, parsed, raw = _run("git worktree add ../wt -b feature/x", proj)

    # Canonical deny mechanism: the JSON decision carries the block; exit 0.
    assert exit_code == 0, (
        "deny is signaled by the stdout JSON decision, not exit 2"
    )
    assert raw.count('"permissionDecision"') == 1, (
        f"deny must be emitted exactly once; stdout was: {raw!r}"
    )
    out = parsed["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"

    reason = out["permissionDecisionReason"]
    # The escape path must be IN the denial (gate-design Rule 1): the concrete
    # correct command, not just prose telling the agent it did something wrong.
    assert "bd worktree create" in reason, (
        f"denial must redirect to `bd worktree create`; got: {reason!r}"
    )


def test_denial_injects_the_concrete_path_and_branch(tmp_path):
    """The redirect should be actionable: it carries the SAME path and branch
    the agent tried, so the agent can run the corrected command verbatim
    (serena_preference_gate-style param injection)."""
    proj = _make_beads_project(tmp_path)
    _, parsed, _ = _run("git worktree add ../my-wt -b reticle-xyz", proj)
    reason = parsed["hookSpecificOutput"]["permissionDecisionReason"]
    assert "../my-wt" in reason and "reticle-xyz" in reason, (
        f"denial should echo the attempted path/branch; got: {reason!r}"
    )


# ---------------------------------------------------------------------------
# Positive control: git worktree add with NO .beads/ passes through.
# ---------------------------------------------------------------------------

def test_worktree_add_in_non_beads_project_is_allowed(tmp_path):
    """The load-bearing control. A plain git repo (no .beads/) must NOT be
    blocked — otherwise the guard breaks worktree creation everywhere. Fails
    the fragile 'always deny git worktree add' implementation."""
    # tmp_path has no .beads/ directory.
    exit_code, parsed, raw = _run("git worktree add ../wt -b foo", tmp_path)
    assert exit_code == 0
    assert parsed == {}, f"non-beads worktree add must pass untouched; got: {raw!r}"


# ---------------------------------------------------------------------------
# Walk-up control: .beads/ in a parent, command run from a subdirectory.
# ---------------------------------------------------------------------------

def test_beads_detected_from_subdirectory(tmp_path):
    proj = _make_beads_project(tmp_path)
    subdir = proj / "recorder" / "src"
    subdir.mkdir(parents=True)
    exit_code, parsed, _ = _run("git worktree add ../wt -b foo", subdir)
    assert exit_code == 0
    assert parsed.get("hookSpecificOutput", {}).get("permissionDecision") == "deny", (
        "a beads project must be detected from a nested subdirectory, not only "
        "from the exact cwd"
    )


# ---------------------------------------------------------------------------
# Settings registration: the guard is wired on the scoped matcher.
# ---------------------------------------------------------------------------

def test_guard_is_registered_on_scoped_worktree_matcher():
    assert _SETTINGS_TEMPLATE.is_file(), (
        f"settings template not found at {_SETTINGS_TEMPLATE}"
    )
    settings = json.loads(_SETTINGS_TEMPLATE.read_text(encoding="utf-8"))
    matchers = set()
    for entry in settings.get("hooks", {}).get("PreToolUse", []):
        commands = [h.get("command", "") for h in entry.get("hooks", [])]
        if any("beads_worktree_guard.py" in c for c in commands):
            matchers.add(entry.get("matcher", ""))
    assert _EXPECTED_MATCHER in matchers, (
        f"beads_worktree_guard.py must be registered on matcher "
        f"{_EXPECTED_MATCHER!r}; found registrations on: {matchers}"
    )


# ---------------------------------------------------------------------------
# Defensive: malformed stdin fails OPEN (never wedge the tool pipeline).
# ---------------------------------------------------------------------------

def test_malformed_stdin_fails_open():
    stdout_capture = io.StringIO()
    exit_code = 0
    with (
        patch("sys.stdin", io.StringIO("not json{{{")),
        patch("sys.stdout", stdout_capture),
        patch.object(hook, "_record_signal", lambda *a, **k: None),
    ):
        try:
            ret = hook.main()
            exit_code = ret if ret is not None else 0
        except SystemExit as exc:
            exit_code = exc.code if isinstance(exc.code, int) else 1
    assert exit_code == 0
    assert stdout_capture.getvalue().strip() == ""
