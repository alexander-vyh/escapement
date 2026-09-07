"""Codex SessionStart warning for the continuation gaps that remain.

The Stop gate now exists (harness/bin/codex_stop_hook.py), so this advisory
no longer denies it. What it must still name: no scheduled wakeup, no
task-mode repository binding, no local judge rung.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "codex_final_response_gap.py"


def _run(payload: dict | None = None) -> tuple[int, dict | None, str]:
    assert HOOK.exists(), f"missing hook: {HOOK}"
    raw = "" if payload is None else json.dumps(payload)
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=raw,
        capture_output=True,
        text=True,
        check=False,
    )
    stdout = result.stdout.strip()
    parsed = json.loads(stdout) if stdout else None
    return result.returncode, parsed, result.stderr


def test_codex_session_start_names_the_remaining_continuation_gaps():
    """Positive control: SessionStart emits user-visible context.

    This fails a manifest-only or no-op-hook implementation because the public
    hook command itself must produce the warning.
    """
    code, output, stderr = _run({"hook_event_name": "SessionStart"})

    assert code == 0, stderr
    assert output is not None
    message = output.get("systemMessage", "")
    context = output.get("hookSpecificOutput", {}).get("additionalContext", "")
    combined = f"{message}\n{context}"

    assert output["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "Codex" in combined
    assert "Stop" in combined
    # The advisory must not re-assert the retired premise. A Codex session told
    # no Stop hook exists will wind down straight through the gate that does.
    assert "no Stop" not in combined
    assert "wakeup" in combined.lower()
    assert "task-mode" in combined.lower()
    assert "judge" in combined.lower()
    assert "continue" in combined.lower()
    assert "outcome" in combined.lower()


def test_codex_gap_hook_treats_empty_payload_as_startup():
    """Missing stdin should still emit because the generated hook is SessionStart-only."""
    code, output, stderr = _run(None)

    assert code == 0, stderr
    assert output is not None
    assert "wakeup" in output["systemMessage"].lower()


def test_codex_gap_hook_silent_for_non_session_start():
    """Negative control: the advisory cannot become a noisy all-event hook."""
    code, output, stderr = _run({"hook_event_name": "PreToolUse"})

    assert code == 0, stderr
    assert output is None
