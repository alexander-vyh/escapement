"""Drive the RENDERED Pi extension the way Pi does, with Pi-shaped events.

The extension is imported from a copy of plugins/escapement-pi -- the tree the
Pi package ships -- so its relative import of ./payloads.ts, the gate
inventory and every vendored hook are the installed ones. The Pi API it is
handed records what the extension sends back (steer notices, follow-up user
messages), and each event gets a context with Pi's sessionManager, whose
branch is the session the extension writes out as a Claude transcript.
Nothing here imports a hook: the only inputs are Pi events.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PI_ROOT = ROOT / "plugins" / "escapement-pi"

PROBE = """
const fs = await import("node:fs/promises");
const { default: extension } = await import(process.argv[2]);
const handlers = new Map();
const sent = [];
extension({
  on(event, handler) { handlers.set(event, handler); },
  sendMessage(message, options) { sent.push({ kind: "message", text: String(message.content), options }); },
  sendUserMessage(content, options) { sent.push({ kind: "user", text: String(content), options }); },
});
const results = [];
for (const call of JSON.parse(process.argv[3])) {
  // A message is wrapped as Pi's session entry; an entry that is not a message
  // (an omp custom_message notice) is already one.
  const branch = (call.branch ?? []).map((item) => (item.type ? item : { type: "message", message: item }));
  let aborts = 0;
  const context = {
    cwd: call.cwd,
    signal: new AbortController().signal,
    abort() { aborts += 1; },
    sessionManager: {
      getSessionId() { return call.sessionId; },
      getBranch() { return branch; },
      getHeader() { return call.header; },
    },
    ui: { notify() {} },
  };
  const before = sent.length;
  const handler = handlers.get(call.event);
  // A pre-input-event extension must fail the release oracle on admission,
  // not because this carrier cannot dispatch an absent optional event.
  if (!handler && call.event !== "input") throw new Error(`No handler for ${call.event}`);
  const result = (handler ? await handler(call.payload, context) : null) ?? null;
  const outcome = { result, sent: sent.slice(before) };
  if (call.observeAbort) outcome.aborts = aborts;
  // Opt-in executor substitutes have filesystem effects only after admission.
  // Never eval/exec submitted programs (including the recorded hash inventory).
  if (call.executor && !result?.block && aborts === 0) {
    const executor = call.executor;
    if (executor.kind === "witness") {
      await fs.writeFile(executor.path, executor.content, "utf8");
      outcome.executed = true;
    } else if (executor.kind === "read") {
      const text = await fs.readFile(executor.path, "utf8");
      const lines = text.split("\\n");
      outcome.read = executor.start
        ? lines.slice(executor.start - 1, executor.end).join("\\n")
        : text;
    } else if (executor.kind === "write") {
      await fs.writeFile(executor.path, executor.content, "utf8");
      outcome.executed = true;
    } else if (executor.kind === "replace") {
      const text = await fs.readFile(executor.path, "utf8");
      if (!text.includes(executor.before)) throw new Error("Existing-file fixture target missing");
      await fs.writeFile(executor.path, text.replace(executor.before, executor.after), "utf8");
      outcome.executed = true;
    } else {
      throw new Error(`Unknown fixture executor ${executor.kind}`);
    }
  }
  results.push(outcome);
}
console.log(JSON.stringify(results));
"""


def rendered_plugin(tmp_path_factory) -> Path:
    """A copy of the rendered Pi package, as Pi would install it."""
    target = tmp_path_factory.mktemp("pi") / "escapement-pi"
    shutil.copytree(PI_ROOT, target)
    (target.parent / "probe.mjs").write_text(PROBE, encoding="utf-8")
    return target


def pi_env(tmp_path: Path) -> dict[str, str]:
    """The test's own harness and signal state, and no inherited agent identity:
    a test run inside a Claude or Codex session must not borrow its state.
    The local judge points at a closed port, so a gate that asks it takes its
    deterministic path at once."""
    state = tmp_path / "harness-state"
    state.mkdir(exist_ok=True)
    (tmp_path / "home").mkdir(exist_ok=True)
    env = {
        key: value for key, value in os.environ.items()
        if not key.startswith(("CLAUDE_", "CODEX_", "ESCAPEMENT_", "BEADS_"))
    }
    env.update({
        "HARNESS_ROOT": str(state),
        "CONTINUATION_HARNESS_HOME": str(state),
        "GATE_SIGNAL_FALLBACK_DIR": str(state),
        "HOME": str(tmp_path / "home"),
        "ESCAPEMENT_LOCAL_JUDGE_BASE_URL": "http://127.0.0.1:9/v1",
        "ESCAPEMENT_LOCAL_JUDGE_TIMEOUT": "1",
    })
    return env


def run(plugin: Path, calls: list[dict], env: dict[str, str]) -> list[dict]:
    completed = subprocess.run(
        [
            "node",
            "--experimental-strip-types",
            str(plugin.parent / "probe.mjs"),
            (plugin / "extensions" / "index.ts").as_uri(),
            json.dumps(calls),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


def git_repo(path: Path, files: dict[str, str]) -> Path:
    """A committed repository holding `files`."""
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.email", "pi@example.test")
    git(path, "config", "user.name", "Pi Test")
    for name, text in files.items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "init")
    return path


class Session:
    """Pi events for one session, in the shapes Pi emits them."""

    def __init__(self, cwd: Path, parent_session: str | None = None) -> None:
        self.cwd = str(cwd)
        self.id = str(uuid.uuid4())
        self.branch: list[dict] = []
        self._calls = 0
        # Pi's session header; a delegated worker's names its parent's file.
        self.header = {"type": "session", "version": 3, "id": self.id, "cwd": self.cwd}
        if parent_session:
            self.header["parentSession"] = parent_session

    def _event(self, event: str, payload: dict) -> dict:
        return {
            "event": event, "cwd": self.cwd, "sessionId": self.id, "header": self.header,
            "branch": list(self.branch), "payload": payload,
        }

    def user(self, text: str) -> None:
        self.branch.append({"role": "user", "content": text, "timestamp": 1})

    def notice(self, custom_type: str, text: str) -> None:
        """A custom message entry, as omp appends an `async-result` delivery."""
        self.branch.append({
            "type": "custom_message", "customType": custom_type, "content": text,
            "display": True, "timestamp": "2026-10-07T23:20:42.047Z",
        })

    def irc(self, sender: str, text: str, from_parent: bool) -> None:
        """An omp IRC delivery, as the session file records it: a custom_message
        entry, not a user message; `fromParent` marks the sender as this
        session's parent."""
        details = {"id": uuid.uuid4().hex[:16], "from": sender, "message": text}
        if from_parent:
            details["fromParent"] = True
        self.branch.append({
            "type": "custom_message",
            "customType": "irc:incoming",
            "content": f"<irc>\nIncoming IRC message from agent `{sender}`:\n\n{text}\n</irc>",
            "display": True,
            "details": details,
            "attribution": "agent",
            "timestamp": 1791415164493,  # omp stamps IRC with Date.now()
        })

    def say(self, text: str) -> dict:
        message = {"role": "assistant", "content": [{"type": "text", "text": text}], "stopReason": "stop", "timestamp": 2}
        self.branch.append(message)
        return message

    def tool_call(self, tool: str, arguments: dict) -> dict:
        self._calls += 1
        call_id = f"call-{self._calls}"
        self.branch.append({
            "role": "assistant",
            "content": [{"type": "toolCall", "id": call_id, "name": tool, "arguments": arguments}],
            "stopReason": "toolUse",
            "timestamp": 2,
        })
        return self._event("tool_call", {"type": "tool_call", "toolCallId": call_id, "toolName": tool, "input": arguments})

    def tool_result(self, tool: str, arguments: dict, text: str = "ok") -> dict:
        call_id = f"call-{self._calls}"
        content = [{"type": "text", "text": text}]
        event = self._event("tool_result", {
            "type": "tool_result", "toolCallId": call_id, "toolName": tool,
            "input": arguments, "content": content, "isError": False,
        })
        self.branch.append({"role": "toolResult", "toolCallId": call_id, "toolName": tool, "content": content, "isError": False, "timestamp": 3})
        return event

    def agent_end(self) -> dict:
        return self._event("agent_end", {"type": "agent_end", "messages": list(self.branch)})

    def prompt(self, text: str) -> dict:
        return self._event("before_agent_start", {"type": "before_agent_start", "prompt": text, "systemPrompt": "BASE PROMPT"})

    def start(self) -> dict:
        return self._event("session_start", {"type": "session_start", "reason": "startup"})


def appended_text(result: dict) -> str:
    """What a tool_result handler appended to the result the model reads."""
    content = (result or {}).get("content") or []
    return "\n".join(block.get("text", "") for block in content[1:])


def notices(outcome: dict) -> str:
    return "\n".join(item["text"] for item in outcome["sent"] if item["kind"] == "message")


def follow_ups(outcome: dict) -> list[dict]:
    return [item for item in outcome["sent"] if item["kind"] == "user"]
