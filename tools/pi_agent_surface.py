"""Render the minimal Pi package surface from Escapement's neutral manifest."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PI_PLUGIN_ROOT = Path("plugins/escapement-pi")
PI_MCP_CONFIG = "mcp.json"
# Same Agent Skills tree Codex ships; Pi discovers SKILL.md dirs under these.
PI_SKILL_DIRS = ("./.agents/skills",)
PI_HOOK_SUPPORT = {
    "claude/hooks/codex_pretool_dispatch.py",
    "claude/hooks/root_checkout_guard.py",
    "harness/bin/repo_outcome.py",
}


def _explicit_pi_events(hook: dict[str, Any], event_name: str, matchers: set[str] | None) -> list[dict[str, Any]] | None:
    """Events from a hook's own `pi` block, or None when the hook declares none.

    An explicit `pi` block is the hook's complete Pi declaration: it wins over
    every Codex-derived default, so a gate is never half-derived and
    half-declared. None means "no block -- derive from Codex if possible".
    """
    pi_host = hook.get("hosts", {}).get("pi")
    if pi_host is None:
        return None
    if pi_host.get("status") != "ready":
        return []
    return [
        event
        for event in pi_host.get("events", [])
        if event.get("event") == event_name
        and (matchers is None or event.get("matcher") in matchers)
    ]


def _gate(hook: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": hook["id"],
        "source": hook["source"],
        "timeout_seconds": event["timeout_seconds"],
    }


def ready_bash_gates(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    adapter = manifest["adapters"]["pi"]
    gates: list[dict[str, Any]] = []
    for hook in manifest.get("hooks", []):
        explicit = _explicit_pi_events(hook, adapter["source_event"], {adapter["target_matcher"]})
        if explicit is not None:
            gates.extend(_gate(hook, event) for event in explicit[:1])
            continue
        host = hook.get("hosts", {}).get(adapter["gate_source_host"], {})
        if host.get("status") != "ready":
            continue
        for event in host.get("events", []):
            if (
                event.get("event") == adapter["source_event"]
                and event.get("matcher") == adapter["source_matcher"]
            ):
                gates.append(_gate(hook, event))
    return gates


def ready_file_gates(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Gates that judge a file write.

    Pi has no apply_patch. It has `write` and `edit`, and the extension maps
    them onto the payload these gates already read, so a gate needs no
    knowledge of Pi. Default source is the Codex apply_patch entry, keeping
    one answer to "does this gate apply to writing a file" instead of a
    second per-host list to drift for the common case.

    A hook may instead declare its own `pi` host block. That escape exists
    for gates whose Codex block is `partial` for a reason specific to
    Codex's payload shape (e.g. apply_patch omits cwd) that does not hold for
    Pi's `write`/`edit` events, which the extension always attaches a real
    `cwd` to -- deriving Pi's readiness from Codex's in that case would drop
    a gate Pi can safely run. An explicit `pi` block always wins over the
    Codex-derived default for that hook.
    """
    adapter = manifest["adapters"]["pi"]
    matcher = adapter.get("file_source_matcher")
    file_targets = set(adapter.get("file_target_matchers", []))
    gates: list[dict[str, Any]] = []
    for hook in manifest.get("hooks", []):
        explicit = _explicit_pi_events(hook, adapter["source_event"], file_targets)
        if explicit is not None:
            gates.extend(_gate(hook, event) for event in explicit[:1])
            continue
        if not matcher:
            continue
        host = hook.get("hosts", {}).get(adapter["gate_source_host"], {})
        if host.get("status") != "ready":
            continue
        for event in host.get("events", []):
            if (
                event.get("event") == adapter["source_event"]
                and event.get("matcher") == matcher
            ):
                gates.append(_gate(hook, event))
    return gates


def ready_read_gates(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Gates that judge a file read. Pi-declared only: Codex has no read tool."""
    adapter = manifest["adapters"]["pi"]
    gates: list[dict[str, Any]] = []
    for hook in manifest.get("hooks", []):
        explicit = _explicit_pi_events(hook, adapter["source_event"], {adapter["read_target_matcher"]})
        gates.extend(_gate(hook, event) for event in (explicit or [])[:1])
    return gates


def ready_context_gates(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Hooks that add model context when a prompt is submitted.

    The extension runs them at Pi's `before_agent_start` with the payload of a
    UserPromptSubmit hook and appends their additionalContext to that turn's
    system prompt, so a context hook needs no knowledge of Pi.
    """
    adapter = manifest["adapters"]["pi"]
    gates: list[dict[str, Any]] = []
    for hook in manifest.get("hooks", []):
        explicit = _explicit_pi_events(hook, adapter["context_source_event"], None)
        gates.extend(_gate(hook, event) for event in (explicit or [])[:1])
    return gates


def pi_status(manifest: dict[str, Any], hook: dict[str, Any]) -> str | None:
    """Effective Pi status: the explicit block's, `ready` when derived, else None."""
    explicit = hook.get("hosts", {}).get("pi")
    if explicit is not None:
        return explicit.get("status")
    hook_id = hook.get("id")
    derived = [*ready_bash_gates(manifest), *ready_file_gates(manifest)]
    return "ready" if any(gate["id"] == hook_id for gate in derived) else None


def render_gate_inventory(manifest: dict[str, Any]) -> str:
    payload = {
        "version": 1,
        "dispatcher": "claude/hooks/codex_pretool_dispatch.py",
        "gates": ready_bash_gates(manifest),
        "file_gates": ready_file_gates(manifest),
        "read_gates": ready_read_gates(manifest),
        "context_gates": ready_context_gates(manifest),
    }
    return json.dumps(payload, indent=2) + "\n"


def render_package(identity: dict[str, Any]) -> str:
    payload = {
        "name": "escapement",
        "version": "1.0.0",
        "description": identity["mission"],
        "license": "GPL-3.0-or-later",
        "repository": "https://github.com/alexander-vyh/escapement",
        "keywords": ["pi-package", "workflow", "oracle", "tdd", "beads"],
        "pi": {
            "extensions": ["./plugins/escapement-pi/extensions/index.ts"],
            "skills": list(PI_SKILL_DIRS),
            # pi-mcp-adapter loads package-declared servers as <package>__<server>.
            "mcp": f"./{PI_PLUGIN_ROOT.as_posix()}/{PI_MCP_CONFIG}",
        },
    }
    return json.dumps(payload, indent=2) + "\n"


def validate_adapter(manifest: dict[str, Any]) -> list[str]:
    expected = {
        "gate_source_host": "codex",
        "source_event": "PreToolUse",
        "source_matcher": "Bash",
        "target_event": "tool_call",
        "target_matcher": "bash",
        # Captured, not assumed: `pi --mode json` names its file tools `write`
        # and `edit`. Pinning them here means inventing a tool name fails the
        # renderer instead of shipping a gate that silently never matches.
        "file_source_matcher": "apply_patch",
        "file_target_matchers": ["write", "edit"],
        # Pi's `read` carries {path, offset?, limit?} (Pi extension docs).
        "read_target_matcher": "read",
        # Prompt-time context: run as UserPromptSubmit hooks at before_agent_start.
        "context_source_event": "UserPromptSubmit",
        "context_target_event": "before_agent_start",
    }
    errors: list[str] = []
    if manifest.get("adapters", {}).get("pi") != expected:
        errors.append("Pi adapter mapping must preserve the verified event contract")
    if not ready_bash_gates(manifest):
        errors.append("Pi adapter must select at least one ready behavioral gate")
    return errors
