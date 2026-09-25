"""Codex oracle for the Bash policy gates bypass_guard and cache_write_guard.

Each case runs the Bash dispatcher command the generated Codex plugin
registers, restricted to the gate under test, on a captured Codex 0.156.1 Bash
payload (see _codex_host). A deny counts only if it survives that path in the
`permissionDecision: "deny"` shape Codex honors.

bypass_guard: a commit that switches hooks off is denied with its waiver
escape; the same flag quoted inside a commit message is not.

cache_write_guard on Codex measures the session's Codex rollout (the payload's
transcript_path), where usage is a cumulative `token_count` total that can
repeat. A heavy recent hour blocks a status op and names the lightweight
runner. The controls are a session with a large history but a quiet last
hour, and a single request whose `token_count` entry repeats 20 times. Both
must pass. Summing per-entry totals, or per-entry `last_token_usage`, would
block them.
"""

from __future__ import annotations

import copy
import datetime as dt
import json

from _codex_host import CAPTURE, denial, is_allowed, isolated_env, payload, run

BASH = "pre_tool_use_bash_with_workdir"
EVENT = "PreToolUse"


def _bash(command: str, cwd, **extra) -> dict:
    return payload(BASH, tool_input={"command": command}, cwd=str(cwd), **extra)


def test_codex_bypass_guard_denies_a_no_verify_commit(tmp_path):
    output = run(EVENT, "bypass_guard.py",
                 _bash('git commit --no-verify -m "wip"', tmp_path), isolated_env(tmp_path))
    reason = denial(output)
    assert "--no-verify" in reason
    assert 'BYPASS_WAIVER="' in reason, "the denial must carry its waiver escape"


def test_codex_bypass_guard_allows_no_verify_quoted_in_a_message(tmp_path):
    output = run(EVENT, "bypass_guard.py",
                 _bash('git commit -m "explain why --no-verify is banned"', tmp_path),
                 isolated_env(tmp_path))
    assert is_allowed(output), output


def _token_count(at: dt.datetime, fed: int, cached: int, last: int) -> str:
    """A rollout line in the captured `token_count` shape, re-dated and re-sized."""
    entry = copy.deepcopy(CAPTURE["rollout_token_count_event"])
    entry["timestamp"] = at.isoformat().replace("+00:00", "Z")
    info = entry["payload"]["info"]
    info["total_token_usage"].update(input_tokens=fed, cached_input_tokens=cached)
    info["last_token_usage"].update(input_tokens=last, cached_input_tokens=0)
    return json.dumps(entry)


def _rollout(tmp_path, lines: list[str]):
    path = tmp_path / "rollout.jsonl"
    # Non-usage records sit between usage records in a real rollout.
    filler = json.dumps({"timestamp": "2026-09-25T02:33:23.073Z", "type": "response_item",
                         "payload": {"type": "custom_tool_call"}})
    path.write_text("\n".join(line for pair in zip(lines, [filler] * len(lines)) for line in pair) + "\n")
    return path


def test_codex_cache_write_guard_denies_a_status_op_in_a_heavy_session(tmp_path):
    now = dt.datetime.now(dt.timezone.utc)
    rollout = _rollout(tmp_path, [
        _token_count(now - dt.timedelta(hours=3), 1_000_000, 900_000, 50_000),
        # 500k of uncached input written in the last hour: a heavy context.
        _token_count(now - dt.timedelta(minutes=20), 1_900_000, 1_300_000, 400_000),
    ])
    output = run(EVENT, "cache_write_guard.py",
                 _bash("bd show escapement-l4fv", tmp_path, transcript_path=str(rollout)),
                 isolated_env(tmp_path))
    reason = denial(output)
    assert "500k" in reason, reason
    assert "codex exec 'bd show escapement-l4fv'" in reason, "must name the Codex lightweight runner"
    assert "cache-guard-waiver:" in reason, "must name the inline waiver escape"


def test_codex_cache_write_guard_allows_the_same_op_after_a_quiet_hour(tmp_path):
    now = dt.datetime.now(dt.timezone.utc)
    history = _token_count(now - dt.timedelta(hours=3), 5_000_000, 1_000_000, 90_000)
    # One request in the last hour, 30k of new context, logged 20 times over.
    repeated = [_token_count(now - dt.timedelta(minutes=10), 5_050_000, 1_020_000, 30_000)] * 20
    rollout = _rollout(tmp_path, [history, *repeated])
    output = run(EVENT, "cache_write_guard.py",
                 _bash("bd show escapement-l4fv", tmp_path, transcript_path=str(rollout)),
                 isolated_env(tmp_path))
    assert is_allowed(output), output
