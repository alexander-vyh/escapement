import copy
import importlib.util
import json
import re
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "agent-surfaces" / "manifest.json"
PI_ROOT = ROOT / "plugins" / "escapement-pi"
EXTENSION = PI_ROOT / "extensions" / "index.ts"
EXTENSION_MODULES = sorted((PI_ROOT / "extensions").glob("*.ts"))
RENDERER = ROOT / "tools" / "render_agent_surfaces.py"


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _explicit_pi(hook: dict, event_name: str, matchers: set | None) -> list | None:
    """Independent reading of an explicit `pi` block: it is the whole Pi
    declaration for that hook, so it replaces any Codex-derived default."""
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
    ][:1]


def _entry(hook: dict, event: dict) -> dict:
    source = hook["hosts"].get("pi", {}).get("source") or hook["source"]
    return {"id": hook["id"], "source": source, "timeout_seconds": event["timeout_seconds"]}


def _pi_gates(manifest: dict, pi_matchers: set | None, codex_matcher: str | None, event_name: str) -> list[dict]:
    adapter = manifest["adapters"]["pi"]
    gates = []
    for hook in manifest["hooks"]:
        explicit = _explicit_pi(hook, event_name, pi_matchers)
        if explicit is not None:
            gates.extend(_entry(hook, event) for event in explicit)
            continue
        if codex_matcher is None:
            continue
        host = hook["hosts"][adapter["gate_source_host"]]
        if host["status"] != "ready":
            continue
        gates.extend(
            _entry(hook, event)
            for event in host.get("events", [])
            if event["event"] == event_name and event["matcher"] == codex_matcher
        )
    return gates


def _pi_ready_bash_gates(manifest: dict) -> list[dict]:
    adapter = manifest["adapters"]["pi"]
    return _pi_gates(manifest, {adapter["target_matcher"]}, adapter["source_matcher"], adapter["source_event"])


def _pi_ready_file_gates(manifest: dict) -> list[dict]:
    """Recompute the file-gate selection independently of the renderer."""
    adapter = manifest["adapters"]["pi"]
    return _pi_gates(
        manifest, set(adapter["file_target_matchers"]), adapter["file_source_matcher"], adapter["source_event"]
    )


def test_root_package_resources_resolve_inside_the_package() -> None:
    """Pi loads extensions, skills and MCP config from these paths; a path that
    does not resolve is a resource Pi silently never loads."""
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))

    assert "pi-package" in package["keywords"]
    pi = package["pi"]
    for entry in [*pi["extensions"], *pi["skills"], pi["mcp"]]:
        assert (ROOT / entry).exists(), f"package.json pi entry does not resolve: {entry}"
    assert any((ROOT / entry).glob("*/SKILL.md") for entry in pi["skills"]), "Pi skills dir holds no skills"
    assert "serena" in json.loads((ROOT / pi["mcp"]).read_text(encoding="utf-8"))["mcpServers"]
    assert (PI_ROOT / "PI.md").is_file()
    assert any((ROOT / entry).glob("*.md") for entry in pi["prompts"]), "Pi prompts dir holds no commands"
    assert any((ROOT / entry).glob("*.md") for entry in pi["subagents"]["agents"]), "Pi agents dir holds no agents"


def test_generated_gate_inventory_exactly_matches_pi_ready_manifest_gates() -> None:
    manifest = _manifest()
    adapter = manifest["adapters"]["pi"]
    inventory = json.loads((PI_ROOT / "gates.json").read_text(encoding="utf-8"))

    tools = [
        adapter["target_matcher"], *adapter["file_target_matchers"], adapter["read_target_matcher"],
        adapter["agent_target_matcher"], adapter["mcp_target_matcher"],
    ]
    post_tool = {
        tool: _pi_gates(manifest, {tool}, None, adapter["post_tool_source_event"]) for tool in tools
    }
    assert inventory == {
        "version": 1,
        "dispatcher": "claude/hooks/codex_pretool_dispatch.py",
        "gates": _pi_ready_bash_gates(manifest),
        "file_gates": _pi_ready_file_gates(manifest),
        "read_gates": _pi_gates(manifest, {adapter["read_target_matcher"]}, None, adapter["source_event"]),
        "agent_gates": _pi_gates(manifest, {adapter["agent_target_matcher"]}, None, adapter["source_event"]),
        "mcp_gates": _pi_gates(manifest, {adapter["mcp_target_matcher"]}, None, adapter["source_event"]),
        # An extension's tool (pi-mcp-adapter direct tools, mcpScript) has no
        # list of its own and is judged by the MCP gates.
        "unlisted_tool_gates": _pi_gates(manifest, {adapter["mcp_target_matcher"]}, None, adapter["source_event"]),
        "post_tool_gates": {tool: gates for tool, gates in post_tool.items() if gates},
        "context_gates": _pi_gates(manifest, None, None, adapter["context_source_event"]),
        "session_gates": _pi_gates(manifest, None, None, adapter["session_source_event"]),
        "stop_gates": _pi_gates(manifest, None, None, adapter["stop_source_event"]),
    }
    assert inventory["file_gates"], (
        "Pi must ship the file-write gates; an empty list means Pi has no brake "
        "on file growth, which is the gap this inventory key exists to close"
    )
    assert inventory["gates"], "Pi must ship at least one behavioral gate"
    # Every gate named must also be SHIPPED. gates.json names a gate by path and
    # the dispatcher opens it from the plugin root, so a gate listed but not
    # vendored reads as a healthy inventory with the brake missing.
    lists = {key: inventory[key] for key in inventory if key.endswith("gates") and key != "post_tool_gates"}
    lists.update({f"post_tool_gates.{tool}": gates for tool, gates in inventory["post_tool_gates"].items()})
    for key, gates in lists.items():
        sources = [gate["source"] for gate in gates]
        assert len(sources) == len(set(sources)), f"Pi {key} must not duplicate gates"
        missing = [s for s in sources if not (PI_ROOT / s).is_file()]
        assert not missing, f"Pi {key} names gates it does not ship: {missing}"


def test_renderer_recomputes_pi_inventory_when_shared_manifest_changes() -> None:
    spec = importlib.util.spec_from_file_location("pi_renderer_mutation", RENDERER)
    assert spec and spec.loader
    renderer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(renderer)

    manifest = _manifest()
    mutated = copy.deepcopy(manifest)
    planted = copy.deepcopy(
        next(hook for hook in manifest["hooks"] if hook["id"] == "beads_worktree_guard")
    )
    planted["id"] = "pi_inventory_mutation_control"
    mutated["hooks"].append(planted)

    original = json.loads(renderer._render_pi_gate_inventory(manifest))
    changed = json.loads(renderer._render_pi_gate_inventory(mutated))
    assert changed != original
    assert changed["gates"][-1]["id"] == "pi_inventory_mutation_control"


EXPECTED_TS_FUNCTIONS = {
    "fail",
    "confinedFile",
    "loadRuntime",
    "parseDispatcherResponse",
    "runDispatcher",
    "surfaceDiagnostics",
    # payloads.ts -- the one place a Pi payload is read, and only to rewrite
    # it into the Claude shape a gate already reads. None of these decides
    # anything about the call.
    "claudeToolCall",
    # A workflowScript's children, each mapped exactly as a one-child call.
    "claudeToolCalls",
    "textOf",
    "claudeTranscript",
    # Host identity, not policy: reads Pi's session id off the handler context
    # so the payload carries the same `session_id` every gate already reads on
    # Claude. It decides nothing about the tool call. Passing a per-call id here
    # silently defeated per-session dedup in discovery-close-gate, which is why
    # this is a named, tested seam rather than two inline narrowings.
    "sessionIdOf",
    # Host plumbing, same category: forwards the per-call working directory the
    # Bash tool already declares. It reads no command text and decides nothing;
    # resolving a `cd` prefix stays in the dispatcher.
    "cwdOf",
}


def _extension_source() -> str:
    """Every module of the rendered extension, entry first. A check that read
    only index.ts would leave each sibling module a blind spot."""
    modules = sorted(EXTENSION_MODULES, key=lambda path: path.name != "index.ts")
    assert [path.name for path in modules][:1] == ["index.ts"]
    return "\n".join(path.read_text(encoding="utf-8") for path in modules)


def _top_level_body(source: str, name: str) -> str:
    return source.split(f"function {name}(", 1)[1].split("\n}\n", 1)[0]


def _assert_thin_pi_extension(source: str) -> None:
    """The Pi extension is a bridge, not a policy engine.

    Asserted as properties rather than as occurrence counts. The previous
    version pinned things like ``run_dispatcher.count("payload") == 2`` and the
    exact text of a for-loop, which made every legitimate refactor look like a
    policy violation while catching nothing the properties below miss.

    What must hold, across every extension module: one dispatcher process per
    event, one tool handler, no gate named in TypeScript, no dispatcher path in
    TypeScript, no decision logic in the transport or the diagnostics, no
    inspection of tool content, tool input read only by the payload mapping,
    and no functions beyond the bridge's own.
    """
    run_dispatcher = source.split("function runDispatcher", 1)[1].split(
        "function surfaceDiagnostics", 1
    )[0]
    diagnostics = source.split("function surfaceDiagnostics", 1)[1].split(
        "export default function", 1
    )[0]
    response_parser = source.split("function parseDispatcherResponse", 1)[1].split(
        "function runDispatcher", 1
    )[0]

    assert source.count("spawn(") == 1, "one tool event must start one dispatcher"
    assert source.count('pi.on("tool_call"') == 1

    # The prompt, session, post-tool and stop handlers compose host text, PI.md
    # and gate output. A string literal of their own beyond the failure
    # notices and payload plumbing is prose policy that lives only in Pi.
    allowed_literals = {
        "`${event.systemPrompt}\\n\\nEscapement Pi configuration error: ${runtime.message}`",
        "`Escapement Pi prompt-context hooks failed: ${error}`",
        "`Escapement Pi session-start hooks failed: ${error}`",
        "`Escapement Pi post-tool hooks failed: ${error}`",
        "`Escapement Pi stop hooks failed: ${error}`",
        '"Escapement stop hooks blocked this stop"',
        '"UserPromptSubmit"',
        '"SessionStart"',
        '"PostToolUse"',
        '"Stop"',
        '"startup"',
        '"info"',
        '"string"',
        '"text"',
        '"message"',
        '"assistant"',
        '"block"',
        '"escapement"',
        '"followUp"',
        '"nextTurn"',
        '""',
        '"\\n\\n"',
    }
    for event in ("before_agent_start", "session_start", "tool_result", "agent_end", "session_shutdown"):
        # A one-line handler has no closing `});` line; the entry function's
        # own closing brace bounds it, so a sibling module is never read as
        # part of the last handler.
        handler = source.split(f'pi.on("{event}"', 1)[1].split("\n  });\n", 1)[0].split("\n}\n", 1)[0]
        for literal in re.findall(r'`[^`]*`|"(?:[^"\\\\]|\\\\.)*"', handler):
            assert literal in allowed_literals, (
                f"{event} handler adds text of its own: {literal}. "
                "Prompt policy belongs in PI.md or a context gate."
            )

    # The extension must not read what the tool is doing. Every mutation that
    # smuggles policy into TypeScript has to look at the payload to decide.
    # One regex test is plumbing, not policy: the mapping asks whether a file
    # tool's path is a URI (omp's xd://, local://) rather than a file on disk.
    mapping = _top_level_body(source, "claudeToolCall")
    assert mapping.count("URI_SCHEME.test(path)") == 1
    uninspected = source.replace("URI_SCHEME.test(path)", "", 1)
    for inspector in (".includes(", ".indexOf(", ".match(", ".search(", ".test(", ".exec("):
        assert inspector not in uninspected, (
            f"TypeScript inspects tool content via {inspector}; policy belongs in a gate"
        )

    # Tool input is read in exactly one place: the mapping onto the Claude
    # payload (plus cwdOf, which forwards a declared working directory).
    # Everywhere else a Pi tool's input may only be handed to that mapping.
    elsewhere = source
    for name in ("claudeToolCall", "claudeToolCalls", "cwdOf"):
        elsewhere = elsewhere.replace(_top_level_body(source, name), "")
    handed_to_mapping = sum(
        elsewhere.count(f"{name}(event.toolName, event.input)")
        for name in ("claudeToolCall", "claudeToolCalls")
    )
    assert elsewhere.count(".input") == handed_to_mapping, (
        "a Pi tool's input is read outside the payload mapping; policy belongs in a gate"
    )
    assert elsewhere.count(".arguments") == 2 and "claudeToolCall(block.name, block.arguments)" in elsewhere, (
        "a transcript tool call's arguments are read outside the payload mapping"
    )
    assert "args." not in elsewhere and "args[" not in elsewhere, (
        "a Pi tool's arguments are read outside the payload mapping"
    )

    # The bridge may block for exactly three reasons: a gate said so, its
    # configuration is broken, or the dispatcher failed. A `reason:` that is a
    # TypeScript literal is the extension inventing policy of its own -- which
    # is how every remaining mutant below smuggles it in without touching the
    # transport or adding a helper.
    handler = source.split('pi.on("tool_call"', 1)[1]
    allowed_reasons = {
        'hook.permissionDecisionReason || "Escapement blocked this Pi tool call"',
        '`Escapement Pi configuration error: ${runtime.message}`',
        '`Escapement Pi adapter error: ${error}`',
        '"Escapement received an invalid Pi Bash payload"',
    }
    for match in re.finditer(r"reason: (.+?),?\n", handler):
        reason = match.group(1).strip().rstrip(",").removesuffix("};").strip()
        assert reason in allowed_reasons, (
            f"extension blocks with a reason of its own: {reason}. "
            "Policy belongs in a gate, not in the bridge."
        )

    declared = set(re.findall(r"^\s*(?:export )?function (\w+)", source, re.M))
    assert declared == EXPECTED_TS_FUNCTIONS, (
        f"unexpected TypeScript functions: {declared ^ EXPECTED_TS_FUNCTIONS}. "
        "A new helper here is usually policy that belongs in a gate."
    )

    # Transport and diagnostics carry decisions; they must not make them.
    assert "permissionDecision" not in run_dispatcher
    assert "hookSpecificOutput" not in run_dispatcher
    assert "child.stdin.end(JSON.stringify(payload));" in run_dispatcher
    assert "permissionDecision" not in diagnostics
    assert "block:" not in diagnostics
    assert "throw " not in diagnostics
    assert "pi.sendMessage(" in diagnostics
    assert "JSON.parse(stdout)" in response_parser
    assert "return {" not in response_parser

    # The bridge runs the inventory as given. Selecting among gates -- by
    # filtering the list or by comparing an id -- is the extension deciding
    # which policy applies, which is the manifest's job.
    runtime_loader = source.split("function loadRuntime", 1)[1].split(
        "function parseDispatcherResponse", 1
    )[0]
    for scope, name in ((runtime_loader, "loadRuntime"), (run_dispatcher, "runDispatcher")):
        assert ".filter(" not in scope, (
            f"{name} selects among gates; it must run the inventory as given"
        )
    inventory = json.loads((PI_ROOT / "gates.json").read_text(encoding="utf-8"))
    for key, gates in inventory.items():
        if not key.endswith("gates"):
            continue
        lists = gates.values() if isinstance(gates, dict) else [gates]
        for gate in (gate for gate_list in lists for gate in gate_list):
            # Whole identifiers only: `stop_hook_active` is Claude's Stop
            # payload field, not a reference to the stop_hook gate.
            assert not re.search(rf"(?<![\w-]){re.escape(gate['id'])}(?![\w-])", source), (
                f"extension names {gate['id']}; the bridge must not know a gate by id"
            )

    assert "codex_pretool_dispatch.py" not in source, (
        "the generated inventory, not TypeScript, owns the dispatcher path"
    )
    for gate_specific_policy in (
        "beads_worktree_guard.py",
        "test_oracle_brief_gate.py",
        "implementation_echo_test_gate.py",
        "file_complexity_gate.py",
    ):
        assert gate_specific_policy not in source


def test_pi_extension_is_a_thin_single_dispatch_bridge() -> None:
    _assert_thin_pi_extension(_extension_source())


def _mutate(source: str, anchor: str, replacement: str) -> str:
    """A mutant whose anchor vanished would equal the source and prove nothing."""
    assert anchor in source, f"mutation anchor is gone: {anchor!r}"
    return source.replace(anchor, replacement, 1)


def test_pi_architecture_check_rejects_selective_typescript_policy() -> None:
    source = _extension_source()
    call_anchor = "    const mapped = claudeToolCall(event.toolName, event.input);"
    mutants = {
        "string inspection before dispatch": _mutate(
            source,
            call_anchor,
            '    if (String(event.input?.command).includes("rm -rf")) {\n'
            '      return { block: true, reason: "TypeScript safety policy" };\n'
            "    }\n" + call_anchor,
        ),
        "policy helper": _mutate(
            source,
            "function runDispatcher",
            "function invalidBash(value: unknown): boolean {\n"
            '  return typeof value !== "string" || value === "rm -rf";\n'
            "}\n\nfunction runDispatcher",
        ),
        "transport inspection": _mutate(
            source,
            "  const argv =",
            '  if (JSON.stringify(payload).indexOf("rm -rf") >= 0) {\n'
            '    return Promise.resolve({ hookSpecificOutput: { permissionDecision: "deny" } });\n'
            "  }\n  const argv =",
        ),
        "transport regex": _mutate(
            source,
            "  const argv =",
            "  if (/sudo/.test(JSON.stringify(payload))) {\n"
            '    return Promise.resolve({ hookSpecificOutput: { hookEventName: "PreToolUse", permissionDecision: "deny" } });\n'
            "  }\n  const argv =",
        ),
        "input read outside the mapping": _mutate(
            source,
            call_anchor,
            '    if (Object.values(event.input ?? {}).some((value) => value === "sudo")) return;\n' + call_anchor,
        ),
        "cwd policy": _mutate(
            source,
            call_anchor,
            '    if (context.cwd === "/") {\n'
            '      return { block: true, reason: "TypeScript root policy" };\n'
            "    }\n" + call_anchor,
        ),
        "parser policy": _mutate(
            source,
            "  const result = JSON.parse(stdout);",
            "  const result = JSON.parse(stdout);\n"
            "  if (/sudo/.test(stdout)) {\n"
            '    return { hookSpecificOutput: { hookEventName: "PreToolUse", permissionDecision: "deny" } };\n'
            "  }",
        ),
        "diagnostics policy": _mutate(
            source,
            "  if (messages.length === 0) return;",
            "  if (/credential/.test(String(messages))) {\n"
            '    throw new Error("TypeScript diagnostics policy");\n'
            "  }\n  if (messages.length === 0) return;",
        ),
        "inventory filter": _mutate(
            source,
            '    ["bash", parsed.gates],',
            '    ["bash", parsed.gates.filter((gate: Gate) => gate.id !== "merge_authorization_gate")],',
        ),
        "transport filter": _mutate(
            source,
            "  for (const gate of gates) {\n    argv.push(",
            '  for (const gate of gates) {\n    if (gate.id === "merge_authorization_gate") continue;\n    argv.push(',
        ),
        "prompt prose": _mutate(
            source,
            "if (added) sections.push(added);",
            'if (added) sections.push(added);\n    sections.push("Pi-only policy: never execute sudo");',
        ),
        "second tool handler": _mutate(
            source,
            '  pi.on("before_agent_start",',
            '  pi.on("tool_call", async ({ input }) => {\n'
            "    const value = Object.values(input ?? {})[0];\n"
            '    return value === "sudo" ? { block: true, reason: "Pi-only policy" } : undefined;\n'
            "  });\n\n"
            '  pi.on("before_agent_start",',
        ),
        "stop prose": _mutate(
            source,
            "    surfaceDiagnostics(pi, result, { triggerTurn: false });\n    stopHookActive =",
            '    pi.sendUserMessage("Pi-only policy: summarize before stopping", { deliverAs: "followUp" });\n'
            "    surfaceDiagnostics(pi, result, { triggerTurn: false });\n    stopHookActive =",
        ),
        # payloads.ts is scanned like index.ts: a sibling module is no hiding place.
        "inspection in the payload module": _mutate(
            source,
            "export function textOf(content: unknown): string {\n",
            "export function textOf(content: unknown): string {\n"
            '  if (String(content).includes("sudo")) return "";\n',
        ),
        "gate id in the payload module": _mutate(
            source,
            "export function textOf(content: unknown): string {\n",
            "export function textOf(content: unknown): string {\n"
            '  if (content === "root_checkout_guard") return "";\n',
        ),
        "arguments read by the transcript": _mutate(
            source,
            "        } else if (block?.type === \"toolCall\") {\n",
            "        } else if (block?.type === \"toolCall\") {\n"
            '          if (block.arguments?.command === "sudo") continue;\n',
        ),
    }
    for name, mutant in mutants.items():
        with pytest.raises(AssertionError):
            _assert_thin_pi_extension(mutant)
            pytest.fail(f"architecture check accepted the {name} mutant")


def test_pi_extension_runs_one_dispatcher_per_tool_call_for_allow_and_deny(
    tmp_path,
) -> None:
    process_log = tmp_path / "python-processes.log"
    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    python_shim = shim_dir / "python3"
    python_shim.write_text(
        "#!/bin/sh\n"
        f"printf 'dispatch\\n' >> {process_log!s}\n"
        f"exec {sys.executable} \"$@\"\n",
        encoding="utf-8",
    )
    python_shim.chmod(0o755)
    probe = tmp_path / "probe.mjs"
    probe.write_text(
        """
const { default: extension } = await import(process.argv[2]);

const handlers = new Map();
extension({
  on(event, handler) {
    const registered = handlers.get(event) ?? [];
    registered.push(handler);
    handlers.set(event, registered);
  },
});
const toolCalls = handlers.get("tool_call") ?? [];
if (toolCalls.length !== 1) {
  throw new Error(`Expected one Pi tool_call handler, got ${toolCalls.length}`);
}
const toolCall = toolCalls[0];
const context = { cwd: process.argv[3] };
const beforeAgentStarts = handlers.get("before_agent_start") ?? [];
if (beforeAgentStarts.length !== 1) {
  throw new Error(
    `Expected one Pi before_agent_start handler, got ${beforeAgentStarts.length}`,
  );
}
const beforeAgentStart = beforeAgentStarts[0];
const injected = await beforeAgentStart({
  type: "before_agent_start", systemPrompt: "base prompt",
}, context);
const safe = await toolCall({
  type: "tool_call", toolCallId: "safe", toolName: "bash",
  input: { command: "pwd" },
}, context);
const denied = await toolCall({
  type: "tool_call", toolCallId: "denied", toolName: "bash",
  input: { command: "git worktree add ../bad feat/bad" },
}, context);
console.log(JSON.stringify({ safe: safe ?? null, denied, injected }));
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "node",
            "--experimental-strip-types",
            str(probe),
            EXTENSION.as_uri(),
            str(ROOT),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "PATH": f"{shim_dir}:{os.environ['PATH']}"},
    )

    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["safe"] is None
    assert output["denied"]["block"] is True
    assert "escapement-worktree create" in output["denied"]["reason"]
    assert output["injected"]["systemPrompt"].startswith(
        "base prompt\n\n" + (PI_ROOT / "PI.md").read_text(encoding="utf-8")
    )
    # One run for the prompt-context gates, then one per tool call.
    assert process_log.read_text(encoding="utf-8").splitlines() == [
        "dispatch",
        "dispatch",
        "dispatch",
    ], "each Pi event must use exactly one shared dispatcher process"


def test_pi_extension_sends_one_stable_session_id_across_tool_calls(tmp_path) -> None:
    """THE DEFECT (escapement-kdrc): session_id was mapped to toolCallId,
    which is unique per call, so ask-once gate dedup never engaged and every
    bead-closing attempt re-asked forever. The dispatcher payload must carry
    ONE id for the whole session, distinct from every toolCallId."""
    payloads_log = tmp_path / "dispatcher-payloads.log"
    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    python_shim = shim_dir / "python3"
    python_shim.write_text(
        "#!/bin/sh\n"
        f"tee -a {payloads_log!s} | {sys.executable} \"$@\"\n",
        encoding="utf-8",
    )
    python_shim.chmod(0o755)
    probe = tmp_path / "probe.mjs"
    probe.write_text(
        """
const { default: extension } = await import(process.argv[2]);
const handlers = new Map();
extension({
  on(event, handler) {
    const registered = handlers.get(event) ?? [];
    registered.push(handler);
    handlers.set(event, registered);
  },
});
const toolCalls = handlers.get("tool_call") ?? [];
if (toolCalls.length !== 1) {
  throw new Error(`Expected one Pi tool_call handler, got ${toolCalls.length}`);
}
const toolCall = toolCalls[0];
const context = { cwd: process.argv[3] };
const first = await toolCall({
  type: "tool_call", toolCallId: "call-alpha", toolName: "bash",
  input: { command: "pwd" },
}, context);
const second = await toolCall({
  type: "tool_call", toolCallId: "call-beta", toolName: "bash",
  input: { command: "pwd" },
}, context);
console.log(JSON.stringify({ first: first ?? null, second: second ?? null }));
""",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            "node",
            "--experimental-strip-types",
            str(probe),
            EXTENSION.as_uri(),
            str(ROOT),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "PATH": f"{shim_dir}:{os.environ['PATH']}"},
    )
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["first"] is None and output["second"] is None

    raw = payloads_log.read_text(encoding="utf-8")
    payloads: list[dict] = []
    decoder = json.JSONDecoder()
    index = 0
    while index < len(raw):
        while index < len(raw) and raw[index].isspace():
            index += 1
        if index >= len(raw):
            break
        payload, index = decoder.raw_decode(raw, index)
        payloads.append(payload)
    assert len(payloads) == 2, "both tool calls must reach the dispatcher"
    session_ids = {p.get("session_id") for p in payloads}
    assert session_ids == {payloads[0]["session_id"]}, (
        "session_id must be stable across tool calls"
    )
    assert payloads[0]["session_id"] not in {"call-alpha", "call-beta"}, (
        "session_id must not be the per-call toolCallId"
    )


def test_real_pi_sdk_loads_installed_extension_without_duplicate_skills_and_nonce_gate(
    tmp_path,
) -> None:
    pi = shutil.which("pi")
    assert pi, "Pi CLI is required for the package contract test"
    pi_sdk = Path(pi).resolve().with_name("index.js")
    assert pi_sdk.is_file(), "Pi SDK must sit beside the selected CLI entrypoint"
    package = tmp_path / "escapement-package"
    package.mkdir()
    shutil.copy2(ROOT / "package.json", package / "package.json")
    shutil.copytree(PI_ROOT, package / "plugins" / "escapement-pi")
    native_skill = tmp_path / ".agents" / "skills" / "openspec-explore"
    native_skill.mkdir(parents=True)
    shutil.copy2(
        ROOT / ".agents" / "skills" / "openspec-explore" / "SKILL.md",
        native_skill / "SKILL.md",
    )

    deny_nonce = f"deny-{uuid.uuid4()}"
    safe_nonce = f"safe-{uuid.uuid4()}"
    deny_reason = f"python-gate-{uuid.uuid4()}"
    pid_log = tmp_path / "gate-pids.log"
    test_gates = package / "plugins" / "escapement-pi" / "test-gates"
    test_gates.mkdir()
    (test_gates / "nonce_gate.py").write_text(
        "import json, os, sys\n"
        "payload = json.load(sys.stdin)\n"
        "with open(os.environ['PI_TEST_PID_LOG'], 'a') as out: "
        "out.write(str(os.getpid()) + '\\n')\n"
        "if payload.get('tool_input', {}).get('command') == os.environ['PI_DENY_NONCE']:\n"
        "    print(json.dumps({'hookSpecificOutput': {"
        "'hookEventName': 'PreToolUse', 'permissionDecision': 'deny', "
        "'permissionDecisionReason': os.environ['PI_DENY_REASON']}}))\n"
        "else:\n"
        "    print('{}')\n",
        encoding="utf-8",
    )
    (test_gates / "pid_witness.py").write_text(
        "import os\n"
        "with open(os.environ['PI_TEST_PID_LOG'], 'a') as out: "
        "out.write(str(os.getpid()) + '\\n')\n"
        "print('{}')\n",
        encoding="utf-8",
    )
    inventory_path = package / "plugins" / "escapement-pi" / "gates.json"
    inventory_path.write_text(
        json.dumps(
            {
                "version": 1,
                "dispatcher": "claude/hooks/codex_pretool_dispatch.py",
                "gates": [
                    {
                        "id": "nonce_gate",
                        "source": "test-gates/nonce_gate.py",
                        "timeout_seconds": 5,
                    },
                    {
                        "id": "pid_witness",
                        "source": "test-gates/pid_witness.py",
                        "timeout_seconds": 5,
                    },
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    config = tmp_path / "pi-agent"
    env = {
        **os.environ,
        "PI_CODING_AGENT_DIR": str(config),
        "PI_OFFLINE": "1",
        "PI_TEST_PID_LOG": str(pid_log),
        "PI_DENY_NONCE": deny_nonce,
        "PI_DENY_REASON": deny_reason,
    }

    install = subprocess.run(
        [pi, "install", str(package), "--approve"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )
    assert install.returncode == 0, install.stderr

    listed = subprocess.run(
        [pi, "list", "--approve"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    assert listed.returncode == 0, listed.stderr
    assert "escapement" in listed.stdout.lower()
    assert str(package) in listed.stdout

    probe = tmp_path / "installed-session.mjs"
    probe.write_text(
        """
const { createAgentSession } = await import(process.argv[2]);
const packageRoot = process.argv[4];
const created = await createAgentSession({
  agentDir: process.argv[3], cwd: process.argv[5], noTools: "all",
});
const { session, extensionsResult } = created;
const safe = await session.extensionRunner.emitToolCall({
  type: "tool_call", toolCallId: "safe", toolName: "bash",
  input: { command: process.argv[7] },
});
const denied = await session.extensionRunner.emitToolCall({
  type: "tool_call", toolCallId: "denied", toolName: "bash",
  input: { command: process.argv[6] },
});
const nonBash = await session.extensionRunner.emitToolCall({
  type: "tool_call", toolCallId: "read", toolName: "read",
  input: { path: process.argv[6] },
});
const skillsResult = session.resourceLoader.getSkills();
console.log(JSON.stringify({
  errors: extensionsResult.errors,
  extensions: extensionsResult.extensions.map((item) => item.resolvedPath),
  packageSkills: skillsResult.skills
    .filter((skill) => skill.sourceInfo.baseDir === packageRoot)
    .map((skill) => skill.name),
  nativeSkills: skillsResult.skills
    .filter((skill) => skill.name === "openspec-explore")
    .map((skill) => ({
      name: skill.name,
      filePath: skill.filePath,
      scope: skill.sourceInfo.scope,
      origin: skill.sourceInfo.origin,
    })),
  skillDiagnostics: skillsResult.diagnostics,
  safe: safe ?? null,
  denied,
  nonBash: nonBash ?? null,
}));
""",
        encoding="utf-8",
    )
    loaded = subprocess.run(
        [
            "node",
            str(probe),
            str(pi_sdk),
            str(config),
            str(package),
            str(tmp_path),
            deny_nonce,
            safe_nonce,
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        env=env,
    )
    assert loaded.returncode == 0, loaded.stderr
    result = json.loads(loaded.stdout)
    assert result["errors"] == []
    assert result["extensions"] == [str(package / "plugins/escapement-pi/extensions/index.ts")]
    assert result["packageSkills"] == []
    assert result["nativeSkills"] == [
        {
            "name": "openspec-explore",
            "filePath": str(native_skill / "SKILL.md"),
            "scope": "project",
            "origin": "top-level",
        }
    ]
    assert result["skillDiagnostics"] == []
    assert result["safe"] is None
    assert result["denied"] == {"block": True, "reason": f"[deny] {deny_reason}"}
    assert result["nonBash"] is None
    assert deny_nonce not in EXTENSION.read_text(encoding="utf-8")

    pids = pid_log.read_text(encoding="utf-8").splitlines()
    assert len(pids) == 4, "two Bash events must each execute both Python gates"
    assert sorted(pids.count(pid) for pid in set(pids)) == [2, 2], (
        "each Bash event must run both gates inside one dispatcher PID"
    )
