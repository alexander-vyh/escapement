"""Oracle for the settings.json hooks merge (e9v.8 deploy fix).

Business invariant
------------------
After deploy, every hook the template REGISTERS must be present in the live
settings.json so it actually fires — without clobbering the user's own settings
or their own hook entries, and without duplicating entries on re-run (idempotent).

Fragile implementations this rejects
------------------------------------
- Overwrite settings.json with the template (loses user customizations + own hooks).
- Append unconditionally (duplicates every entry on each install).
Both are caught by the preserve/dedupe/idempotency controls below.
"""

import importlib.util
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
spec = importlib.util.spec_from_file_location("merge_settings_hooks", SCRIPTS / "merge_settings_hooks.py")
msh = importlib.util.module_from_spec(spec)
sys.modules["merge_settings_hooks"] = msh
spec.loader.exec_module(msh)

merge = msh.merge_hooks  # merge_hooks(template: dict, settings: dict) -> dict


def _cmds(settings, event, matcher=None):
    out = []
    for grp in settings.get("hooks", {}).get(event, []):
        if matcher is not None and grp.get("matcher") != matcher:
            continue
        out += [h.get("command") for h in grp.get("hooks", [])]
    return out


TEMPLATE = {
    "hooks": {
        "PreToolUse": [
            {"matcher": "Bash", "hooks": [
                {"type": "command", "command": "python3 ~/.claude/hooks/validate_no_shirking.py"},
                {"type": "command", "command": "python3 ~/.claude/hooks/bypass_guard.py"},
            ]},
        ],
        "Stop": [
            {"hooks": [{"type": "command", "command": "python3 ~/.claude/harness/bin/stop_hook.py"}]},
        ],
    }
}


def test_missing_hook_is_added():
    live = {"hooks": {"PreToolUse": [
        {"matcher": "Bash", "hooks": [
            {"type": "command", "command": "python3 ~/.claude/hooks/validate_no_shirking.py"},
        ]},
    ]}}
    out = merge(TEMPLATE, live)
    assert "python3 ~/.claude/hooks/bypass_guard.py" in _cmds(out, "PreToolUse", "Bash")


def test_user_own_settings_preserved():
    live = {"model": "opus", "permissions": {"allow": ["Bash(ls)"]},
            "hooks": {"PreToolUse": [
                {"matcher": "Bash", "hooks": [
                    {"type": "command", "command": "python3 ~/.claude/hooks/validate_no_shirking.py"},
                    {"type": "command", "command": "python3 ~/.my/custom_hook.py"},
                ]},
            ]}}
    out = merge(TEMPLATE, live)
    assert out["model"] == "opus"
    assert out["permissions"]["allow"] == ["Bash(ls)"]
    # the user's own hook is NOT removed
    assert "python3 ~/.my/custom_hook.py" in _cmds(out, "PreToolUse", "Bash")
    # the template's missing one IS added
    assert "python3 ~/.claude/hooks/bypass_guard.py" in _cmds(out, "PreToolUse", "Bash")


def test_idempotent_no_duplicates():
    live = {"hooks": {}}
    once = merge(TEMPLATE, live)
    twice = merge(TEMPLATE, once)
    assert _cmds(twice, "PreToolUse", "Bash").count("python3 ~/.claude/hooks/bypass_guard.py") == 1
    assert _cmds(twice, "Stop").count("python3 ~/.claude/harness/bin/stop_hook.py") == 1


def test_new_event_created():
    live = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": []}]}}
    out = merge(TEMPLATE, live)
    assert "python3 ~/.claude/harness/bin/stop_hook.py" in _cmds(out, "Stop")


def test_empty_live_settings():
    out = merge(TEMPLATE, {})
    assert "python3 ~/.claude/hooks/bypass_guard.py" in _cmds(out, "PreToolUse", "Bash")
