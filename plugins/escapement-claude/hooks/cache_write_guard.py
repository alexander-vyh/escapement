#!/usr/bin/env python3
"""PreToolUse hook: redirect trivial ops OUT of a heavy (bloated-context) session.

PreToolUse on Bash. When the current session has written a large amount of new context
into its prompt cache recently (default >250k tokens in the last hour — i.e. it is
carrying a huge context) AND the next command is just a read-only status op
(`gh pr view`, `bd show`, `bd close`, …), running it inline re-pays that context cost for
nothing. The guard BLOCKS and redirects to a lightweight runner (a fresh cheap session or
a shell job). It fires ONLY at the intersection: heavy session AND lightweight op.

The measure is read from the payload's `transcript_path`, in whichever host's format it is:
  - Claude Code transcript: `usage.cache_creation_input_tokens` on assistant turns.
  - Codex rollout: `event_msg`/`token_count` entries. OpenAI caches the prompt without a
    separate write count, so the uncached input (`input_tokens - cached_input_tokens`) is
    the new context written; `total_token_usage` is cumulative, so the window's amount is
    the growth since the last entry before the window (repeated entries count once).
  - Pi: the extension writes a Claude-shaped transcript with Pi's usage under Claude's
    names. Per turn, cache writes plus uncached input: whichever provider runs, that is
    the new context (Anthropic reports writes; OpenAI reports 0 writes and the uncached
    prompt as input).

Fail-open: if usage can't be read, ALLOW (a guard that blocks when it can't measure is
worse than the waste). Subagent-exempt. gate-design compliant: the denial names the
escape (lightweight runner / inline waiver), emits persistent signal, and validates VALUE
(actual cache-writes over threshold + actually-named lightweight op), not presence.
"""
import datetime as _dt
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _agent_dispatch import host as _host  # noqa: E402
try:
    from _gate_signal import record as _record_signal
except ImportError:  # pragma: no cover
    def _record_signal(*_a, **_k) -> None:
        return None

THRESHOLD_CACHE_WRITES = 250_000  # 1h cache-write tokens that mark a session "heavy"
WINDOW_SECONDS = 3600
_WAIVER_MIN_REASON = 20

# Read-only status ops that should never justify re-paying a huge context. The user's
# named set (gh pr view / bd show / bd close) plus close read-only cousins. Deliberately
# narrow — real work (pytest, edits, bd create, gh pr create) is NOT in scope.
_LIGHTWEIGHT = re.compile(
    r"^\s*(?:gh\s+pr\s+(?:view|checks|status)\b"
    r"|gh\s+run\s+view\b"
    r"|bd\s+(?:show|close|list|ready)\b)",
    re.IGNORECASE,
)
_WAIVER = re.compile(r"#\s*cache-guard-waiver:\s*(.+)$", re.IGNORECASE)


def is_lightweight_action(command: str) -> bool:
    return bool(command) and bool(_LIGHTWEIGHT.match(command))


def has_waiver(command: str) -> bool:
    m = _WAIVER.search(command or "")
    return bool(m) and len(m.group(1).strip()) >= _WAIVER_MIN_REASON


def _parse_ts(s):
    if not isinstance(s, str) or not s:
        return None
    try:
        return _dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _codex_fresh_input(entry: dict):
    """Cumulative uncached input of a Codex rollout `token_count` entry, else None."""
    if entry.get("type") != "event_msg":
        return None
    payload = entry.get("payload") or {}
    if not isinstance(payload, dict) or payload.get("type") != "token_count":
        return None
    total = (payload.get("info") or {}).get("total_token_usage") or {}
    fed, cached = total.get("input_tokens"), total.get("cached_input_tokens", 0)
    if not isinstance(fed, (int, float)) or not isinstance(cached, (int, float)):
        return None
    return max(int(fed) - int(cached), 0)


def recent_cache_writes(transcript_path: str, now: _dt.datetime, window_seconds: int = WINDOW_SECONDS,
                        *, uncached_input: bool = False) -> int:
    """New context tokens written to the prompt cache within the window.

    Claude transcript: the sum of `usage.cache_creation_input_tokens` over assistant turns.
    Codex rollout: the growth of cumulative uncached input across the window.
    `uncached_input` also counts each turn's `usage.input_tokens`: the Pi extension writes
    Pi's usage under Claude's names, and there a provider without explicit cache writes
    (OpenAI: cacheWrite 0, input = the uncached prompt) reports its new context as input.

    FAIL-OPEN: missing/unreadable transcript → 0 (→ below threshold → allow).
    """
    if not transcript_path:
        return 0
    p = Path(transcript_path)
    if not p.exists():
        return 0
    n = now if now.tzinfo else now.replace(tzinfo=_dt.timezone.utc)
    cutoff = n - _dt.timedelta(seconds=window_seconds)
    total = 0
    codex_before = codex_latest = None
    marker = "input_tokens" if uncached_input else "cache_creation_input_tokens"
    try:
        with p.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                # Rollouts run to hundreds of MB; only usage-bearing lines are parsed.
                if marker not in line and "token_count" not in line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(e, dict):
                    continue
                ts = _parse_ts(e.get("timestamp"))
                if ts is None:
                    continue
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=_dt.timezone.utc)
                fresh = _codex_fresh_input(e)
                if fresh is not None:
                    if ts < cutoff:
                        codex_before = fresh
                    else:
                        codex_latest = fresh
                    continue
                if e.get("type") != "assistant" or ts < cutoff:
                    continue
                usage = (e.get("message", {}) or {}).get("usage", {}) or {}
                keys = ("cache_creation_input_tokens", "input_tokens") if uncached_input else (
                    "cache_creation_input_tokens",)
                for key in keys:
                    val = usage.get(key)
                    if isinstance(val, (int, float)):
                        total += int(val)
    except OSError:
        return 0
    if codex_latest is not None:
        grown = codex_latest - (codex_before or 0)
        total += grown if grown >= 0 else codex_latest  # a reset counter restarts at 0
    return total


def decide(command: str, cache_writes: int, *, has_waiver: bool = False,
           threshold: int = THRESHOLD_CACHE_WRITES):
    """(block: bool, reason: str). Block only at the intersection, never on presence."""
    if has_waiver:
        return (False, "waiver")
    if is_lightweight_action(command) and cache_writes > threshold:
        return (True, f"lightweight op in heavy session ({cache_writes} cache writes/1h > {threshold})")
    return (False, "")


_REDIRECT = (
    "Blocked: this session has written {kw}k new tokens into its prompt cache in the last "
    "hour — it is carrying a heavy context. Running `{cmd}` here re-pays that whole context "
    "cost for a trivial read-only op.\n\n"
    "Run it lightweight instead:\n"
    "  • fresh cheap session:  {runner}\n"
    "  • or just run it as a plain shell job outside this conversation\n"
    "  • or, if you genuinely need the result inline here, append a real reason:\n"
    "      {cmd}  # cache-guard-waiver: <why this must run in-session, ≥20 chars>"
)
# The fresh session each host can start. Claude's line also names Codex's, as it did before
# hosts were told apart; Pi's print mode (`pi -p`) runs one prompt and exits.
_RUNNERS = {
    "pi": "pi -p '{cmd}'",
}
_DEFAULT_RUNNER = "claude -p --model haiku '{cmd}'  (on Codex: codex exec '{cmd}')"


def _deny(reason: str) -> int:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))
    return 0


def _is_subagent() -> bool:
    return any(os.environ.get(v) for v in (
        "CLAUDE_AGENT_NAME", "CLAUDE_AGENT_TYPE", "CLAUDE_SUBAGENT",
        "CLAUDE_TEAM_NAME", "CLAUDE_AGENT_ID",
    ))


def main() -> int:
    if _is_subagent():
        return 0
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0
    if data.get("tool_name") != "Bash":
        return 0
    tool_input = data.get("tool_input", {})
    if not isinstance(tool_input, dict):
        return 0
    command = tool_input.get("command", "")
    if not is_lightweight_action(command):
        return 0  # cheap exit: only the named ops are ever in scope

    waiver = has_waiver(command)
    host = _host(data)
    cache_writes = recent_cache_writes(
        data.get("transcript_path", ""), _dt.datetime.now(_dt.timezone.utc), uncached_input=host == "pi"
    )
    block, reason = decide(command, cache_writes, has_waiver=waiver)

    if waiver:
        _record_signal(gate_name="cache_write_guard", decision="waiver-accepted",
                       reason="inline waiver", cmd=command[:80])
        return 0
    if block:
        _record_signal(gate_name="cache_write_guard", decision="deny",
                       reason=reason, cmd=command[:80])
        cmd = command.strip()[:120]
        runner = _RUNNERS.get(host, _DEFAULT_RUNNER).format(cmd=cmd)
        return _deny(_REDIRECT.format(kw=cache_writes // 1000, cmd=cmd, runner=runner))
    return 0


if __name__ == "__main__":
    sys.exit(main())
