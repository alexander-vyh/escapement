"""Drive the real rendered Pi extension through Pi's own events and see the
design-principles reminder reach the model on every submitted prompt, in or out
of a code project. Nothing here imports the hook; the only inputs are
Pi-shaped events.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PI_ROOT = ROOT / "plugins" / "escapement-pi"

PROBE = """
const { default: extension } = await import(process.argv[2]);
const handlers = new Map();
extension({
  on(event, handler) { handlers.set(event, handler); },
  sendMessage() {},
});
const results = [];
for (const call of JSON.parse(process.argv[3])) {
  const sessionId = call.sessionId;
  const context = {
    cwd: call.cwd,
    signal: new AbortController().signal,
    sessionManager: { getSessionId() { return sessionId; } },
  };
  results.push((await handlers.get(call.event)(call.payload, context)) ?? null);
}
console.log(JSON.stringify(results));
"""


@pytest.fixture(scope="module")
def plugin(tmp_path_factory) -> Path:
    target = tmp_path_factory.mktemp("pi") / "escapement-pi"
    shutil.copytree(PI_ROOT, target)
    (target.parent / "probe.mjs").write_text(PROBE, encoding="utf-8")
    return target


def run(plugin: Path, calls: list[dict]) -> list:
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
        timeout=60,
        env=dict(os.environ),
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def prompt_call(project: Path, session_id: str) -> dict:
    return {
        "event": "before_agent_start",
        "cwd": str(project),
        "sessionId": session_id,
        "payload": {"prompt": "fix the handler", "systemPrompt": "BASE PROMPT"},
    }


def test_pi_prompt_context_carries_the_reminder_on_every_prompt(plugin, tmp_path):
    session = str(uuid.uuid4())
    results = run(plugin, [prompt_call(tmp_path, session) for _ in range(3)])

    for result in results:
        assert result["systemPrompt"].startswith("BASE PROMPT")
        for principle in ("DRY", "SOLID", "YAGNI"):
            assert principle in result["systemPrompt"]
