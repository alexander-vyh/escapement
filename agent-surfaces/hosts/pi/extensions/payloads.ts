// Pi events translated into the Claude-shaped payloads Escapement's hooks
// already read. Host plumbing only: nothing here decides anything about a
// call; the hooks behind the dispatcher do.
import { randomUUID } from "node:crypto";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

export type ClaudeToolCall = { tool_name: string; tool_input: Record<string, unknown> };

// A path that opens with a URI scheme names no file on disk (see
// claudeToolCall); the scheme grammar is RFC 3986's.
const URI_SCHEME = /^[a-z][a-z0-9+.-]*:\/\//i;

// Pi's own tools, plus the two MCP tools pi-mcp-adapter itself adds. The
// adapter refuses a direct tool whose name collides with a built-in, so any
// other tool name is an extension's (see claudeToolCall).
const PI_OWN_TOOLS: Record<string, true> = {
  bash: true, read: true, write: true, edit: true, grep: true, find: true, ls: true,
  subagent: true, mcp: true, mcpScript: true,
};

// Pi supplies no conversation identifier, and event.toolCallId is unique per
// call — keying ask-once gate dedup on it made every prompt fire forever
// (escapement-kdrc). A per-load id is stable for this extension instance,
// which is the lifetime those gates dedup over. If one process hosts several
// conversations, they share the id: the worst case suppresses a repeat NUDGE
// across conversations, never a deny, and the inline waiver remains.
const SESSION_ID = randomUUID();

// A per-tool-call id is NOT a session id. Any gate that dedupes an advisory
// prompt per session keys on whatever this returns; handing it `event.toolCallId`
// makes every call look like a fresh session, so a once-per-session prompt
// re-fires on every command until the reader learns to dismiss it. Pi exposes
// the real one via ctx.sessionManager.getSessionId().
export function sessionIdOf(context: unknown): string {
  if (!context || typeof context !== "object") return "";
  const manager = "sessionManager" in context ? context.sessionManager : undefined;
  if (manager && typeof manager === "object" && "getSessionId" in manager) {
    const getSessionId = manager.getSessionId;
    if (typeof getSessionId === "function") {
      const resolved = getSessionId.call(manager);
      if (typeof resolved === "string" && resolved.length > 0) return resolved;
    }
  }
  if ("sessionId" in context) {
    const direct = context.sessionId;
    if (typeof direct === "string" && direct.length > 0) return direct;
  }
  // Nothing host-provided: fall back to the per-load id, which is stable for
  // this instance's lifetime. Never a per-call value — that is what silently
  // defeated the dedup in the first place.
  return SESSION_ID;
}

// Pi's Bash tool takes a per-call working directory. Gates read `cwd` as "the
// repository this command touches", so sending the session's directory made a
// command aimed at another checkout get judged against this one. The dispatcher
// still resolves a leading `cd`; this only forwards what the call itself
// declared, without reading the command.
export function cwdOf(event: unknown, context: unknown): unknown {
  if (event && typeof event === "object" && "input" in event) {
    const input = event.input;
    if (input && typeof input === "object" && "cwd" in input) {
      const declared = input.cwd;
      if (typeof declared === "string" && declared.length > 0) return declared;
    }
  }
  if (context && typeof context === "object" && "cwd" in context) return context.cwd;
  return undefined;
}

// Pi's tools mapped onto the Claude tool payloads the gates already read, so a
// gate needs no knowledge of Pi. Shapes are captured from a live
// `pi --mode json` session and the Pi, pi-subagents and pi-mcp-adapter docs:
//   bash {command}                           -> Bash {command}
//   read {path, offset?, limit?}             -> Read {file_path, offset?, limit?}
//   write {path, content}                    -> Write {file_path, content}
//   edit {path, edits: [{oldText, newText}]} -> Edit {file_path, old_string, new_string}
//   subagent {agent, task?}                  -> Agent {name, subagent_type, description, prompt}
//   mcp {tool, server?, args?}               -> mcp__<server>__<tool> with args as input
//   <server>_<tool> {...args}                -> <server>_<tool> with args as input
//   mcpScript {code}                         -> <path> per literal path (claudeToolCalls)
// null means the call is not one this mapping can read; the caller decides
// whether that fails open.
export function claudeToolCall(toolName: unknown, input: unknown): ClaudeToolCall | null {
  const args: Record<string, unknown> =
    input && typeof input === "object" && !Array.isArray(input) ? { ...input } : {};

  if (toolName === "bash") {
    return typeof args.command === "string"
      ? { tool_name: "Bash", tool_input: { command: args.command } }
      : null;
  }

  // One child per call: pi-subagents requires `agent` (its `task` is
  // optional), and that agent is the child's identity, so it is both Claude's
  // `name` and its `subagent_type`. A management action dispatches nothing,
  // and a workflowScript's children are read by claudeToolCalls.
  if (toolName === "subagent") {
    if (args.action !== undefined || args.workflowScript !== undefined) return null;
    if (typeof args.agent !== "string" && typeof args.task !== "string") return null;
    const agent = typeof args.agent === "string" ? args.agent : "";
    const task = typeof args.task === "string" ? args.task : "";
    return {
      tool_name: "Agent",
      tool_input: { name: agent, subagent_type: agent, description: task, prompt: task },
    };
  }

  // pi-mcp-adapter's proxy tool carries every MCP call; `args` may arrive as a
  // JSON string. Search and describe calls name no tool and call nothing.
  if (toolName === "mcp") {
    if (typeof args.tool !== "string" || args.tool.length === 0) return null;
    let toolInput = args.args;
    if (typeof toolInput === "string") {
      try {
        toolInput = JSON.parse(toolInput);
      } catch {
        toolInput = {};
      }
    }
    return {
      tool_name: `mcp__${typeof args.server === "string" ? args.server : ""}__${args.tool}`,
      tool_input: toolInput && typeof toolInput === "object" && !Array.isArray(toolInput) ? { ...toolInput } : {},
    };
  }

  // Any tool that is not one of Pi's own is an extension's. pi-mcp-adapter
  // registers a server's `directTools` under their prefixed name
  // (`<server>_<tool>`) and never under a Pi built-in's. Gates already know
  // those names as Pi spells them (see _serena_tools.py), so the call keeps
  // its name. An extension tool that is not MCP maps too; no MCP gate matches it.
  if (typeof toolName === "string" && toolName.length > 0 && !Object.hasOwn(PI_OWN_TOOLS, toolName)) {
    return { tool_name: toolName, tool_input: args };
  }

  if (toolName !== "read" && toolName !== "write" && toolName !== "edit") return null;
  let path = args.path;
  if (typeof path !== "string" || path.length === 0) return null;
  // omp's file tools also take its internal URIs (xd://github, local://x.md,
  // artifact://3). Those name no file on disk, so no file gate applies to
  // them -- judged as paths they resolved to `<repo>/xd:/github` and a
  // harmless tool-device write was denied in the primary checkout. A file://
  // URI names a file and maps to its path.
  if (URI_SCHEME.test(path)) {
    if (path.slice(0, 7).toLowerCase() !== "file://") return null;
    try {
      path = fileURLToPath(path);
    } catch {
      return null;
    }
  }

  if (toolName === "read") {
    const toolInput: Record<string, unknown> = { file_path: path };
    for (const field of ["offset", "limit"]) {
      if (typeof args[field] === "number") toolInput[field] = args[field];
    }
    return { tool_name: "Read", tool_input: toolInput };
  }

  if (toolName === "write") {
    const content = args.content;
    if (typeof content !== "string") return null;
    return { tool_name: "Write", tool_input: { file_path: path, content } };
  }

  // Pi sends a LIST of edits where Claude sends one old/new pair. Joining
  // each side with "\n" keeps the projection exact rather than approximate:
  // both sides gain the same number of separators, so the joined delta
  // equals the sum of the per-edit deltas.
  const edits = args.edits;
  if (!Array.isArray(edits) || edits.length === 0) return null;
  const olds: string[] = [];
  const news: string[] = [];
  for (const entry of edits) {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) return null;
    const { oldText, newText } = entry;
    if (typeof oldText !== "string" || typeof newText !== "string") return null;
    olds.push(oldText);
    news.push(newText);
  }
  return {
    tool_name: "Edit",
    tool_input: {
      file_path: path,
      old_string: olds.join("\n"),
      new_string: news.join("\n"),
    },
  };
}

// A workflowScript launches its children as runs.run(key, {agent, task}) or
// runs.all([{key, agent, task}, ...]) inside JavaScript. Each literal `agent:`
// it names is one child dispatch, judged like a one-child call with the script
// as its prompt. A script naming no agent literally cannot be read: null.
const WORKFLOW_AGENT = /\bagent\s*:\s*(["'`])([^"'`\s]+)\1/g;

// pi-mcp-adapter's mcpScript runs JavaScript whose MCP calls are
// `tools.call("<path>", args)`, `tools.<path>(args)` or `tools["<path>"](args)`,
// the path being the prefixed tool name a direct tool has. Each literal path
// is one MCP call, mapped as the direct call to that tool would be. A path
// computed while the script runs cannot be read; a script with no literal
// path is null.
const SCRIPT_CALL =
  /\btools\s*(?:\.\s*call\s*\(\s*(["'`])([^"'`]+)\1|\[\s*(["'`])([^"'`]+)\3\s*\]\s*\(|\.\s*([A-Za-z_$][\w$]*)\s*\()/g;
const SCRIPT_API: Record<string, true> = { call: true, search: true, describe: true };

export function claudeToolCalls(toolName: unknown, input: unknown): ClaudeToolCall[] | null {
  const args: Record<string, unknown> =
    input && typeof input === "object" && !Array.isArray(input) ? { ...input } : {};
  if (toolName === "mcpScript") {
    if (typeof args.code !== "string") return null;
    const paths = [...args.code.matchAll(SCRIPT_CALL)]
      .map((match) => match[2] ?? match[4] ?? match[5])
      .filter((path): path is string => path !== undefined && !Object.hasOwn(SCRIPT_API, path));
    if (paths.length === 0) return null;
    return [...new Set(paths)].map((path) => ({ tool_name: path, tool_input: {} }));
  }
  const script = toolName === "subagent" ? args.workflowScript : undefined;
  if (typeof script !== "string") {
    const mapped = claudeToolCall(toolName, input);
    return mapped === null ? null : [mapped];
  }
  const agents = [...new Set([...script.matchAll(WORKFLOW_AGENT)].map((match) => match[2]))];
  if (agents.length === 0) return null;
  return agents.map((agent) => ({
    tool_name: "Agent",
    tool_input: { name: agent, subagent_type: agent, description: script, prompt: script },
  }));
}

// The text blocks of a Pi message, joined. Images and thinking are not speech.
export function textOf(content: unknown): string {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  const texts: string[] = [];
  for (const block of content) {
    if (block && block.type === "text" && typeof block.text === "string") texts.push(block.text);
  }
  return texts.join("\n");
}

// Pi's per-turn token usage (pi-ai `Usage`) under Claude's transcript names.
const CLAUDE_USAGE: Record<string, string> = {
  input: "input_tokens",
  output: "output_tokens",
  cacheRead: "cache_read_input_tokens",
  cacheWrite: "cache_creation_input_tokens",
};

// The session so far as a Claude transcript: one JSON line per message, in the
// shape harness/ and the hooks parse (`timestamp`, `message.role`,
// `message.content` blocks of `text`, `tool_use` {id, name, input} and
// `tool_result`, and an assistant turn's `message.usage`). Tool calls carry
// their Claude name and input, so code-touch detection sees a Pi `write` as the
// Write it is; usage carries Pi's cache writes as Claude's
// cache_creation_input_tokens, which is how a heavy session is measured. Pi-only
// roles (custom notices, `!` shell runs, summaries) are neither user nor
// assistant speech and are left out.
function claudeTranscript(messages: unknown[]): string {
  const lines: string[] = [];
  for (const message of messages) {
    if (!message || typeof message !== "object" || !("role" in message)) continue;
    const content = "content" in message ? message.content : undefined;
    const at = "timestamp" in message && typeof message.timestamp === "number"
      ? new Date(message.timestamp).toISOString()
      : undefined;
    if (message.role === "user") {
      lines.push(JSON.stringify({
        type: "user",
        timestamp: at,
        message: { role: "user", content: [{ type: "text", text: textOf(content) }] },
      }));
    } else if (message.role === "assistant" && Array.isArray(content)) {
      const blocks: Record<string, unknown>[] = [];
      for (const block of content) {
        if (block?.type === "text" && typeof block.text === "string") {
          blocks.push({ type: "text", text: block.text });
        } else if (block?.type === "toolCall") {
          const mapped = claudeToolCall(block.name, block.arguments);
          blocks.push({
            type: "tool_use",
            id: block.id,
            name: mapped?.tool_name ?? block.name,
            input: mapped?.tool_input ?? block.arguments ?? {},
          });
        }
      }
      const usage = "usage" in message && message.usage && typeof message.usage === "object"
        ? Object.fromEntries(Object.entries(message.usage)
          .filter(([name]) => Object.hasOwn(CLAUDE_USAGE, name))
          .map(([name, tokens]) => [CLAUDE_USAGE[name], tokens]))
        : undefined;
      lines.push(JSON.stringify({
        type: "assistant",
        timestamp: at,
        message: {
          role: "assistant",
          content: blocks,
          usage,
        },
      }));
    } else if (message.role === "toolResult") {
      lines.push(JSON.stringify({
        type: "user",
        timestamp: at,
        message: {
          role: "user",
          content: [{
            type: "tool_result",
            tool_use_id: "toolCallId" in message ? message.toolCallId : undefined,
            content: textOf(content),
            is_error: "isError" in message && message.isError === true,
          }],
        },
      }));
    }
  }
  return lines.length > 0 ? `${lines.join("\n")}\n` : "";
}

// One private directory per extension instance, one transcript file per
// session, rewritten before each dispatch. A failed write hands the gates no
// path, which they read as "no evidence" and fail open on.
export class TranscriptFiles {
  #dir: string | undefined;

  write(sessionId: string, messages: unknown[]): string | null {
    try {
      this.#dir ??= mkdtempSync(join(tmpdir(), "escapement-pi-"));
      const path = join(this.#dir, `${encodeURIComponent(sessionId)}.jsonl`);
      writeFileSync(path, claudeTranscript(messages), { mode: 0o600 });
      return path;
    } catch {
      return null;
    }
  }

  // The transcript holds the session's words; it outlives no session.
  remove(): void {
    if (this.#dir) rmSync(this.#dir, { recursive: true, force: true });
    this.#dir = undefined;
  }
}
