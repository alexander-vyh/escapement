"""Tests for cache_write_guard.py — block trivial ops in a HEAVY (bloated) session.

Load-bearing control: the SAME `bd show` / `gh pr view` must be ALLOWED in a LIGHT
session — the gate fires only at the intersection (heavy session AND lightweight op),
never on command-presence alone.
"""
import datetime as dt
import json
import pathlib
import sys

HOOKS = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HOOKS))

import cache_write_guard as g

NOW = dt.datetime(2026, 6, 4, 9, 0, 0, tzinfo=dt.timezone.utc)


# --- is_lightweight_action ------------------------------------------------

def test_named_lightweight_ops_match():
    for cmd in ("gh pr view 5", "bd show cake-1", "bd close cake-1",
                "gh pr view 5 --json state", "  bd show abc  "):
        assert g.is_lightweight_action(cmd) is True, cmd


def test_real_work_is_not_lightweight():
    for cmd in ("pytest -q", "bd create 'x'", "python build.py", "git commit -m x",
                "gh pr create", "npm test"):
        assert g.is_lightweight_action(cmd) is False, cmd


# --- recent_cache_writes (reads transcript usage) -------------------------

def _asst(ts, cache_creation):
    return {"type": "assistant", "timestamp": ts,
            "message": {"usage": {"cache_creation_input_tokens": cache_creation}}}


def test_recent_cache_writes_sums_within_window(tmp_path):
    tp = tmp_path / "t.jsonl"
    recent1 = (NOW - dt.timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
    recent2 = (NOW - dt.timedelta(minutes=30)).isoformat().replace("+00:00", "Z")
    old = (NOW - dt.timedelta(hours=3)).isoformat().replace("+00:00", "Z")
    tp.write_text("\n".join(json.dumps(e) for e in [
        _asst(recent1, 200_000), _asst(recent2, 120_000), _asst(old, 999_999),
    ]))
    total = g.recent_cache_writes(str(tp), NOW, window_seconds=3600)
    assert total == 320_000  # old entry excluded


def test_recent_cache_writes_failopen_missing_transcript():
    assert g.recent_cache_writes("/no/such/file.jsonl", NOW) == 0


# --- decide: the intersection + fail-safe ---------------------------------

def test_heavy_session_blocks_lightweight_op():
    block, reason = g.decide("bd show cake-1", cache_writes=320_000)
    assert block is True
    assert reason  # carries a reason for the signal


def test_light_session_allows_same_op():  # the fragile-impl killer
    block, _ = g.decide("bd show cake-1", cache_writes=40_000)
    assert block is False


def test_heavy_session_allows_real_work():
    block, _ = g.decide("pytest -q", cache_writes=900_000)
    assert block is False


def test_valid_waiver_allows():
    block, _ = g.decide("bd show cake-1", cache_writes=900_000,
                        has_waiver=True)
    assert block is False


# --- waiver substance -----------------------------------------------------

def test_waiver_requires_substantive_reason():
    assert g.has_waiver("bd show x  # cache-guard-waiver: need the live state inline to decide next step") is True
    assert g.has_waiver("bd show x  # cache-guard-waiver: tbd") is False  # too short
    assert g.has_waiver("bd show x") is False
