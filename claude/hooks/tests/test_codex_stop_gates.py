"""Codex Stop: oracle_downgrade_stop and validate_no_shirking on the real payload.

Business outcome
----------------
On Codex, a turn that ends by dismissing a failure ("that's a pre-existing
failure") is sent back to work, and a turn that weakened a test surfaces the
advisory, exactly as on Claude.

Independent source of truth
---------------------------
The Stop payload captured from codex-cli 0.156.1
(fixtures/codex_agent_mcp_stop_payloads.json). It has `last_assistant_message`,
`stop_hook_active` and a rollout `transcript_path` whose format Escapement does
not parse. The hooks run as real processes, because Codex judges exit status and
stdout: a Stop hook must exit 0 with JSON (or nothing) on stdout, and
`{"decision": "block", "reason": ...}` continues the turn with the reason as
the next prompt (block contract captured in harness/tests/fixtures/codex_stop_payload.json).

Rejects
-------
- a gate that needs a Claude transcript and so silently allows every Codex stop;
- the old print-then-exit-2 contract (Codex treats a non-zero exit as failure);
- a gate that blocks an owned, clean final message;
- a missing final message passing silently as if it had been judged.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HOOKS = ROOT / "claude" / "hooks"
CODEX_PLUGIN_HOOKS = ROOT / "plugins" / "escapement" / "claude" / "hooks"
CAPTURED = json.loads(
    (Path(__file__).parent / "fixtures" / "codex_agent_mcp_stop_payloads.json").read_text()
)["payloads"]["stop"]

_STRONG = "def test_total():\n    assert total() == 42\n    assert count() == 7\n"
_WEAK = "def test_total():\n    assert total()\n"


def _env(tmp_path: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_", "ESCAPEMENT_HOST"))}
    env.update(
        GATE_SIGNAL_FALLBACK_DIR=str(tmp_path / "signal"),
        HARNESS_ROOT=str(tmp_path / "harness"),
        # Nothing listens on the discard port: the stop-solicitation judge is
        # unavailable, so the deterministic backstop decides, as it does
        # whenever the local model is down.
        ESCAPEMENT_LOCAL_JUDGE_BASE_URL="http://127.0.0.1:9/v1",
        ESCAPEMENT_LOCAL_JUDGE_TIMEOUT="1",
    )
    env.pop("BEADS_DIR", None)
    return env


def _stop(hook: Path, cwd: Path, tmp_path: Path, **overrides) -> tuple[subprocess.CompletedProcess, dict | None]:
    payload = {**CAPTURED, "cwd": str(cwd), **overrides}
    result = subprocess.run(
        [sys.executable, "-B", str(hook)],
        input=json.dumps(payload),
        cwd=cwd,
        env=_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"Codex fails a Stop hook that exits non-zero: {result.stderr}"
    out = result.stdout.strip()
    return result, (json.loads(out) if out else None)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (("init", "-q"), ("config", "user.email", "t@example.com"), ("config", "user.name", "t")):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    (repo / "tests").mkdir()
    (repo / "tests" / "test_total.py").write_text(_STRONG)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-q", "-m", "seed"], cwd=repo, check=True, capture_output=True)
    return repo


def test_captured_codex_stop_payload_carries_the_final_message():
    """The premise the Codex path rests on, pinned to the capture."""
    assert CAPTURED["hook_event_name"] == "Stop"
    assert isinstance(CAPTURED["last_assistant_message"], str)
    assert CAPTURED["stop_hook_active"] is False


# --- oracle_downgrade_stop -------------------------------------------------


def test_codex_stop_surfaces_oracle_downgrade(tmp_path, hooks_dir=HOOKS):
    repo = _repo(tmp_path)
    (repo / "tests" / "test_total.py").write_text(_WEAK)
    _, out = _stop(hooks_dir / "oracle_downgrade_stop.py", repo, tmp_path)
    assert out is not None and "tests/test_total.py" in out["systemMessage"]
    assert "decision" not in out, "the advisory must never hold the Codex turn open"


def test_codex_stop_is_silent_on_strengthened_tests(tmp_path):
    repo = _repo(tmp_path)
    (repo / "tests" / "test_total.py").write_text(_STRONG + "    assert extra() == 1\n")
    _, out = _stop(HOOKS / "oracle_downgrade_stop.py", repo, tmp_path)
    assert out is None


def test_codex_plugin_copy_surfaces_oracle_downgrade(tmp_path):
    """The copy Codex actually runs, from the installed plugin tree."""
    test_codex_stop_surfaces_oracle_downgrade(tmp_path, CODEX_PLUGIN_HOOKS)


# --- validate_no_shirking --------------------------------------------------

_SHIRK = (
    "Pushed the fix. The two failing tests in test_billing.py are a pre-existing "
    "failure and unrelated to our changes, so I left them."
)
_OWNED = "Fixed the rounding bug, reran the billing suite, and all 48 tests pass."


def test_codex_stop_blocks_shirking_final_message(tmp_path, hooks_dir=HOOKS):
    _, out = _stop(hooks_dir / "validate_no_shirking.py", tmp_path, tmp_path, last_assistant_message=_SHIRK)
    assert out is not None and out["decision"] == "block"
    assert "pre-existing" in out["reason"]
    assert "FIX THE FAILURES NOW" in out["reason"], "the continuation prompt must name the repair"


def test_codex_stop_allows_owned_final_message(tmp_path):
    _, out = _stop(HOOKS / "validate_no_shirking.py", tmp_path, tmp_path, last_assistant_message=_OWNED)
    assert out is None


def test_codex_stop_releases_the_continued_turn(tmp_path):
    """Codex re-enters Stop with stop_hook_active=true; blocking again would loop."""
    _, out = _stop(
        HOOKS / "validate_no_shirking.py", tmp_path, tmp_path,
        last_assistant_message=_SHIRK, stop_hook_active=True,
    )
    assert out is None


def test_codex_stop_without_final_message_says_it_did_not_judge(tmp_path):
    _, out = _stop(
        HOOKS / "validate_no_shirking.py", tmp_path, tmp_path,
        last_assistant_message=None, transcript_path=None,
    )
    assert out is not None and "decision" not in out
    assert "did not run" in out["systemMessage"]


def test_codex_plugin_copy_blocks_shirking_final_message(tmp_path):
    test_codex_stop_blocks_shirking_final_message(tmp_path, CODEX_PLUGIN_HOOKS)
