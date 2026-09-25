#!/usr/bin/env python3
"""Oracle for the Codex plugin hook-trust reporter.

The failure this guards against is a silent one: Codex skips an untrusted
plugin hook without a word, so a gate can install green and never fire. The
reporter must name exactly the events Codex will skip -- a reporter that names
everything is as useless as one that names nothing, so both directions are
asserted.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "codex_hook_trust.py"
PLUGIN_ID = "escapement@escapement"

# Real handler definitions with the trusted_hash Codex 0.156.1 recorded for
# each after the user accepted it in /hooks (captured from ~/.codex/config.toml).
# Codex omits the matcher from Stop/UserPromptSubmit hashes and defaults the
# timeout to 600, which is why these differ in shape.
_SESSION_CONTEXT = 'python3 -B "${PLUGIN_ROOT}/claude/hooks/escapement_session_context.py"'
HOOKS = {
    "hooks": {
        "SessionStart": [{"matcher": "", "hooks": [{"type": "command", "command": _SESSION_CONTEXT}]}],
        "Stop": [{"matcher": "", "hooks": [{
            "type": "command", "timeout": 30,
            "command": 'python3 -B "${PLUGIN_ROOT}/harness/bin/codex_stop_hook.py"',
        }]}],
        "UserPromptSubmit": [{"matcher": "", "hooks": [{
            "type": "command", "timeout": 10,
            "command": 'python3 -B "${PLUGIN_ROOT}/harness/bin/codex_prompt_recorder.py"',
        }]}],
    }
}
CODEX_RECORDED = {
    "session_start": "sha256:7298f319bc8c26aa7e96ac275bc2286ab6196bdada49a970af80864357d2ecc8",
    "stop": "sha256:6bf5a247c9cc19b40414d3825f6a8b8871a6972c877be54566583e8be94ace5a",
    "user_prompt_submit": "sha256:6ba4148bf7208e520c66c84ccf70879524279469b0347b483a744e70cd3c1e50",
}


def _write(tmp_path: Path, trusted_events: list[str], hooks: dict = HOOKS) -> tuple[Path, Path]:
    hooks_json = tmp_path / "hooks.json"
    hooks_json.write_text(json.dumps(hooks), encoding="utf-8")
    lines = ["[hooks.state]", ""]
    for event in trusted_events:
        key = f"{PLUGIN_ID}:hooks/hooks.json:{event}:0:0"
        lines += [f'[hooks.state."{key}"]', f'trusted_hash = "{CODEX_RECORDED[event]}"', ""]
    config = tmp_path / "config.toml"
    config.write_text("\n".join(lines), encoding="utf-8")
    return hooks_json, config


def _run(hooks_json: Path, config: Path) -> str:
    result = subprocess.run(
        [sys.executable, "-B", str(SCRIPT), "--plugin-id", PLUGIN_ID,
         "--hooks-json", str(hooks_json), "--config-toml", str(config)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_untrusted_events_are_named(tmp_path):
    hooks_json, config = _write(tmp_path, ["session_start"])
    out = _run(hooks_json, config)
    assert "NOT YET LIVE" in out
    assert "Stop" in out and "UserPromptSubmit" in out


def test_trusted_events_are_not_named(tmp_path):
    """Positive control: a reporter that names everything would fail here."""
    hooks_json, config = _write(tmp_path, ["session_start"])
    out = _run(hooks_json, config)
    # SessionStart is trusted; naming it would send the user chasing a
    # non-problem and would hide the two that are real.
    assert "SessionStart" not in out


def test_fully_trusted_plugin_reports_ok(tmp_path):
    hooks_json, config = _write(tmp_path, ["session_start", "stop", "user_prompt_submit"])
    out = _run(hooks_json, config)
    assert "OK" in out
    assert "NOT YET LIVE" not in out


def test_entry_without_a_hash_is_not_trust(tmp_path):
    """A present-but-empty record is Codex's 'seen, not trusted' state."""
    hooks_json, config = _write(tmp_path, ["session_start"])
    config.write_text(
        config.read_text(encoding="utf-8")
        + f'\n[hooks.state."{PLUGIN_ID}:hooks/hooks.json:stop:0:0"]\nenabled = true\n',
        encoding="utf-8",
    )
    out = _run(hooks_json, config)
    assert "Stop" in out


def test_missing_config_reports_every_event(tmp_path):
    """A machine that has never trusted anything must not read as fully trusted."""
    hooks_json, _ = _write(tmp_path, [])
    out = _run(hooks_json, tmp_path / "absent.toml")
    for event in ("SessionStart", "Stop", "UserPromptSubmit"):
        assert event in out


def test_hook_displaced_by_an_inserted_group_is_untrusted(tmp_path):
    """The trust record stays under ``session_start:0:0`` but now holds another
    hook's hash: Codex skips it, so the reporter must name the event. This is
    what a release that put a new SessionStart hook first did to a real install."""
    inserted = {"matcher": "", "hooks": [{"type": "command", "command": "python3 -B new.py"}]}
    hooks = json.loads(json.dumps(HOOKS))
    hooks["hooks"]["SessionStart"].insert(0, inserted)
    hooks_json, config = _write(tmp_path, ["session_start", "stop", "user_prompt_submit"], hooks)
    out = _run(hooks_json, config)
    assert "SessionStart" in out
    assert "Stop" not in out and "UserPromptSubmit" not in out


def test_event_names_use_codex_snake_case_keys():
    """The key shape is the whole contract; a wrong case silently reports all."""
    sys.path.insert(0, str(ROOT / "scripts"))
    from codex_hook_trust import event_key

    assert event_key("SessionStart") == "session_start"
    assert event_key("UserPromptSubmit") == "user_prompt_submit"
    assert event_key("PreToolUse") == "pre_tool_use"
    assert event_key("Stop") == "stop"
