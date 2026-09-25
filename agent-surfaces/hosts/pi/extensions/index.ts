import { spawn } from "node:child_process";
import { readFileSync, realpathSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, isAbsolute, relative, resolve, sep } from "node:path";
import { claudeToolCall, claudeToolCalls, cwdOf, sessionIdOf, textOf, TranscriptFiles } from "./payloads.ts";

type Handler = (event: any, context: any) => any;
type PiAPI = {
  on(event: string, handler: Handler): void;
  sendMessage(message: Record<string, unknown>, options?: Record<string, unknown>): void;
  sendUserMessage(content: string, options?: Record<string, unknown>): void;
};
type Gate = { id: string; source: string; timeout_seconds: number };
type HookOutput = {
  hookEventName: string;
  permissionDecision?: "allow" | "ask" | "deny";
  permissionDecisionReason?: string;
  additionalContext?: string;
};
type DispatcherResponse = {
  decision?: "block";
  reason?: string;
  hookSpecificOutput?: HookOutput;
  systemMessage?: string;
};
type Runtime = {
  dispatcherPath: string;
  preToolGates: Map<string, Gate[]>;
  // Gates for a tool with no list of its own: an extension's tool, which is
  // how pi-mcp-adapter's direct tools and mcpScript arrive.
  unlistedToolGates: Gate[];
  postToolGates: Map<string, Gate[]>;
  contextGates: Gate[];
  sessionGates: Gate[];
  stopGates: Gate[];
  instructions: string;
};

const pluginRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const MAX_OUTPUT_BYTES = 1_048_576;
const PERMISSION_DECISIONS: Record<string, true> = { allow: true, ask: true, deny: true };

function fail(message: string): never {
  throw new Error(message);
}

function confinedFile(relativePath: string): string {
  if (isAbsolute(relativePath) || relativePath.split(/[\\/]/).some((part) => part === "..")) {
    return fail("dispatcher path escapes the Pi package root");
  }
  const root = realpathSync(pluginRoot);
  const candidate = realpathSync(resolve(root, relativePath));
  const within = relative(root, candidate);
  if (within === ".." || within.slice(0, 3) === `..${sep}` || isAbsolute(within)) {
    return fail("dispatcher path escapes the Pi package root");
  }
  if (!statSync(candidate).isFile()) return fail("dispatcher path is not a regular file");
  return candidate;
}

function loadRuntime(): Runtime {
  const parsed = JSON.parse(readFileSync(resolve(pluginRoot, "gates.json"), "utf8"));
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    return fail("gate inventory must be an object");
  }
  if (parsed.version !== 1 || typeof parsed.dispatcher !== "string") {
    return fail("gate inventory version or dispatcher is invalid");
  }
  if (!Array.isArray(parsed.gates) || parsed.gates.length === 0) {
    return fail("gate inventory must contain gates");
  }
  const optionalGates = (value: unknown): Gate[] => (Array.isArray(value) ? value : []);
  const byTool = parsed.post_tool_gates;
  if (byTool !== undefined && (!byTool || typeof byTool !== "object" || Array.isArray(byTool))) {
    return fail("gate inventory post_tool_gates must map Pi tools to gates");
  }
  const fileGates = optionalGates(parsed.file_gates);
  // Keyed by the Pi tool each list judges; the inventory, not TypeScript,
  // decides which gates those are.
  const preToolGates = new Map<string, Gate[]>([
    ["bash", parsed.gates],
    ["write", fileGates],
    ["edit", fileGates],
    ["read", optionalGates(parsed.read_gates)],
    ["subagent", optionalGates(parsed.agent_gates)],
    ["mcp", optionalGates(parsed.mcp_gates)],
  ]);
  const unlistedToolGates = optionalGates(parsed.unlisted_tool_gates);
  const postToolGates = new Map<string, Gate[]>(
    Object.entries(byTool ?? {}).map(([tool, gates]) => [tool, optionalGates(gates)]),
  );
  const contextGates = optionalGates(parsed.context_gates);
  const sessionGates = optionalGates(parsed.session_gates);
  const stopGates = optionalGates(parsed.stop_gates);
  for (const gate of [
    ...[...preToolGates.values()].flat(),
    ...[...postToolGates.values()].flat(),
    ...unlistedToolGates,
    ...contextGates,
    ...sessionGates,
    ...stopGates,
  ]) {
    if (
      !gate || typeof gate !== "object" || Array.isArray(gate)
      || typeof gate.id !== "string" || typeof gate.source !== "string"
      || typeof gate.timeout_seconds !== "number"
      || !Number.isFinite(gate.timeout_seconds) || gate.timeout_seconds <= 0
    ) {
      return fail("gate inventory contains an invalid gate");
    }
  }
  return {
    dispatcherPath: confinedFile(parsed.dispatcher),
    preToolGates,
    unlistedToolGates,
    postToolGates,
    contextGates,
    sessionGates,
    stopGates,
    instructions: readFileSync(resolve(pluginRoot, "PI.md"), "utf8"),
  };
}

function parseDispatcherResponse(stdout: string, event: unknown): DispatcherResponse {
  const result = JSON.parse(stdout);
  if (!result || typeof result !== "object" || Array.isArray(result)) {
    return fail("dispatcher result must be an object");
  }
  const allowedTop = new Set(["decision", "reason", "hookSpecificOutput", "systemMessage"]);
  if (Object.keys(result).some((key) => !allowedTop.has(key))) {
    return fail("dispatcher result contains unknown fields");
  }
  if (result.decision !== undefined && result.decision !== "block") {
    return fail("dispatcher decision is invalid");
  }
  for (const field of ["reason", "systemMessage"]) {
    if (result[field] !== undefined && typeof result[field] !== "string") {
      return fail(`dispatcher ${field} must be a string`);
    }
  }
  const hook = result.hookSpecificOutput;
  if (hook !== undefined) {
    if (!hook || typeof hook !== "object" || Array.isArray(hook)) {
      return fail("dispatcher hookSpecificOutput must be an object");
    }
    const allowedHook = new Set([
      "hookEventName", "permissionDecision", "permissionDecisionReason", "additionalContext",
    ]);
    if (Object.keys(hook).some((key) => !allowedHook.has(key))) {
      return fail("dispatcher hookSpecificOutput contains unknown fields");
    }
    if (hook.hookEventName !== event) return fail("dispatcher hook event is invalid");
    if (hook.permissionDecision !== undefined && !Object.hasOwn(PERMISSION_DECISIONS, hook.permissionDecision)) {
      return fail("dispatcher permission decision is invalid");
    }
    for (const field of ["permissionDecisionReason", "additionalContext"]) {
      if (hook[field] !== undefined && typeof hook[field] !== "string") {
        return fail(`dispatcher ${field} must be a string`);
      }
    }
  }
  return result;
}

// `cwd` is the session's directory: hooks run where Claude runs them, in the
// project, so a relative Pi path or a hook reading its own working directory
// resolves against the repository the session is in. ESCAPEMENT_HOST lets a
// hook word its guidance for the host it runs on without sniffing payloads,
// and the session id rides in the variables hooks already key per-session
// state on, so a Pi process started from inside another agent's session does
// not file its state under that session.
function runDispatcher(
  runtime: Runtime,
  gates: Gate[],
  payload: Record<string, unknown>,
  signal?: AbortSignal,
  cwd?: unknown,
): Promise<DispatcherResponse> {
  const argv = ["-B", runtime.dispatcherPath];
  for (const gate of gates) {
    argv.push("--gate", gate.source, "--gate-timeout", String(gate.timeout_seconds));
  }
  const deadlineMs = gates.reduce(
    (total, gate) => total + (gate.timeout_seconds + 1) * 1000,
    0,
  );

  return new Promise((resolveResult, reject) => {
    const child = spawn("python3", argv, {
      cwd: typeof cwd === "string" && cwd.length > 0 ? cwd : undefined,
      env: {
        ...process.env,
        ESCAPEMENT_HOST: "pi",
        CLAUDE_CODE_SESSION_ID: String(payload.session_id),
        CLAUDE_SESSION_ID: String(payload.session_id),
      },
      stdio: ["pipe", "pipe", "pipe"],
    });
    const stdout: Buffer[] = [];
    const stderr: Buffer[] = [];
    let outputBytes = 0;
    let settled = false;
    const finish = (callback: () => void) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      signal?.removeEventListener("abort", abort);
      callback();
    };
    const abort = () => {
      child.kill("SIGKILL");
      finish(() => reject(new Error("Escapement Pi dispatcher aborted")));
    };
    const collect = (target: Buffer[], chunk: Buffer) => {
      outputBytes += chunk.length;
      if (outputBytes > MAX_OUTPUT_BYTES) {
        child.kill("SIGKILL");
        finish(() => reject(new Error("dispatcher output exceeded 1048576 bytes")));
        return;
      }
      target.push(chunk);
    };
    const timer = setTimeout(() => {
      child.kill("SIGKILL");
      finish(() => reject(new Error("Escapement Pi dispatcher timed out")));
    }, deadlineMs);
    if (signal?.aborted) abort();
    else signal?.addEventListener("abort", abort, { once: true });

    child.stdout.on("data", (chunk: Buffer) => collect(stdout, chunk));
    child.stderr.on("data", (chunk: Buffer) => collect(stderr, chunk));
    child.stdin.on("error", (error: NodeJS.ErrnoException) => {
      if (error.code !== "EPIPE") finish(() => reject(error));
    });
    child.on("error", (error) => finish(() => reject(error)));
    child.on("close", (code) => finish(() => {
      const renderedError = Buffer.concat(stderr).toString("utf8").trim();
      if (code !== 0) {
        reject(new Error(renderedError || `Escapement Pi dispatcher exited ${code}`));
        return;
      }
      try {
        resolveResult(parseDispatcherResponse(Buffer.concat(stdout).toString("utf8"), payload.hook_event_name));
      } catch (error) {
        reject(new Error(`Escapement Pi dispatcher returned invalid JSON: ${error}`));
      }
    }));
    child.stdin.end(JSON.stringify(payload));
  });
}

// A gate's non-blocking words: shown in the session and read by the model.
// `steer` reaches the model before its next call; `delivery` overrides that
// where steering would itself continue the run.
function surfaceDiagnostics(
  pi: PiAPI,
  result: DispatcherResponse,
  delivery: Record<string, unknown> = { deliverAs: "steer" },
): void {
  const messages = [result.systemMessage, result.hookSpecificOutput?.additionalContext]
    .filter((message): message is string => Boolean(message));
  if (messages.length === 0) return;
  pi.sendMessage({ customType: "escapement", content: messages.join("\n\n"), display: true }, delivery);
}

export default function escapementPi(pi: PiAPI): void {
  let runtime: Runtime | Error;
  try {
    runtime = loadRuntime();
  } catch (error) {
    runtime = error instanceof Error ? error : new Error(String(error));
  }

  // Claude hands every hook the session so far as `transcript_path`, and gates
  // read it to judge what the session did: whether it changed code, how heavy
  // its context is, what it said last. Pi keeps the session in memory, so its
  // current branch (or, without one, the finished run) is written out for each
  // dispatch.
  const transcripts = new TranscriptFiles();
  const transcriptOf = (
    context: { sessionManager?: { getBranch?: () => unknown } } | undefined,
    sessionId: string,
    run: unknown,
  ): string | null => {
    const branch = context?.sessionManager?.getBranch?.();
    return transcripts.write(sessionId, Array.isArray(branch)
      ? branch.filter((entry) => entry?.type === "message").map((entry) => entry.message)
      : Array.isArray(run) ? run : []);
  };

  // SessionStart hooks run once when Pi starts, resumes or forks a session.
  // Their additionalContext is kept and re-appended to every turn's system
  // prompt below: Pi rebuilds the system prompt per turn, so this is how the
  // context stays in force for the whole session (and survives compaction,
  // which is why PreCompact needs no Pi counterpart). Advisory: a failure is
  // reported in the prompt rather than blocking the session.
  let sessionContext: Promise<string> = Promise.resolve("");
  pi.on("session_start", (event, context) => {
    if (runtime instanceof Error || runtime.sessionGates.length === 0) return;
    const loaded = runtime;
    const sessionId = sessionIdOf(context);
    sessionContext = runDispatcher(
      loaded,
      loaded.sessionGates,
      {
        session_id: sessionId,
        transcript_path: transcriptOf(context, sessionId, []),
        cwd: context?.cwd,
        hook_event_name: "SessionStart",
        source: typeof event?.reason === "string" ? event.reason : "startup",
      },
      undefined,
      context?.cwd,
    ).then(
      (result) => {
        // Claude and Codex show a hook's systemMessage to the user; Pi's
        // counterpart is a UI notice. The dispatcher already carries it into
        // additionalContext for the model.
        if (result.systemMessage) context?.ui?.notify?.(result.systemMessage, "info");
        return result.hookSpecificOutput?.additionalContext ?? "";
      },
      (error) => `Escapement Pi session-start hooks failed: ${error}`,
    );
  });

  // Pi has no UserPromptSubmit hook; before_agent_start is the same moment
  // (prompt submitted, agent not yet running) and may extend the system
  // prompt. Context hooks get a UserPromptSubmit payload and their
  // additionalContext is appended for this turn. Prompt context is advisory,
  // so a failure is reported in the prompt rather than blocking the turn.
  pi.on("before_agent_start", async (event, context) => {
    if (runtime instanceof Error) {
      return { systemPrompt: `${event.systemPrompt}\n\nEscapement Pi configuration error: ${runtime.message}` };
    }
    const sections = [event.systemPrompt, runtime.instructions];
    const session = await sessionContext;
    if (session) sections.push(session);
    if (runtime.contextGates.length > 0) {
      const sessionId = sessionIdOf(context);
      try {
        const result = await runDispatcher(
          runtime,
          runtime.contextGates,
          {
            session_id: sessionId,
            transcript_path: transcriptOf(context, sessionId, []),
            cwd: context?.cwd,
            hook_event_name: "UserPromptSubmit",
            prompt: typeof event.prompt === "string" ? event.prompt : "",
          },
          context?.signal,
          context?.cwd,
        );
        const added = result.hookSpecificOutput?.additionalContext;
        if (added) sections.push(added);
      } catch (error) {
        sections.push(`Escapement Pi prompt-context hooks failed: ${error}`);
      }
    }
    return { systemPrompt: sections.join("\n\n") };
  });

  pi.on("tool_call", async (event, context) => {
    // Read gates steer toward cheaper navigation; they are not a safety
    // brake, so a broken install or failed dispatch never blocks a read.
    const advisory = event.toolName === "read";
    const calls = claudeToolCalls(event.toolName, event.input);
    // An unreadable payload fails OPEN: a call that cannot be parsed is not
    // evidence of a violation, and blocking on it would make every future Pi
    // tool-shape change look like a policy failure. Bash is the exception --
    // its payload is one string, so an unreadable one is not a Bash call at all.
    if (calls === null) {
      if (event.toolName !== "bash") return;
      return { block: true, reason: "Escapement received an invalid Pi Bash payload" };
    }
    if (runtime instanceof Error) {
      return advisory
        ? undefined
        : { block: true, reason: `Escapement Pi configuration error: ${runtime.message}` };
    }
    const gates = runtime.preToolGates.get(event.toolName) ?? runtime.unlistedToolGates;
    if (gates.length === 0) return;
    const sessionId = sessionIdOf(context);
    try {
      // A workflowScript maps to one call per child; the first denial wins.
      for (const mapped of calls) {
        const result = await runDispatcher(
          runtime,
          gates,
          {
            session_id: sessionId,
            transcript_path: transcriptOf(context, sessionId, []),
            cwd: cwdOf(event, context),
            hook_event_name: "PreToolUse",
            ...mapped,
          },
          context?.signal,
          context?.cwd,
        );
        surfaceDiagnostics(pi, result);
        const hook = result.hookSpecificOutput;
        if (hook?.permissionDecision === "deny" || hook?.permissionDecision === "ask") {
          return {
            block: true,
            reason: hook.permissionDecisionReason || "Escapement blocked this Pi tool call",
          };
        }
      }
    } catch (error) {
      if (advisory) return;
      return { block: true, reason: `Escapement Pi adapter error: ${error}` };
    }
  });

  // Pi's tool_result is Claude's PostToolUse, and may extend the result the
  // model reads (Pi extension docs). What a gate says -- its additionalContext,
  // or the reason of a block, which on Claude is fed back to the model -- is
  // appended to that result. The tool already ran, so a failed dispatch is
  // appended as a notice rather than failing the tool.
  pi.on("tool_result", async (event, context) => {
    if (runtime instanceof Error) return;
    const gates = runtime.postToolGates.get(event.toolName) ?? [];
    if (gates.length === 0) return;
    const mapped = claudeToolCall(event.toolName, event.input);
    if (mapped === null) return;
    const content = Array.isArray(event.content) ? event.content : [];
    const sessionId = sessionIdOf(context);
    let notes: string[];
    try {
      const result = await runDispatcher(
        runtime,
        gates,
        {
          session_id: sessionId,
          transcript_path: transcriptOf(context, sessionId, []),
          cwd: cwdOf(event, context),
          hook_event_name: "PostToolUse",
          ...mapped,
          tool_response: { content: textOf(content), is_error: Boolean(event.isError) },
        },
        context?.signal,
        context?.cwd,
      );
      notes = [result.reason, result.hookSpecificOutput?.additionalContext]
        .filter((note): note is string => Boolean(note));
    } catch (error) {
      notes = [`Escapement Pi post-tool hooks failed: ${error}`];
    }
    if (notes.length === 0) return;
    return { content: [...content, ...notes.map((text) => ({ type: "text", text }))] };
  });

  // Pi's agent_end is Claude's Stop: the run is over unless something
  // continues it. Stop gates run once per agent_end with a Claude Stop
  // payload. A block continues the run with its reason as a follow-up user
  // message -- Pi continues a run for messages queued during agent_end -- and
  // the next agent_end in that chain says stop_hook_active, so a gate can let
  // the session go instead of looping.
  let stopHookActive = false;
  pi.on("agent_end", async (event, context) => {
    if (runtime instanceof Error || runtime.stopGates.length === 0) return;
    const run = Array.isArray(event?.messages) ? event.messages : [];
    const sessionId = sessionIdOf(context);
    const lastAssistant = [...run].reverse().find((message) => message?.role === "assistant");
    let result: DispatcherResponse;
    try {
      result = await runDispatcher(
        runtime,
        runtime.stopGates,
        {
          session_id: sessionId,
          cwd: context?.cwd,
          hook_event_name: "Stop",
          stop_hook_active: stopHookActive,
          last_assistant_message: textOf(lastAssistant?.content),
          transcript_path: transcriptOf(context, sessionId, run),
        },
        undefined,
        context?.cwd,
      );
    } catch (error) {
      stopHookActive = false;
      pi.sendMessage(
        { customType: "escapement", content: `Escapement Pi stop hooks failed: ${error}`, display: true },
        { deliverAs: "nextTurn" },
      );
      return;
    }
    // An advisory at Stop is shown, not acted on: a steered message queued
    // during agent_end would itself continue the run (Pi's AgentSession), so
    // it is appended without triggering a turn. Only a block continues.
    surfaceDiagnostics(pi, result, { triggerTurn: false });
    stopHookActive = result.decision === "block";
    if (stopHookActive) {
      pi.sendUserMessage(result.reason || "Escapement stop hooks blocked this stop", { deliverAs: "followUp" });
    }
  });

  pi.on("session_shutdown", () => transcripts.remove());
}
