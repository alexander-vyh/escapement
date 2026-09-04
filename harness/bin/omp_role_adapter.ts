#!/usr/bin/env bun
/** One prompt through a sterile Oh My Pi SDK session; no completion authority. */

import path from "node:path";
import { writeSync } from "node:fs";
import {
	AgentRegistry,
	AuthStorage,
	ModelRegistry,
	SessionManager,
	Settings,
	VERSION,
	createAgentSession,
} from "@oh-my-pi/pi-coding-agent";

type Request = {
	protocol_version: 1;
	role: string;
	prompt: string;
	system_prompt: string;
	provider: string;
	model: string;
	auth_token: string;
	cwd: string;
	agent_dir: string;
};

type WireRecord =
	| { record_type: "header"; protocol_version: 2; runtime_version: string }
	| { record_type: "event"; sequence: number; elapsed_ms: number; event: unknown }
	| { record_type: "terminal"; sequence: number; wall_time_ms: number };

function exactRequest(value: unknown): Request {
	if (typeof value !== "object" || value === null || Array.isArray(value)) {
		throw new Error("request must be an object");
	}
	const record = value as Record<string, unknown>;
	const keys = [
		"agent_dir",
		"auth_token",
		"cwd",
		"model",
		"prompt",
		"protocol_version",
		"provider",
		"role",
		"system_prompt",
	];
	if (Object.keys(record).sort().join("\0") !== keys.sort().join("\0")) {
		throw new Error("request schema is invalid");
	}
	if (record.protocol_version !== 1) throw new Error("unsupported protocol version");
	for (const key of keys.filter((key) => key !== "protocol_version")) {
		if (typeof record[key] !== "string" || (record[key] as string).length === 0) {
			throw new Error(`${key} must be a non-empty string`);
		}
	}
	return record as Request;
}

function writeRecord(record: WireRecord): void {
	const line = `${JSON.stringify(record)}\n`;
	const written = writeSync(1, line);
	if (written !== Buffer.byteLength(line)) {
		throw new Error("incomplete OMP protocol write");
	}
}

const request = exactRequest(JSON.parse(await Bun.stdin.text()));
const started = performance.now();
writeRecord({
	record_type: "header",
	protocol_version: 2,
	runtime_version: VERSION,
});
const settings = Settings.isolated({
	"advisor.enabled": false,
	"retry.enabled": false,
	"retry.modelFallback": false,
	"retry.usageAwareFallback": false,
	"compaction.enabled": false,
	"compaction.idleEnabled": false,
	"memory.backend": "off",
	"autolearn.enabled": false,
	"goal.enabled": false,
	"todo.enabled": false,
	"magicKeywords.enabled": false,
	"recap.enabled": false,
	"title.refreshOnReplan": false,
	includeWorkspaceTree: false,
	"power.sleepPrevention": "off",
	"secrets.enabled": false,
});
const authStorage = await AuthStorage.create(":memory:");
authStorage.setRuntimeApiKey(request.provider, request.auth_token);
const modelRegistry = new ModelRegistry(
	authStorage,
	path.join(request.agent_dir, "models.yml"),
	{ settings },
);
const model = modelRegistry.find(request.provider, request.model);
if (!model) throw new Error("requested model is unavailable in the pinned registry");

let sequence = 0;
let resolveTerminal: (() => void) | undefined;
const terminal = new Promise<void>((resolve) => {
	resolveTerminal = resolve;
});
const { session } = await createAgentSession({
	cwd: request.cwd,
	agentDir: request.agent_dir,
	authStorage,
	modelRegistry,
	model,
	rebindModelAfterDiscovery: false,
	settings,
	sessionManager: SessionManager.inMemory(request.cwd),
	agentRegistry: new AgentRegistry(),
	systemPrompt: request.system_prompt,
	thinkingLevel: "off",
	skills: [],
	rules: [],
	contextFiles: [],
	promptTemplates: [],
	slashCommands: [],
	disableExtensionDiscovery: true,
	enableMCP: false,
	enableLsp: false,
	enableIrc: false,
	spawns: "",
	toolNames: [],
	restrictToolNames: true,
	requireYieldTool: false,
	hasUI: false,
	interactivePrompts: false,
	autoApprove: false,
	skipPythonPreflight: true,
	telemetry: {},
});
const unsubscribe = session.subscribe((event) => {
	writeRecord({
		record_type: "event",
		sequence,
		elapsed_ms: performance.now() - started,
		event,
	});
	sequence += 1;
	if (event.type === "agent_end" && event.isTerminal !== false) resolveTerminal?.();
});

try {
	const forwarded = await session.prompt(request.prompt, {
		expandPromptTemplates: false,
		synthetic: true,
		userInitiated: false,
	});
	if (!forwarded) throw new Error("prompt was handled locally instead of by the model");
	await terminal;
} finally {
	unsubscribe();
	await session.dispose();
	authStorage.close();
}

writeRecord({
	record_type: "terminal",
	sequence,
	wall_time_ms: performance.now() - started,
});
process.exit(0);
