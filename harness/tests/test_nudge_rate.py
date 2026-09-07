"""Oracle for the nudge-rate measurement.

This metric is the outcome oracle for the continuation harness: not "did a gate
fire" but "did a human have to type 'continue' to restart the work". If it
over-counts it will declare victory that was never won; if it under-counts it
hides the failure it exists to expose. The controls below are the point.
"""

import importlib.util
import json
import pathlib
import sys

BIN = pathlib.Path(__file__).resolve().parents[2] / "claude" / "bin"


def _load():
    spec = importlib.util.spec_from_file_location("nudge_rate", BIN / "nudge_rate.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load claude/bin/nudge_rate.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


nr = _load()


# --- what counts as a nudge -------------------------------------------------


def test_the_real_phrases_count():
    """Taken verbatim from the measured 7-day baseline."""
    for phrase in [
        "well?", "continue", "progress?", "keep fucking going",
        "still waiting?", "ok. keep going", "go", "why the fuck are you stopped",
    ]:
        assert nr.is_nudge(phrase), phrase


def test_content_bearing_prompts_are_not_nudges():
    """The metric must not reward a silent agent by counting real instructions."""
    for phrase in [
        "continue with the pacing tab",
        "why is cake not filtering out test opportunities?",
        "ok. ship it",
        "yes. task codex agents to handle those things",
        "what are the next set of beads that need doing?",
        "well, the filter is wrong",
    ]:
        assert not nr.is_nudge(phrase), phrase


def test_the_length_guard_catches_what_the_regex_cannot():
    """Load-bearing control for MAX_NUDGE_CHARS.

    Several regex branches end in `.*` ("you stopped.*", "don't stop.*"), so
    they happily match a long, content-bearing complaint. Only the length cap
    keeps those out. Raising the cap must break this test — a mutation that
    changes nothing means the guard is decoration.
    """
    real_instruction = (
        "you stopped before finishing the pacing tab migration and I need it today"
    )
    assert len(real_instruction) > nr.MAX_NUDGE_CHARS
    assert nr.NUDGE.match(real_instruction), "regex alone would accept this"
    assert not nr.is_nudge(real_instruction), "length guard must reject it"


def test_a_bare_stop_complaint_is_still_a_nudge():
    """Positive side of the same guard — short form carries no information."""
    assert nr.is_nudge("you stopped")


# --- who counts -------------------------------------------------------------


def _transcript(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in records))


def _user(ts, text, source="typed", **kw):
    row = {
        "type": "user", "timestamp": ts, "sessionId": "s1", "cwd": "/repo",
        "promptSource": source, "message": {"role": "user", "content": text},
    }
    row.update(kw)
    return row


def test_only_typed_prompts_count(tmp_path, monkeypatch):
    """sdk / system / queued prompts are machinery, not a human being blocked."""
    monkeypatch.setattr(nr, "PROJECTS", str(tmp_path))
    _transcript(tmp_path / "p" / "s1.jsonl", [
        {"type": "assistant", "timestamp": "2026-09-01T00:00:00Z"},
        _user("2026-09-01T00:10:00Z", "well?"),
        _user("2026-09-01T00:11:00Z", "well?", source="sdk"),
        _user("2026-09-01T00:12:00Z", "well?", source="system"),
        _user("2026-09-01T00:13:00Z", "well?", source="queued"),
    ])
    typed, nudges = nr.collect("2026-08-01T00:00:00Z")
    assert len(typed) == 1 and len(nudges) == 1


def test_sidechain_prompts_are_excluded(tmp_path, monkeypatch):
    """Subagent traffic is not the user."""
    monkeypatch.setattr(nr, "PROJECTS", str(tmp_path))
    _transcript(tmp_path / "p" / "s1.jsonl", [
        _user("2026-09-01T00:10:00Z", "well?", isSidechain=True),
    ])
    assert nr.collect("2026-08-01T00:00:00Z") == ([], [])


def test_idle_gap_is_measured_from_the_last_assistant_turn(tmp_path, monkeypatch):
    monkeypatch.setattr(nr, "PROJECTS", str(tmp_path))
    _transcript(tmp_path / "p" / "s1.jsonl", [
        {"type": "assistant", "timestamp": "2026-09-01T00:00:00Z"},
        _user("2026-09-01T00:20:00Z", "well?"),
    ])
    _, nudges = nr.collect("2026-08-01T00:00:00Z")
    assert nudges[0]["idle_s"] == 1200


# --- the deploy confound ----------------------------------------------------


def test_started_after_excludes_sessions_predating_a_deploy(tmp_path, monkeypatch):
    """A deployed gate is inert in an already-running session.

    On 2026-09-07 all four nudged sessions had begun 1-4 days earlier, so they
    carried none of the night's fixes. Counting them would have read as the
    repairs failing.
    """
    monkeypatch.setattr(nr, "PROJECTS", str(tmp_path))
    _transcript(tmp_path / "p" / "old.jsonl", [
        {"type": "assistant", "timestamp": "2026-09-03T00:00:00Z"},
        _user("2026-09-07T10:00:00Z", "well?"),
    ])
    _transcript(tmp_path / "p" / "new.jsonl", [
        {"type": "assistant", "timestamp": "2026-09-07T08:00:00Z"},
        _user("2026-09-07T10:00:00Z", "well?"),
    ])

    _, all_nudges = nr.collect("2026-09-01T00:00:00Z")
    assert len(all_nudges) == 2, "unfiltered must see both"

    _, post = nr.collect("2026-09-01T00:00:00Z", started_after="2026-09-07T07:05:00Z")
    assert len(post) == 1, "only the session begun after the deploy counts"


def test_empty_population_reports_zero_not_success(tmp_path, monkeypatch):
    """No post-deploy sessions yet must read as 'no data', never as 0% nudges."""
    monkeypatch.setattr(nr, "PROJECTS", str(tmp_path))
    typed, nudges = nr.collect("2026-09-01T00:00:00Z", started_after="2099-01-01T00:00:00Z")
    summary = nr.summarize(typed, nudges)
    assert summary["typed_prompts"] == 0
    assert "no typed prompts" in nr.render(summary, "7d")
