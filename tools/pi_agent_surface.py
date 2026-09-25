"""Render the minimal Pi package surface from Escapement's neutral manifest."""

from __future__ import annotations

import ast
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
    # The commands the Pi Stop adapter's block text tells the model to run,
    # named by their path inside this package. Omitting one ships a way
    # forward that does not exist.
    "harness/bin/init_contract.py",
    "harness/bin/derive_contract.py",
    "harness/bin/verify",
    # The script the Pi project_bootstrap gate (scripts/pi_project_bootstrap.py)
    # runs; a shell file, so the sibling-import closure cannot find it.
    "scripts/project-bootstrap.sh",
    # prepatch_failure_gate loads its verifier by path from the package's
    # harness/bin, which the import closure does not follow; without it the
    # gate fails open.
    "harness/bin/prepatch_verify.py",
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
    # A hook's Pi block may name the file that serves it on Pi, the way Codex
    # Stop is served by its own adapter over the shared core: stop_hook runs
    # harness/bin/pi_stop_hook.py on Pi, never the Claude adapter.
    pi_source = hook.get("hosts", {}).get("pi", {}).get("source")
    return {
        "id": hook["id"],
        "source": pi_source or hook["source"],
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


def ready_session_gates(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Hooks that add model context when a session starts.

    The extension runs them once at Pi's `session_start` with a SessionStart
    payload and re-appends their additionalContext to every turn's system
    prompt, which is how Pi keeps session context in force.
    """
    adapter = manifest["adapters"]["pi"]
    gates: list[dict[str, Any]] = []
    for hook in manifest.get("hooks", []):
        explicit = _explicit_pi_events(hook, adapter["session_source_event"], None)
        gates.extend(_gate(hook, event) for event in (explicit or [])[:1])
    return gates


def ready_agent_gates(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Gates that judge an agent dispatch.

    The extension maps a pi-subagents `subagent` call onto the Claude Agent
    payload these gates already read. Pi-declared only.
    """
    adapter = manifest["adapters"]["pi"]
    gates: list[dict[str, Any]] = []
    for hook in manifest.get("hooks", []):
        explicit = _explicit_pi_events(hook, adapter["source_event"], {adapter["agent_target_matcher"]})
        gates.extend(_gate(hook, event) for event in (explicit or [])[:1])
    return gates


def ready_mcp_gates(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Gates that judge an MCP tool call.

    pi-mcp-adapter routes every MCP call through one proxy tool; the extension
    maps it onto Claude's `mcp__<server>__<tool>` name. Pi-declared only.
    """
    adapter = manifest["adapters"]["pi"]
    gates: list[dict[str, Any]] = []
    for hook in manifest.get("hooks", []):
        explicit = _explicit_pi_events(hook, adapter["source_event"], {adapter["mcp_target_matcher"]})
        gates.extend(_gate(hook, event) for event in (explicit or [])[:1])
    return gates


def pi_tool_targets(adapter: dict[str, Any]) -> list[str]:
    """Every Pi tool the extension maps onto a Claude tool payload."""
    return [
        adapter["target_matcher"],
        *adapter["file_target_matchers"],
        adapter["read_target_matcher"],
        adapter["agent_target_matcher"],
        adapter["mcp_target_matcher"],
    ]


def ready_post_tool_gates(manifest: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """Hooks that react to a finished tool call, keyed by Pi tool name.

    The extension runs them at Pi's `tool_result` with a PostToolUse payload
    and appends what they say to the tool result the model reads. Keyed by
    tool so the extension looks its gates up instead of choosing among them.
    """
    adapter = manifest["adapters"]["pi"]
    gates: dict[str, list[dict[str, Any]]] = {}
    for tool in pi_tool_targets(adapter):
        for hook in manifest.get("hooks", []):
            explicit = _explicit_pi_events(hook, adapter["post_tool_source_event"], {tool})
            gates.setdefault(tool, []).extend(_gate(hook, event) for event in (explicit or [])[:1])
    return {tool: tool_gates for tool, tool_gates in gates.items() if tool_gates}


def ready_stop_gates(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Hooks that judge the end of an agent run.

    The extension runs them once at Pi's `agent_end` with a Stop payload; a
    block continues the run with the reason as a follow-up user message.
    """
    adapter = manifest["adapters"]["pi"]
    gates: list[dict[str, Any]] = []
    for hook in manifest.get("hooks", []):
        explicit = _explicit_pi_events(hook, adapter["stop_source_event"], None)
        gates.extend(_gate(hook, event) for event in (explicit or [])[:1])
    return gates


def _pi_gates(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    listed = [
        *ready_bash_gates(manifest),
        *ready_file_gates(manifest),
        *ready_read_gates(manifest),
        *ready_agent_gates(manifest),
        *ready_mcp_gates(manifest),
        *ready_context_gates(manifest),
        *ready_session_gates(manifest),
        *ready_stop_gates(manifest),
    ]
    for tool_gates in ready_post_tool_gates(manifest).values():
        listed.extend(tool_gates)
    return listed


def _imported_modules(path: Path) -> set[str]:
    """Top-level names of every absolute import in a Python file, including
    imports inside functions (hooks import optional siblings lazily)."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def pi_gate_sources(manifest: dict[str, Any], root: Path, shared: set[str]) -> set[str]:
    """Every file the Pi package must carry for its gates to run.

    gates.json names each gate by path, and the dispatcher opens it from the
    plugin root with the gate's own directory first on sys.path. A sibling
    module the gate imports but the package lacks fails that import, which
    most hooks treat as "allow" -- the inventory looks right and the brake is
    missing. So the set is closed over sibling imports, transitively, instead
    of relying on a hand-kept list to name each one.
    """
    pending = sorted({gate["source"] for gate in _pi_gates(manifest)} | shared | PI_HOOK_SUPPORT)
    closure: set[str] = set()
    while pending:
        source = pending.pop()
        if source in closure:
            continue
        closure.add(source)
        path = root / source
        if path.suffix != ".py" or not path.is_file():
            continue
        for module in _imported_modules(path):
            sibling = (Path(source).parent / f"{module}.py").as_posix()
            if (root / sibling).is_file():
                pending.append(sibling)
    return closure


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
        "agent_gates": ready_agent_gates(manifest),
        "mcp_gates": ready_mcp_gates(manifest),
        # A tool with no list of its own is an extension's: pi-mcp-adapter's
        # direct tools and mcpScript calls arrive that way, so the MCP gates
        # judge them too. No MCP gate matches an extension tool that is not MCP.
        "unlisted_tool_gates": ready_mcp_gates(manifest),
        "post_tool_gates": ready_post_tool_gates(manifest),
        "context_gates": ready_context_gates(manifest),
        "session_gates": ready_session_gates(manifest),
        "stop_gates": ready_stop_gates(manifest),
    }
    return json.dumps(payload, indent=2) + "\n"


def render_package(identity: dict[str, Any]) -> str:
    payload = {
        "name": "escapement",
        "version": "0.1.0",
        "description": identity["mission"],
        "license": "GPL-3.0-or-later",
        "repository": "https://github.com/alexander-vyh/escapement",
        "keywords": ["pi-package", "workflow", "oracle", "tdd", "beads"],
        "pi": {
            "extensions": ["./plugins/escapement-pi/extensions/index.ts"],
            "skills": list(PI_SKILL_DIRS),
            # pi-mcp-adapter loads package-declared servers as <package>__<server>.
            "mcp": f"./{PI_PLUGIN_ROOT.as_posix()}/{PI_MCP_CONFIG}",
            # Escapement's commands, as Pi prompt templates.
            "prompts": [f"./{PI_PLUGIN_ROOT.as_posix()}/prompts"],
            # Escapement's agents, loaded by the pi-subagents package.
            "subagents": {"agents": [f"./{PI_PLUGIN_ROOT.as_posix()}/agents"]},
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
        # Session context: run as SessionStart hooks at session_start.
        "session_source_event": "SessionStart",
        "session_target_event": "session_start",
        # pi-subagents registers its dispatch tool as `subagent` {agent, task};
        # it is mapped onto Claude's Agent payload.
        "agent_target_matcher": "subagent",
        # pi-mcp-adapter's proxy tool `mcp` {tool, server, args} carries every
        # MCP call by default; it is mapped onto Claude's mcp__<server>__<tool>.
        "mcp_target_matcher": "mcp",
        # Finished tool calls: run as PostToolUse hooks at tool_result, whose
        # result content the extension may extend (Pi extension docs).
        "post_tool_source_event": "PostToolUse",
        "post_tool_target_event": "tool_result",
        # Run end: run as Stop hooks at agent_end; a block continues the run
        # through pi.sendUserMessage(reason, {deliverAs: "followUp"}).
        "stop_source_event": "Stop",
        "stop_target_event": "agent_end",
    }
    errors: list[str] = []
    if manifest.get("adapters", {}).get("pi") != expected:
        errors.append("Pi adapter mapping must preserve the verified event contract")
    if not ready_bash_gates(manifest):
        errors.append("Pi adapter must select at least one ready behavioral gate")
    return errors
