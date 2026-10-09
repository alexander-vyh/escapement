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
