"""Codex agent dispatch: enforce_named_agents, review_gate, context_burn_detector.

Business outcome
----------------
On Codex, an unnamed subagent spawn is stopped with the fix in hand, a task
close with no review behind it tells the agent so, and a main thread that reads
source file after source file is nudged to hand the research to a subagent.

Independent source of truth
---------------------------
Payloads captured from codex-cli 0.156.1
(fixtures/codex_agent_mcp_stop_payloads.json):
  - the spawn is PreToolUse `collaborationspawn_agent` with `{task_name, message}`
    (message encrypted); anchored matchers `Agent` and `spawn_agent` did not
    fire on it and `(collaboration)?spawn_agent` did;
  - a tool call inside a subagent carries `agent_id`;
  - a deny on the spawn blocked it (no SubagentStart), and plain
    additionalContext reached the model while an `ask` was dropped.
Hooks run as processes; Bash gates run through the real Codex dispatcher, the
way the plugin registers them.

Rejects
-------
- a gate keyed on Claude's `Agent` tool name, which never fires on Codex;
- a review nudge sent as `ask` (inert on Codex);
- counting a subagent's reads against the main thread, or never resetting.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
HOOKS = ROOT / "claude" / "hooks"
DISPATCHER = HOOKS / "codex_pretool_dispatch.py"
MANIFEST = json.loads((ROOT / "agent-surfaces" / "manifest.json").read_text())
_PAYLOADS = json.loads(
    (Path(__file__).parent / "fixtures" / "codex_agent_mcp_stop_payloads.json").read_text()
)["payloads"]
SPAWN = _PAYLOADS["spawn_agent_pretooluse"]
MAIN_BASH = _PAYLOADS["main_bash_pretooluse"]
SUB_BASH = _PAYLOADS["subagent_bash_pretooluse"]
DISPATCH_GATES = ("enforce_named_agents", "review_gate", "context_burn_detector")


@pytest.fixture
def session(tmp_path):
    session_id = f"codex-fixture-{uuid.uuid4()}"
    yield session_id
    for leftover in (
        Path("/tmp/claude-review-gate") / f"{session_id}.json",
        Path(f"/tmp/context_burn_{session_id}.json"),
    ):
        leftover.unlink(missing_ok=True)


def _env(tmp_path: Path) -> dict[str, str]:
    env = {
        k: v for k, v in os.environ.items()
        if not k.startswith("CLAUDE_") and k not in {"ESCAPEMENT_HOST", "BEADS_DIR", "CONTEXT_BURN_THRESHOLD"}
    }
    env.update(HOME=str(tmp_path), GATE_SIGNAL_FALLBACK_DIR=str(tmp_path / "signal"))
    return env


def _parse(result: subprocess.CompletedProcess) -> dict | None:
    assert result.returncode == 0, f"Codex fails a hook that exits non-zero: {result.stderr}"
    out = result.stdout.strip()
    return json.loads(out) if out else None


def _hook(gate: str, payload: dict, tmp_path: Path) -> dict | None:
    """One gate registered as its own Codex command (the spawn matcher)."""
    return _parse(subprocess.run(
        [sys.executable, "-B", str(HOOKS / f"{gate}.py")],
        input=json.dumps({**payload, "cwd": str(tmp_path)}),
        cwd=tmp_path, env=_env(tmp_path), capture_output=True, text=True, timeout=30,
    ))


def _bash(gate: str, base: dict, command: str, session_id: str, tmp_path: Path) -> dict:
    """A Codex Bash call through the dispatcher, as the plugin registers Bash gates."""
    payload = {
        **base, "session_id": session_id, "cwd": str(tmp_path),
        "tool_input": {"command": command},
    }
    out = _parse(subprocess.run(
        [sys.executable, "-B", str(DISPATCHER), "--gate", f"claude/hooks/{gate}.py", "--gate-timeout", "5"],
        input=json.dumps(payload),
        cwd=tmp_path, env=_env(tmp_path), capture_output=True, text=True, timeout=30,
    ))
    return (out or {}).get("hookSpecificOutput", {})


def _spawn(task_name: str | None, session_id: str) -> dict:
    tool_input = {k: v for k, v in SPAWN["tool_input"].items() if k != "task_name"}
    if task_name is not None:
        tool_input["task_name"] = task_name
    return {**SPAWN, "session_id": session_id, "tool_input": tool_input}


# --- registration ----------------------------------------------------------


def test_codex_spawn_matcher_fires_on_the_captured_tool_name():
    """Codex anchors matchers: the registered one must fully match the captured name."""
    for hook in MANIFEST["hooks"]:
        if hook["id"] not in DISPATCH_GATES:
            continue
        codex = hook["hosts"]["codex"]
        assert codex["status"] == "ready", hook["id"]
        spawn_matchers = [e["matcher"] for e in codex["events"] if e["matcher"] != "Bash"]
        assert spawn_matchers, f"{hook['id']} has no Codex spawn registration"
        for matcher in spawn_matchers:
            assert re.fullmatch(matcher, SPAWN["tool_name"]), (hook["id"], matcher)
            assert re.fullmatch(matcher, "spawn_agent"), "the older tool name must still match"
            assert not re.fullmatch(matcher, "collaborationwait_agent")


# --- enforce_named_agents --------------------------------------------------


def test_codex_unnamed_spawn_is_denied_with_the_repair(tmp_path, session):
    out = _hook("enforce_named_agents", _spawn(None, session), tmp_path)
    decision = out["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    assert "task_name" in decision["permissionDecisionReason"]
    assert "SendMessage" not in decision["permissionDecisionReason"], "Claude wording on Codex"


def test_codex_named_spawn_is_allowed(tmp_path, session):
    assert _hook("enforce_named_agents", _spawn("readme", session), tmp_path) is None


def test_codex_agent_type_alone_names_the_spawn(tmp_path, session):
    payload = _spawn(None, session)
    payload["tool_input"] = {**payload["tool_input"], "agent_type": "explorer"}
    assert _hook("enforce_named_agents", payload, tmp_path) is None


# --- review_gate -----------------------------------------------------------


def test_codex_close_without_reviewer_reaches_the_model_as_context(tmp_path, session):
    out = _bash("review_gate", MAIN_BASH, "bd close proj-12", session, tmp_path)
    assert "permissionDecision" not in out, "ask is inert on Codex; the nudge must be context"
    assert "No review agent" in out["additionalContext"]
    assert "spawn_agent" in out["additionalContext"]


def test_codex_reviewer_spawn_satisfies_the_close(tmp_path, session):
    assert _hook("review_gate", _spawn("readme", session), tmp_path) is None
    still_unreviewed = _bash("review_gate", MAIN_BASH, "bd close proj-12", session, tmp_path)
    assert "No review agent" in still_unreviewed.get("additionalContext", "")

    assert _hook("review_gate", _spawn("test_quality_reviewer", session), tmp_path) is None
    reviewed = _bash("review_gate", MAIN_BASH, "bd close proj-12", session, tmp_path)
    assert "No review agent" not in reviewed.get("additionalContext", "")


# --- context_burn_detector -------------------------------------------------


def _read_source(base: dict, session: str, tmp_path: Path) -> str:
    return _bash("context_burn_detector", base, "cat src/billing.py", session, tmp_path).get(
        "additionalContext", ""
    )


def test_codex_full_source_reads_cross_the_threshold_once(tmp_path, session):
    assert _read_source(MAIN_BASH, session, tmp_path) == ""
    nudge = _read_source(MAIN_BASH, session, tmp_path)
    assert "Context-burn threshold crossed" in nudge
    assert "spawn_agent" in nudge and "TeamCreate" not in nudge
    assert _read_source(MAIN_BASH, session, tmp_path) == "", "the nudge fires once per crossing"


def test_codex_spawn_resets_the_count(tmp_path, session):
    _read_source(MAIN_BASH, session, tmp_path)
    assert "threshold" in _read_source(MAIN_BASH, session, tmp_path)
    assert _hook("context_burn_detector", _spawn("explorer", session), tmp_path) is None
    assert _read_source(MAIN_BASH, session, tmp_path) == ""
    assert "threshold" in _read_source(MAIN_BASH, session, tmp_path)


def test_codex_subagent_reads_do_not_count(tmp_path, session):
    for _ in range(3):
        assert _read_source(SUB_BASH, session, tmp_path) == ""
    assert _read_source(MAIN_BASH, session, tmp_path) == "", "subagent reads leaked into the count"


def test_codex_search_and_ranged_reads_stay_cheap(tmp_path, session):
    for command in ("rg total src", "sed -n '1,80p' src/billing.py", "ls src"):
        _bash("context_burn_detector", MAIN_BASH, command, session, tmp_path)
    assert _read_source(MAIN_BASH, session, tmp_path) == ""
