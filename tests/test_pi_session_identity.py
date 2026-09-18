"""The session id Pi hands its gates must identify the session, not the call.

Business outcome
----------------
A gate that asks a question once per session asks it once. `discovery-close-gate`
dedupes its design questions on the session id; the Pi bridge passed
`event.toolCallId`, which is unique per tool call, so every command looked like a
brand-new session and the question re-fired on each one. Observed in a live cake
session: five identical asks in twenty-five minutes, none deduped, plus one
`/tmp/discovery_close_gate_<id>.json` per call. That is the habituation failure
`claude/rules/delicate-art-of-bureaucracy.md` names — the reader learns to
dismiss the gate.

Independent source of truth
---------------------------
The payload the dispatcher actually receives on stdin, captured by a real gate
running under the real extension loaded in node. Nothing reimplements the bridge.

Invalid solution classes this suite rejects
-------------------------------------------
- a per-call id (toolCallId, a uuid, a counter) standing in for the session
- reading a session id from a source the host does not populate, so every
  session silently degrades to ""
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PI_ROOT = ROOT / "plugins" / "escapement-pi"

# Two tool calls with DIFFERENT toolCallIds inside ONE session, which is the
# shape that exposed the defect.
PROBE = """
const { default: extension } = await import(process.argv[2]);
const handlers = new Map();
extension({
  on(event, handler) { handlers.set(event, handler); },
  sendMessage() {},
});
const context = {
  cwd: process.argv[3],
  signal: new AbortController().signal,
  sessionManager: { getSessionId: () => process.argv[4] },
};
for (const toolCallId of ["call-one", "call-two"]) {
  await handlers.get("tool_call")(
    { type: "tool_call", toolCallId, toolName: "bash", input: { command: "echo probe" } },
    context,
  );
}
console.log("done");
"""

ECHO_GATE = """#!/usr/bin/env python3
import json, os, sys
payload = json.load(sys.stdin)
with open(os.environ["SESSION_PROBE_OUT"], "a", encoding="utf-8") as handle:
    handle.write(json.dumps({"session_id": payload.get("session_id")}) + "\\n")
"""


@pytest.fixture
def plugin(tmp_path: Path) -> Path:
    """A plugin copy whose only Bash gate records the payload it was handed."""
    target = tmp_path / "escapement-pi"
    shutil.copytree(PI_ROOT, target)
    gate = target / "claude" / "hooks" / "session_probe_gate.py"
    gate.write_text(ECHO_GATE, encoding="utf-8")
    inventory = json.loads((target / "gates.json").read_text(encoding="utf-8"))
    inventory["gates"] = [
        {
            "id": "session_probe_gate",
            "source": "claude/hooks/session_probe_gate.py",
            "timeout_seconds": 10,
        }
    ]
    inventory["file_gates"] = []
    (target / "gates.json").write_text(json.dumps(inventory), encoding="utf-8")
    return target


def observed_session_ids(plugin: Path, tmp_path: Path, session_id: str) -> list[str | None]:
    out = tmp_path / "payloads.jsonl"
    probe = tmp_path / "probe.mjs"
    probe.write_text(PROBE, encoding="utf-8")
    env = dict(os.environ)
    env["SESSION_PROBE_OUT"] = str(out)
    completed = subprocess.run(
        [
            "node",
            "--experimental-strip-types",
            str(probe),
            (plugin / "extensions" / "index.ts").as_uri(),
            str(tmp_path),
            session_id,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=90,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
    if not out.is_file():
        return []
    return [json.loads(line)["session_id"] for line in out.read_text(encoding="utf-8").splitlines() if line]


def test_two_calls_in_one_session_carry_the_same_session_id(plugin, tmp_path):
    """Per-session dedup is only possible if the id is per session."""
    observed = observed_session_ids(plugin, tmp_path, "session-abcdef")

    assert len(observed) == 2, f"the probe gate did not run twice: {observed}"
    assert observed == ["session-abcdef", "session-abcdef"]
    # The defect shape: the two calls' own ids must not leak through.
    assert "call-one" not in observed and "call-two" not in observed
