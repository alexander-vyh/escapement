"""A gate must see the directory the command runs in, through the real bridge.

Business outcome
----------------
Gates decide against a repository. If the payload names the session's
directory while the command operates on another checkout, the decision is
about the wrong tree: on 2026-09-18 a branch push in one repository was held
up by an advisory reporting uncommitted test edits in a different one.

Independent source of truth
---------------------------
The `cwd` a gate actually receives on stdin, captured by a real gate running
under the real extension loaded in node, and under the real dispatcher. Both
layers are exercised: the bridge forwards what the call declared, the
dispatcher resolves a leading `cd`.

Invalid solution classes this suite rejects
-------------------------------------------
- forwarding the session directory when the call named its own
- resolving a `cd` inside the bridge (the thin-bridge contract forbids the
  extension reading command text; the dispatcher owns that)
- inventing a directory that does not exist
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

PROBE = """
const { default: extension } = await import(process.argv[2]);
const handlers = new Map();
extension({ on(event, handler) { handlers.set(event, handler); }, sendMessage() {} });
const call = JSON.parse(process.argv[4]);
await handlers.get("tool_call")(
  { type: "tool_call", toolCallId: "probe", toolName: "bash", input: call },
  {
    cwd: process.argv[3],
    signal: new AbortController().signal,
    sessionManager: { getSessionId: () => "cwd-probe-session" },
  },
);
console.log("done");
"""

ECHO_GATE = """#!/usr/bin/env python3
import json, os, sys
payload = json.load(sys.stdin)
with open(os.environ["CWD_PROBE_OUT"], "a", encoding="utf-8") as handle:
    handle.write(json.dumps({"cwd": payload.get("cwd")}) + "\\n")
"""


@pytest.fixture
def plugin(tmp_path: Path) -> Path:
    target = tmp_path / "escapement-pi"
    shutil.copytree(PI_ROOT, target)
    gate = target / "claude" / "hooks" / "cwd_probe_gate.py"
    gate.write_text(ECHO_GATE, encoding="utf-8")
    inventory = json.loads((target / "gates.json").read_text(encoding="utf-8"))
    inventory["gates"] = [
        {"id": "cwd_probe_gate", "source": "claude/hooks/cwd_probe_gate.py", "timeout_seconds": 10}
    ]
    inventory["file_gates"] = []
    (target / "gates.json").write_text(json.dumps(inventory), encoding="utf-8")
    return target


def observed_cwd(plugin: Path, tmp_path: Path, session_cwd: Path, call: dict) -> str | None:
    out = tmp_path / "payloads.jsonl"
    out.unlink(missing_ok=True)
    probe = tmp_path / "probe.mjs"
    probe.write_text(PROBE, encoding="utf-8")
    env = dict(os.environ)
    env["CWD_PROBE_OUT"] = str(out)
    completed = subprocess.run(
        [
            "node",
            "--experimental-strip-types",
            str(probe),
            (plugin / "extensions" / "index.ts").as_uri(),
            str(session_cwd),
            json.dumps(call),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=90,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
    if not out.is_file():
        return None
    lines = [line for line in out.read_text(encoding="utf-8").splitlines() if line]
    assert lines, "the probe gate never ran"
    return json.loads(lines[-1])["cwd"]


@pytest.fixture
def repos(tmp_path: Path) -> tuple[Path, Path]:
    session = tmp_path / "session-repo"
    other = tmp_path / "other-repo"
    session.mkdir()
    other.mkdir()
    return session, other


def test_a_call_naming_its_own_directory_is_judged_there(plugin, tmp_path, repos):
    session, other = repos
    seen = observed_cwd(
        plugin, tmp_path, session, {"command": "git push", "cwd": str(other)}
    )
    assert seen == str(other.resolve())


def test_a_command_that_opens_with_cd_is_judged_in_that_directory(plugin, tmp_path, repos):
    """The bridge forwards; the dispatcher resolves. Together the gate is right."""
    session, other = repos
    seen = observed_cwd(plugin, tmp_path, session, {"command": f"cd {other} && git push"})
    assert seen == str(other.resolve())


def test_an_ordinary_command_still_reports_the_session_directory(plugin, tmp_path, repos):
    session, _ = repos
    seen = observed_cwd(plugin, tmp_path, session, {"command": "git status"})
    assert seen == str(session)
