#!/usr/bin/env python3
"""Report Codex plugin hooks that are installed but not yet trusted.

Codex gates every plugin hook on a per-hook record in the user's
`config.toml` under `[hooks.state]`, keyed

    <pluginId>:hooks/hooks.json:<event_snake_case>:<group_index>:<hook_index>

An untrusted hook is skipped *silently*: the event simply never arrives, which
is indistinguishable from the host not supporting the event at all. That is how
a gate ships green, installs green, and does nothing -- observed 2026-09-07,
when the Codex Stop gate's five sibling SessionStart hooks fired and Stop did
not (escapement-i6p3).

This is a reporter, not an enforcer. Granting trust is the user's security
decision and is made in a Codex session, never written here.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

_EVENT_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")


def event_key(event: str) -> str:
    """Codex's trust keys use snake_case: SessionStart -> session_start."""
    return _EVENT_BOUNDARY.sub("_", event).lower()


def declared_hook_keys(plugin_id: str, hooks_json: Path) -> list[tuple[str, str]]:
    """Every (trust key, event) the installed plugin declares, in file order."""
    hooks = json.loads(hooks_json.read_text(encoding="utf-8")).get("hooks", {})
    keys: list[tuple[str, str]] = []
    for event, groups in hooks.items():
        for group_index, group in enumerate(groups):
            for hook_index, _hook in enumerate(group.get("hooks", [])):
                keys.append(
                    (
                        f"{plugin_id}:hooks/hooks.json:"
                        f"{event_key(event)}:{group_index}:{hook_index}",
                        event,
                    )
                )
    return keys


def trusted_keys(config_toml: Path) -> set[str]:
    if not config_toml.is_file():
        return set()
    try:
        data = tomllib.loads(config_toml.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError, UnicodeError):
        return set()
    state = data.get("hooks", {}).get("state", {})
    if not isinstance(state, dict):
        return set()
    return {
        key
        for key, record in state.items()
        if isinstance(record, dict) and record.get("trusted_hash")
    }


def untrusted_events(plugin_id: str, hooks_json: Path, config_toml: Path) -> list[str]:
    """Distinct events with at least one hook Codex will silently skip."""
    trusted = trusted_keys(config_toml)
    missing: list[str] = []
    for key, event in declared_hook_keys(plugin_id, hooks_json):
        if key not in trusted and event not in missing:
            missing.append(event)
    return missing


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin-id", required=True)
    parser.add_argument("--hooks-json", required=True, type=Path)
    parser.add_argument("--config-toml", required=True, type=Path)
    args = parser.parse_args(argv)

    if not args.hooks_json.is_file():
        print(f"FATAL: installed plugin has no hooks.json: {args.hooks_json}", file=sys.stderr)
        return 1

    missing = untrusted_events(args.plugin_id, args.hooks_json, args.config_toml)
    if not missing:
        print("==> OK: every installed Codex hook event is trusted.")
        return 0

    print(
        "==> NOT YET LIVE: Codex will silently skip these installed hook events "
        "until they are trusted: " + ", ".join(missing)
    )
    print(
        "    Trust is granted in Codex, not here. Start one interactive `codex` "
        "session and accept the hook trust prompt; the grant is one-time and "
        "applies to every repository."
    )
    print(f"    Trust records live in {args.config_toml} under [hooks.state].")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
