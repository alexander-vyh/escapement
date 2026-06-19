#!/usr/bin/env python3
"""Claude Code hook: redirect trivial ops OUT of a heavy (bloated-context) session.

PreToolUse on Bash. When the current session has written a large amount to the 1h cache
recently (default >250k `cache_creation_input_tokens` in the last hour — i.e. it is
carrying a huge context) AND the next command is just a read-only status op
(`gh pr view`, `bd show`, `bd close`, …), running it inline re-pays that context cost for
nothing. The guard BLOCKS and redirects to a lightweight runner (a fresh cheap session or
a shell job). It fires ONLY at the intersection: heavy session AND lightweight op.

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


def recent_cache_writes(transcript_path: str, now: _dt.datetime, window_seconds: int = WINDOW_SECONDS) -> int:
    """Sum `usage.cache_creation_input_tokens` over assistant turns within the window.

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
    try:
        with p.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if e.get("type") != "assistant":
                    continue
                ts = _parse_ts(e.get("timestamp"))
                if ts is None:
                    continue
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=_dt.timezone.utc)
                if ts < cutoff:
                    continue
                usage = (e.get("message", {}) or {}).get("usage", {}) or {}
                val = usage.get("cache_creation_input_tokens")
                if isinstance(val, (int, float)):
                    total += int(val)
    except OSError:
        return 0
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
    "Blocked: this session has written {kw}k tokens to the 1h cache in the last hour — it "
    "is carrying a heavy context. Running `{cmd}` here re-pays that whole context cost for "
    "a trivial read-only op.\n\n"
    "Run it lightweight instead:\n"
    "  • fresh cheap session:  claude -p --model haiku '{cmd}'\n"
    "  • or just run it as a plain shell job outside this conversation\n"
    "  • or, if you genuinely need the result inline here, append a real reason:\n"
    "      {cmd}  # cache-guard-waiver: <why this must run in-session, ≥20 chars>"
)


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
    cache_writes = recent_cache_writes(
        data.get("transcript_path", ""), _dt.datetime.now(_dt.timezone.utc)
    )
    block, reason = decide(command, cache_writes, has_waiver=waiver)

    if waiver:
        _record_signal(gate_name="cache_write_guard", decision="waiver-accepted",
                       reason="inline waiver", cmd=command[:80])
        return 0
    if block:
        _record_signal(gate_name="cache_write_guard", decision="deny",
                       reason=reason, cmd=command[:80])
        return _deny(_REDIRECT.format(kw=cache_writes // 1000, cmd=command.strip()[:120]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
