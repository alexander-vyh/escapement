// Pi events translated into the Claude-shaped payloads Escapement's hooks
// already read. Host plumbing only: nothing here decides anything about a
// call; the hooks behind the dispatcher do.
import { randomUUID } from "node:crypto";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
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
//   edit {input: "[path#TAG]\nPUT ..."} (omp) -> Edit per file (claudeToolCalls)
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
  const path = diskPath(args.path);
  if (path === null) return null;

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

// The file a file tool's path names, or null when it names none. omp's file
// tools also take its internal URIs (xd://github, local://x.md, artifact://3).
// Those name no file on disk, so no file gate applies to them -- judged as
// paths they resolved to `<repo>/xd:/github` and a harmless tool-device write
// was denied in the primary checkout. A file:// URI names a file. Pi and omp
// expand a leading `~` to the home directory; judged as written, `~/notes.md`
// resolved into the session's checkout.
function diskPath(path: unknown): string | null {
  if (typeof path !== "string" || path.length === 0) return null;
  if (URI_SCHEME.test(path)) {
    if (path.slice(0, 7).toLowerCase() !== "file://") return null;
    try {
      return fileURLToPath(path);
    } catch {
      return null;
    }
  }
  if (path === "~") return homedir();
  return path.startsWith("~/") ? join(homedir(), path.slice(2)) : path;
}

// omp's default edit tool (edit.mode "hashline") sends one string that may
// change several files, optionally inside `*** Begin Patch` / `*** End Patch`:
//   [src/app.py#1A2B]   a file, by path and snapshot tag
//   PUT 5.=7:           replace lines 5-7 with the `+` rows that follow
//   PUT >9:  PUT <9:    insert the rows after / before line 9
//   CUT 3.=4            delete lines 3-4
//   MV src/main.py      rename the file;  REM  delete it
// A path drops its tag and quotes as omp's own reader does
// (packages/tui/src/tools/hashline-format.ts and the edit renderer).
const HASHLINE_TAG = /#[0-9a-fA-F]{4}$/;

function hashlinePath(raw: string): string {
  const path = raw.trim().replace(HASHLINE_TAG, "");
  const quote = path[0];
  return path.length >= 2 && (quote === '"' || quote === "'") && path.endsWith(quote) ? path.slice(1, -1) : path;
}

// Each edited file is one Claude Edit, and a rename's target is another, so a
// file gate judges every file the call writes. The call names replaced lines by
// number, not text: old_string holds one empty line per line removed and
// new_string the rows added, which a gate counting lines projects exactly. An
// operation the call does not size -- a block (`N*`), or a paste of lines an
// earlier CUT captured -- counts as no change. A deletion maps to nothing, as
// Claude's `rm` reaches no file gate. omp's other edit modes (apply_patch,
// sloppy) send `*** <verb> File:` lines this reading does not cover: null.
function hashlineCalls(text: string): ClaudeToolCall[] | null {
  const files: { path: string; edited: boolean; removed: number; rows: string[]; rename?: string }[] = [];
  let file: (typeof files)[number] | undefined;
  // What the `+` rows under the current PUT are: none, an insert or sized
  // replacement, or the body of an unsized one (each row also replaces one).
  let rows: "none" | "added" | "replaced" = "none";
  for (const raw of (text.startsWith("\uFEFF") ? text.slice(1) : text).split("\n")) {
    const line = raw.endsWith("\r") ? raw.slice(0, -1) : raw;
    const header = line.trimEnd();
    if (header.startsWith("[")) {
      const path = hashlinePath(header.slice(1, header.endsWith("]") ? -1 : undefined));
      if (path.length > 0) {
        file = { path, edited: false, removed: 0, rows: [] };
        files.push(file);
        rows = "none";
        continue;
      }
    }
    const op = line.trim();
    if (op.startsWith("***") && op !== "*** Begin Patch" && op !== "*** End Patch") return null;
    if (file === undefined) continue;
    if (rows !== "none" && line.startsWith("+")) {
      file.rows.push(line.slice(1));
      if (rows === "replaced") file.removed += 1;
      continue;
    }
    rows = "none";
    const [verb, target = ""] = op.split(/\s+/);
    if (verb === "MV") file.rename = hashlinePath(op.slice(2));
    if (verb !== "PUT" && verb !== "CUT") continue;
    file.edited = true;
    const body = verb === "PUT" && target.endsWith(":");
    const spot = body ? target.slice(0, -1) : target;
    const [from, to = from] = spot.split(".=");
    const sized = spot.startsWith("<") || spot.startsWith(">") ? 0
      : from !== "" && to !== "" && Number.isInteger(Number(from)) && Number.isInteger(Number(to))
        ? Math.max(Number(to) - Number(from) + 1, 0)
        : undefined;
    if (verb === "CUT") file.removed += sized ?? 0;
    else if (body) {
      file.removed += sized ?? 0;
      rows = sized === undefined ? "replaced" : "added";
    }
  }
  const calls: ClaudeToolCall[] = [];
  for (const { path, edited, removed, rows: added, rename } of files) {
    const edit = diskPath(path);
    if (edited && edit !== null) {
      calls.push({
        tool_name: "Edit",
        tool_input: {
          file_path: edit,
          old_string: "\n".repeat(removed),
          new_string: added.map((row) => `${row}\n`).join(""),
        },
      });
    }
    const moved = rename === undefined ? null : diskPath(rename);
    if (moved !== null) calls.push({ tool_name: "Edit", tool_input: { file_path: moved, old_string: "", new_string: "" } });
  }
  return calls;
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
  if (toolName === "edit" && typeof args.input === "string") return hashlineCalls(args.input);
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

// The messages on a session branch, as Pi's own context builds them. A
// custom_message entry (omp's `async-result` delivery of a background job, an
// IRC delivery) is kept as the "custom" message it is: a host notice, not speech.
export function branchMessages(branch: unknown[]): unknown[] {
  const messages: unknown[] = [];
  for (const entry of branch) {
    if (!entry || typeof entry !== "object" || !("type" in entry)) continue;
    if (entry.type === "message" && "message" in entry) {
      messages.push(entry.message);
    } else if (entry.type === "custom_message") {
      messages.push({
        role: "custom",
        customType: "customType" in entry ? entry.customType : undefined,
        content: "content" in entry ? entry.content : undefined,
        timestamp: "timestamp" in entry ? entry.timestamp : undefined,
      });
    }
  }
  return messages;
}

// The parent session a delegated worker was spawned from, from the session
// header omp writes (`parentSession`); "" for a session nobody delegated.
export function parentSessionOf(context: unknown): string {
  if (!context || typeof context !== "object" || !("sessionManager" in context)) return "";
  const manager = context.sessionManager;
  if (!manager || typeof manager !== "object" || !("getHeader" in manager)) return "";
  const getHeader = manager.getHeader;
  if (typeof getHeader !== "function") return "";
  const header = getHeader.call(manager);
  return header && typeof header === "object" && "parentSession" in header && typeof header.parentSession === "string"
    ? header.parentSession
    : "";
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
// cache_creation_input_tokens, which is how a heavy session is measured. A
// custom notice becomes a `system` line; other Pi-only roles (`!` shell runs,
// summaries) are neither user nor assistant speech and are left out.
function claudeTranscript(messages: unknown[]): string {
  const lines: string[] = [];
  for (const message of messages) {
    if (!message || typeof message !== "object" || !("role" in message)) continue;
    const content = "content" in message ? message.content : undefined;
    const stamp = "timestamp" in message ? message.timestamp : undefined;
    const at = typeof stamp === "number" ? new Date(stamp).toISOString()
      : typeof stamp === "string" ? stamp : undefined;
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
          // One Pi call may be several Claude calls: an omp edit of two files
          // is two Edits, and both files were written.
          const mapped = claudeToolCalls(block.name, block.arguments);
          const calls = mapped?.length ? mapped : [{ tool_name: block.name, tool_input: block.arguments ?? {} }];
          for (const call of calls) {
            blocks.push({ type: "tool_use", id: block.id, name: call.tool_name, input: call.tool_input });
          }
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
    } else if (message.role === "custom") {
      // A host notice (omp's `async-result` job delivery) is neither user nor
      // assistant speech: a Claude `system` line, which speech readers skip.
      lines.push(JSON.stringify({
        type: "system",
        subtype: "customType" in message ? message.customType : undefined,
        timestamp: at,
        content: textOf(content),
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
