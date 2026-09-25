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
import hashlib
import json
import re
import sys
import tomllib
from pathlib import Path

_EVENT_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")


def event_key(event: str) -> str:
    """Codex's trust keys use snake_case: SessionStart -> session_start."""
    return _EVENT_BOUNDARY.sub("_", event).lower()


# Codex's default handler timeout, in seconds; it is part of the trust hash.
_DEFAULT_TIMEOUT = 600
_SHORT_TIMEOUT_EVENTS = {"SessionEnd": 1, "Interrupt": 1}
# Events whose matcher Codex ignores; it is left out of their trust hash.
_MATCHERLESS_EVENTS = {"UserPromptSubmit", "Stop", "Interrupt"}


def hook_hash(event: str, matcher: str | None, hook: dict) -> str:
    """The ``trusted_hash`` Codex records for one handler.

    Codex hashes the canonical JSON of the normalized handler, not the key, so
    a hook that moves to another index or changes its command is untrusted
    even though a record exists under its key.
    """
    handler = {
        "async": bool(hook.get("async", False)),
        "command": hook.get("command", ""),
        "timeout": hook.get("timeout") or _SHORT_TIMEOUT_EVENTS.get(event, _DEFAULT_TIMEOUT),
        "type": hook.get("type", "command"),
    }
    if hook.get("statusMessage") is not None:
        handler["statusMessage"] = hook["statusMessage"]
    definition: dict = {"event_name": event_key(event), "hooks": [handler]}
    if event not in _MATCHERLESS_EVENTS:
        definition["matcher"] = matcher or ""
    canonical = json.dumps(definition, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def declared_hooks(plugin_id: str, hooks_json: Path) -> list[tuple[str, str, str]]:
    """Every (trust key, event, expected hash) the installed plugin declares."""
    hooks = json.loads(hooks_json.read_text(encoding="utf-8")).get("hooks", {})
    declared: list[tuple[str, str, str]] = []
    for event, groups in hooks.items():
        for group_index, group in enumerate(groups):
            for hook_index, hook in enumerate(group.get("hooks", [])):
                declared.append(
                    (
                        f"{plugin_id}:hooks/hooks.json:"
                        f"{event_key(event)}:{group_index}:{hook_index}",
                        event,
                        hook_hash(event, group.get("matcher"), hook),
                    )
                )
    return declared


def trusted_hashes(config_toml: Path) -> dict[str, str]:
    if not config_toml.is_file():
        return {}
    try:
        data = tomllib.loads(config_toml.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError, UnicodeError):
        return {}
    state = data.get("hooks", {}).get("state", {})
    if not isinstance(state, dict):
        return {}
    return {
        key: record["trusted_hash"]
        for key, record in state.items()
        if isinstance(record, dict) and record.get("trusted_hash")
    }


def untrusted_events(plugin_id: str, hooks_json: Path, config_toml: Path) -> list[str]:
    """Distinct events with at least one hook Codex will silently skip."""
    trusted = trusted_hashes(config_toml)
    missing: list[str] = []
    for key, event, expected in declared_hooks(plugin_id, hooks_json):
        if trusted.get(key) != expected and event not in missing:
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
        "session and accept the hook trust prompt. A grant covers the exact hook "
        "definition at its position, so a release that adds, moves or changes a "
        "hook needs it again."
    )
    print(f"    Trust records live in {args.config_toml} under [hooks.state].")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
