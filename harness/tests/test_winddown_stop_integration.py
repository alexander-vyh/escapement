"""Integration tests for the wind-down rung wired into stop_hook.py.

Covers the new live-gate surface: reading the last assistant message, reading the
daemon's cached verdict, and the surgical override of the `conversational` allow.
The bd work-check is injected so these never shell out.
"""
import datetime as dt
import json
import pathlib
import sys

BIN = pathlib.Path(__file__).resolve().parent.parent / "bin"
sys.path.insert(0, str(BIN))

import stop_hook as sh


def _write_transcript(tmp_path, entries):
    p = tmp_path / "t.jsonl"
    p.write_text("\n".join(json.dumps(e) for e in entries))
    return str(p)


def _asst(text, **extra):
    d = {"type": "assistant", "message": {"role": "assistant", "content": text}}
    d.update(extra)
    return d


# ---------------------------------------------------------------------------
# _read_last_assistant_message
# ---------------------------------------------------------------------------

def test_reads_last_assistant_text(tmp_path):
    tp = _write_transcript(tmp_path, [
        {"type": "user", "message": {"role": "user", "content": "do the thing"}},
        _asst("first reply"),
        _asst("want me to wrap for the night, or keep going?"),
    ])
    assert sh._read_last_assistant_message(tp) == "want me to wrap for the night, or keep going?"


def test_skips_sidechain_subagent_turns(tmp_path):
    tp = _write_transcript(tmp_path, [
        _asst("real assistant message: proceeding"),
        _asst("subagent wrap for the night offer", isSidechain=True),
    ])
    # the sidechain turn must be ignored — it's not the main assistant
    assert sh._read_last_assistant_message(tp) == "real assistant message: proceeding"


# ---------------------------------------------------------------------------
# _read_cached_winddown_verdict
# ---------------------------------------------------------------------------

def test_fresh_verdict_read(tmp_path):
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (tmp_path / "winddown_verdict.json").write_text(json.dumps({"verdict": True, "ts": now}))
    assert sh._read_cached_winddown_verdict(tmp_path) is True


def test_stale_verdict_ignored(tmp_path):
    old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    (tmp_path / "winddown_verdict.json").write_text(json.dumps({"verdict": True, "ts": old}))
    assert sh._read_cached_winddown_verdict(tmp_path) is None


def test_missing_verdict_is_none(tmp_path):
    assert sh._read_cached_winddown_verdict(tmp_path) is None


# ---------------------------------------------------------------------------
# _winddown_override — the surgical conversational-path override
# ---------------------------------------------------------------------------

def _work_remains(cwd, thread_dir=None):
    return ("block", "implicit_queue_scoped")


def _no_work(cwd, thread_dir=None):
    return ("allow", "implicit_queue_scoped_drained")


def test_override_blocks_winddown_offer_with_work(tmp_path):
    tp = _write_transcript(tmp_path, [_asst("It's late — want me to wrap for the night, or keep going?")])
    # HERMETICITY: under judge-only there is no regex pre-empt, so this offer would
    # otherwise reach the live judge at localhost:8000 (passes when the model is up,
    # fail-open-allows when it's down — an environment-dependent test). Inject the
    # verdict so the block is driven deterministically by the judge layer's seam.
    disp = sh._winddown_override(
        "conversational", tp, "/repo", tmp_path,
        work_check=_work_remains, judge=lambda t: True,
    )
    assert disp is not None
    assert "proceed" in disp.lower() and "stop" in disp.lower()  # escape path present


def test_override_skips_when_no_reversible_work(tmp_path):
    tp = _write_transcript(tmp_path, [_asst("want me to wrap for the night, or keep going?")])
    disp = sh._winddown_override("conversational", tp, "/repo", tmp_path, work_check=_no_work)
    assert disp is None  # genuinely blocked / nothing to do → legitimate stop, no nag


def test_override_skips_legit_question(tmp_path):
    tp = _write_transcript(tmp_path, [_asst("Should I use Postgres or SQLite for this service?")])
    # regex misses this (correctly) → the inline judge runs; inject it deterministically
    # (model agrees it's NOT a wind-down) so the test never touches the live model.
    disp = sh._winddown_override(
        "conversational", tp, "/repo", tmp_path,
        work_check=_work_remains, judge=lambda t: False,
    )
    assert disp is None  # not a wind-down offer → don't block


def test_override_only_applies_to_conversational_reason(tmp_path):
    tp = _write_transcript(tmp_path, [_asst("want me to wrap for the night?")])
    # a genuine terminal (user_released) must never be overridden
    disp = sh._winddown_override("user_released", tp, "/repo", tmp_path, work_check=_work_remains)
    assert disp is None
