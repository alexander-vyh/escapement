"""Behavioral tests for claude/hooks/inject_timestamp.py.

Business outcome: on every prompt, on Claude, Codex and Pi, the model is given
the true current local time in a form it can convert to and from UTC.

The independent source of truth is the system clock and the TZ database,
read here through ``datetime.now().astimezone()`` under the same TZ the hook
runs with. The hook runs as a subprocess (Claude shape directly; Codex through
the command the generated hooks.json registers).

Run: python3 -m pytest claude/hooks/tests/test_inject_timestamp.py -q
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from _codex_host import assert_codex_reads, isolated_env, payload, registered_command

_HOOK = Path(__file__).resolve().parent.parent / "inject_timestamp.py"
_LINE = re.compile(
    r"^now: (?P<dow>\w{3}) (?P<date>\d{4}-\d{2}-\d{2}) (?P<hm>\d{2}:\d{2}) "
    r"(?P<abbr>\S+) \(UTC(?P<off>[+-]\d{4})\)$"
)
TOLERANCE = timedelta(seconds=90)
ZONES = ["America/Los_Angeles", "Asia/Kolkata", "UTC"]

_CLAUDE = {
    "session_id": "s-1", "transcript_path": "/dev/null", "cwd": "/tmp",
    "permission_mode": "default", "hook_event_name": "UserPromptSubmit",
    "prompt": "what day is it",
}


def _clock_under(tz: str) -> datetime:
    """The clock read independently, in zone ``tz``."""
    saved = os.environ.get("TZ")
    os.environ["TZ"] = tz
    time.tzset()
    try:
        return datetime.now().astimezone()
    finally:
        if saved is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = saved
        time.tzset()


def _run(argv: list[str], stdin: str, tz: str, env: dict | None = None) -> tuple[dict, str]:
    """Run the hook; return (parsed output, raw stdout)."""
    base = dict(env if env is not None else os.environ)
    base["TZ"] = tz
    proc = subprocess.run(argv, input=stdin, capture_output=True, text=True,
                          env=base, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout), proc.stdout


def _claude(stdin: str | None = None, tz: str = "UTC") -> tuple[dict, str]:
    return _run([sys.executable, str(_HOOK)],
                json.dumps(_CLAUDE) if stdin is None else stdin, tz)


def _context(output: dict) -> str:
    hook = output["hookSpecificOutput"]
    assert hook["hookEventName"] == "UserPromptSubmit"
    return hook["additionalContext"]


def _assert_true_local_time(line: str, tz: str, before: datetime, after: datetime) -> None:
    m = _LINE.match(line)
    assert m, line
    sign = 1 if m["off"][0] == "+" else -1
    offset = timezone(sign * timedelta(hours=int(m["off"][1:3]), minutes=int(m["off"][3:5])))
    instant = datetime.strptime(f"{m['date']} {m['hm']}", "%Y-%m-%d %H:%M").replace(tzinfo=offset)
    # The line is truncated to the minute, so the instant may trail the clock by <60s.
    assert before - TOLERANCE <= instant <= after + TOLERANCE, (line, before, after)
    # Zone label and numeric offset must be this zone's, per the TZ database.
    for reference in (before, after):
        if reference.strftime("%z") == m["off"]:
            assert reference.strftime("%Z") == m["abbr"], (line, reference)
            assert reference.strftime("%a") == m["dow"] or abs(instant - reference) <= TOLERANCE
            break
    else:
        pytest.fail(f"offset {m['off']} matches neither bracket: {line}")


def _check(call, tz: str) -> None:
    before = _clock_under(tz)
    output, _ = call(tz)
    after = _clock_under(tz)
    _assert_true_local_time(_context(output), tz, before, after)


@pytest.mark.parametrize("tz", ZONES)
def test_claude_prompt_gets_true_local_time(tz):
    _check(lambda z: _claude(tz=z), tz)


@pytest.mark.parametrize("tz", ZONES)
def test_codex_prompt_gets_true_local_time(tz, tmp_path):
    argv = registered_command("UserPromptSubmit", "inject_timestamp.py")
    data = payload("user_prompt_submit", cwd=str(tmp_path))

    def call(z):
        out, _ = _run(argv, json.dumps(data), z, isolated_env(tmp_path))
        assert_codex_reads("UserPromptSubmit", out)
        return out, ""

    _check(call, tz)


def test_zone_offsets_differ_across_zones():
    """Negative control: a hardcoded zone or UTC-as-local cannot satisfy all three."""
    lines = {tz: _context(_claude(tz=tz)[0]) for tz in ZONES}
    offsets = {tz: _LINE.match(line)["off"] for tz, line in lines.items()}
    assert offsets["Asia/Kolkata"] == "+0530"
    assert offsets["UTC"] == "+0000"
    assert offsets["America/Los_Angeles"] in ("-0700", "-0800")


def test_every_prompt_fires_not_once_per_session():
    for _ in range(3):
        output, _ = _claude()
        assert _LINE.match(_context(output))


def test_second_prompt_reflects_the_later_clock():
    """A cached/session-start time would be identical across a minute boundary."""
    first = _LINE.match(_context(_claude()[0]))
    second_before = _clock_under("UTC")
    second = _LINE.match(_context(_claude()[0]))
    stamp = datetime.strptime(f"{second['date']} {second['hm']}", "%Y-%m-%d %H:%M")
    assert abs(stamp.replace(tzinfo=timezone.utc) - second_before) <= TOLERANCE
    assert first is not None


def test_emits_additional_context_only_on_one_short_line():
    output, raw = _claude()
    assert "systemMessage" not in output, "per-turn UI noise, and Codex never shows it to the model"
    assert set(output) == {"hookSpecificOutput"}
    line = _context(output)
    assert "\n" not in line and len(line) <= 60, line
    assert raw.count("\n") <= 1


@pytest.mark.parametrize("stdin", ["", "not json {{{", "[1, 2]", "null"])
def test_garbage_stdin_still_yields_the_time(stdin):
    output, _ = _claude(stdin=stdin)
    assert _LINE.match(_context(output))
