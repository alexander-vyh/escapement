"""Drive the real rendered Pi extension through Pi's own events and see the
Serena surfaces act: a whole-file `read` of a large source file is blocked in
an onboarded project, and a submitted prompt carries Serena guidance once per
session. Nothing here imports the hooks; the only inputs are Pi-shaped events.
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


@pytest.fixture
def onboarded_project(tmp_path) -> Path:
    project = tmp_path / "project"
    (project / ".git").mkdir(parents=True)
    memories = project / ".serena" / "memories"
    memories.mkdir(parents=True)
    (memories / "architecture.md").write_text("notes", encoding="utf-8")
    (project / "service.py").write_text(
        "".join(f"def handler_{i}(value):\n    return value + {i}\n\n" for i in range(600)),
        encoding="utf-8",
    )
    return project


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


def read_call(project: Path, **extra) -> dict:
    return {
        "event": "tool_call",
        "cwd": str(project),
        "sessionId": str(uuid.uuid4()),
        "payload": {
            "type": "tool_call",
            "toolCallId": "probe",
            "toolName": "read",
            "input": {"path": str(project / "service.py"), **extra},
        },
    }


def prompt_call(project: Path, session_id: str) -> dict:
    return {
        "event": "before_agent_start",
        "cwd": str(project),
        "sessionId": session_id,
        "payload": {"prompt": "fix the handler", "systemPrompt": "BASE PROMPT"},
    }


def test_pi_read_of_large_source_is_blocked(plugin, onboarded_project):
    [result] = run(plugin, [read_call(onboarded_project)])

    assert result is not None and result["block"] is True
    assert "service.py" in result["reason"]
    assert "find_symbol" in result["reason"]


def test_pi_ranged_read_is_not_blocked(plugin, onboarded_project):
    [result] = run(plugin, [read_call(onboarded_project, offset=1, limit=40)])

    assert result is None


def test_pi_prompt_context_carries_serena_guidance_once_per_session(plugin, onboarded_project):
    session = str(uuid.uuid4())
    first, second, other = run(
        plugin,
        [
            prompt_call(onboarded_project, session),
            prompt_call(onboarded_project, session),
            prompt_call(onboarded_project, str(uuid.uuid4())),
        ],
    )

    assert first["systemPrompt"].startswith("BASE PROMPT")
    # The Pi instructions still ride along with the added context.
    assert (PI_ROOT / "PI.md").read_text(encoding="utf-8").strip()[:200] in first["systemPrompt"]
    assert "find_symbol" in first["systemPrompt"]
    assert "find_symbol" not in second["systemPrompt"], "guidance must not repeat within a session"
    assert "find_symbol" in other["systemPrompt"], "a new session gets the guidance again"


def test_pi_prompt_outside_a_code_project_adds_no_guidance(plugin, tmp_path):
    [result] = run(plugin, [prompt_call(tmp_path, str(uuid.uuid4()))])

    assert "find_symbol" not in result["systemPrompt"]
