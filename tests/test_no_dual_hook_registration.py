"""Regression: escapement must register each gate exactly once (escapement-ptzz).

Two installers both registered escapement's hooks:
  * ``INSTALL.sh`` merged ``claude/settings.template.json`` into ``~/.claude/settings.json``
  * the Claude plugin ships ``plugins/escapement-claude/hooks/hooks.json``

Claude Code does not dedupe them, so 38 gates fired **twice** per matching tool
call. Observed 2026-07-09: a single Stop event produced two ``validate_no_shirking``
messages and two ``stop_hook`` messages.

The plugin is the sole owner of hook registration. The settings template must
register **no** hook that the plugin owns.

Oracle notes
------------
* Compares **repo artifacts**, never the live ``~/.claude/settings.json`` — that
  file carries the user's personal hooks and is not reproducible in CI.
* The naive fix ("empty the template's hooks block") would silently drop
  ``project-bootstrap.sh``, which only the template registered. ``test_plugin_owns_
  every_hook_the_template_used_to_own`` is the positive control that rejects it.
* ``test_overlap_detector_catches_a_duplicate`` is the negative control: it proves
  the detector can fail, so a green run means something.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "claude" / "settings.template.json"
PLUGIN_HOOKS = ROOT / "plugins" / "escapement-claude" / "hooks" / "hooks.json"

# Scripts the plugin must register once the template stops registering anything.
# `project-bootstrap.sh` is the migration canary: it was template-only, and the
# manifest wrongly claimed it was "user-specific, not repo-resident".
MIGRATED_FROM_TEMPLATE = {"project-bootstrap.sh"}

# Positive control: guards against a "fix" that just deletes hooks wholesale.
MIN_PLUGIN_HOOK_SCRIPTS = 41

_SCRIPT_RE = re.compile(r"([\w.-]+\.(?:py|sh))")


def _hook_scripts(config: dict) -> set[str]:
    """Every ``*.py`` / ``*.sh`` script named by any hook command in a settings-shaped dict."""
    found: set[str] = set()
    for entries in (config.get("hooks") or {}).values():
        for entry in entries:
            for hook in entry.get("hooks", []):
                match = _SCRIPT_RE.search(hook.get("command", ""))
                if match:
                    found.add(match.group(1))
    return found


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_template_and_plugin_never_register_the_same_script():
    """The double-fire regression. Intersection must be empty."""
    template = _hook_scripts(_load(TEMPLATE))
    plugin = _hook_scripts(_load(PLUGIN_HOOKS))
    overlap = template & plugin
    assert not overlap, (
        f"{len(overlap)} script(s) registered by BOTH claude/settings.template.json "
        f"and the plugin's hooks.json — each fires twice per matching tool call: "
        f"{sorted(overlap)}"
    )


def test_plugin_owns_every_hook_the_template_used_to_own():
    """Positive control: dedupe by migration, not by deletion."""
    plugin = _hook_scripts(_load(PLUGIN_HOOKS))
    missing = MIGRATED_FROM_TEMPLATE - plugin
    assert not missing, (
        f"template-only hook(s) {sorted(missing)} are registered by neither the "
        f"template nor the plugin — the gate was dropped, not migrated"
    )
    assert len(plugin) >= MIN_PLUGIN_HOOK_SCRIPTS, (
        f"plugin registers only {len(plugin)} hook scripts "
        f"(expected >= {MIN_PLUGIN_HOOK_SCRIPTS}) — hooks were deleted, not moved"
    )


def test_overlap_detector_catches_a_duplicate():
    """Negative control: the detector must be capable of failing."""
    dup = {"hooks": {"Stop": [{"hooks": [{"command": "python3 -B x/validate_no_shirking.py"}]}]}}
    plugin_like = {
        "hooks": {
            "Stop": [{"hooks": [{"command": 'python3 -B "${CLAUDE_PLUGIN_ROOT}/hooks/validate_no_shirking.py"'}]}]
        }
    }
    assert _hook_scripts(dup) & _hook_scripts(plugin_like) == {"validate_no_shirking.py"}, (
        "detector failed to match the same script across differing path styles — "
        "a real duplicate would slip through"
    )


def test_plugin_bootstrap_command_does_not_rely_on_the_exec_bit():
    """The plugin cache is read-only; a direct exec of a vendored .sh can fail.

    Whatever command registers project-bootstrap must invoke it through an
    interpreter rather than executing the file directly.
    """
    plugin = _load(PLUGIN_HOOKS)
    commands = [
        hook.get("command", "")
        for entries in (plugin.get("hooks") or {}).values()
        for entry in entries
        for hook in entry.get("hooks", [])
        if "project-bootstrap.sh" in hook.get("command", "")
    ]
    assert commands, "project-bootstrap.sh is not registered by the plugin at all"
    for command in commands:
        assert command.lstrip().startswith(("bash ", "sh ")), (
            f"project-bootstrap must run via an interpreter (plugin cache is "
            f"read-only, exec bit not guaranteed); got: {command!r}"
        )
