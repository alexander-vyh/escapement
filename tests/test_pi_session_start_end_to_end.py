"""Drive the real rendered Pi extension through Pi's session events and see
SessionStart hooks act on Pi: they run once when the session starts, and the
context they produce (Escapement's rules among it) is in force on every turn.
The only inputs are Pi-shaped events; nothing here imports the hooks.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
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
  const context = {
    cwd: call.cwd,
    signal: new AbortController().signal,
    sessionManager: { getSessionId() { return call.sessionId; } },
    ui: { notify() {} },
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


def _python_shim(tmp_path: Path, *, fail_on: str | None = None) -> tuple[Path, Path]:
    """A python3 on PATH that logs each dispatcher argv (and can fail one)."""
    log = tmp_path / "dispatches.log"
    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    fail = (
        f'case "$*" in *{fail_on}*) exit 3;; esac\n' if fail_on else ""
    )
    shim = shim_dir / "python3"
    shim.write_text(
        "#!/bin/sh\n"
        f"printf '%s\\n' \"$*\" >> {log}\n"
        f"{fail}"
        f'exec {sys.executable} "$@"\n',
        encoding="utf-8",
    )
    shim.chmod(0o755)
    return shim_dir, log


def run(plugin: Path, calls: list[dict], shim_dir: Path) -> list:
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
        timeout=120,
        env={**os.environ, "PATH": f"{shim_dir}:{os.environ['PATH']}"},
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def _session(project: Path, turns: int) -> list[dict]:
    session = str(uuid.uuid4())
    start = {
        "event": "session_start",
        "cwd": str(project),
        "sessionId": session,
        "payload": {"type": "session_start", "reason": "startup"},
    }
    turn = {
        "event": "before_agent_start",
        "cwd": str(project),
        "sessionId": session,
        "payload": {"prompt": "continue", "systemPrompt": "BASE PROMPT"},
    }
    return [start, *[turn] * turns]


def _rule_sentence(plugin: Path, name: str) -> str:
    text = (plugin / "claude" / "rules" / name).read_text(encoding="utf-8")
    return next(line for line in text.splitlines() if len(line.split()) > 6 and "<!--" not in line)


def test_pi_session_start_injects_rules_every_turn(plugin, tmp_path):
    shim_dir, _ = _python_shim(tmp_path)
    _, first, second = run(plugin, _session(tmp_path, turns=2), shim_dir)

    rule = _rule_sentence(plugin, "never-suppress.md")
    for turn in (first, second):
        prompt = turn["systemPrompt"]
        assert prompt.startswith("BASE PROMPT")
        assert rule in prompt, "session rules must stay in force on every turn"
        # continuation-harness is Claude-only; its wakeup instructions must not reach Pi.
        assert "ScheduleWakeup" not in prompt


def test_pi_session_start_runs_every_session_gate_once(plugin, tmp_path):
    shim_dir, log = _python_shim(tmp_path)
    run(plugin, _session(tmp_path, turns=3), shim_dir)

    inventory = json.loads((plugin / "gates.json").read_text(encoding="utf-8"))
    session_sources = [gate["source"] for gate in inventory["session_gates"]]
    assert "claude/hooks/inject_rules.py" in session_sources
    session_runs = [
        line for line in log.read_text(encoding="utf-8").splitlines()
        if any(source in line for source in session_sources)
    ]
    assert len(session_runs) == 1, "session gates run once per session, not per turn"
    assert all(source in session_runs[0] for source in session_sources), (
        "every session gate runs in that one dispatcher process"
    )


def test_pi_session_start_failure_is_reported_without_blocking_the_turn(plugin, tmp_path):
    shim_dir, _ = _python_shim(tmp_path, fail_on="inject_rules.py")
    _, turn = run(plugin, _session(tmp_path, turns=1), shim_dir)

    prompt = turn["systemPrompt"]
    assert prompt.startswith("BASE PROMPT")
    assert "session-start hooks failed" in prompt
