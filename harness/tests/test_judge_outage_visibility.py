"""Oracle for judge-outage visibility in the gate-signal monitor.

escapement-lf8l: the Stop hook's semantic judge fails open on any error, and
records that as decision=allow, reason=winddown_judge_unavailable. When the
local judge LaunchAgent (com.user.rapid-mlx) was silently unloaded, the
continuation gate degraded to a no-op and NOTHING said so. The corpus recorded
it 3,165 times across three repos (escapement 391, cake 1,537, dashboards
1,237) and no operator ever saw a single one.

The monitor already reads this corpus weekly and files beads for
mock-bureaucracy risk, so it is the existing owner of "corpus finding becomes
visible". These tests make a judge outage one of the things it reports.

The negative controls are the point: a clean corpus must produce no warning
and no bead, or the signal becomes noise and gets ignored exactly like the
3,165 records did.
"""

import importlib.util
import pathlib
import sys

BIN = pathlib.Path(__file__).resolve().parents[2] / "claude" / "bin"


def _load():
    spec = importlib.util.spec_from_file_location(
        "gate_signal_monitor", BIN / "gate_signal_monitor.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load claude/bin/gate_signal_monitor.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mon = _load()

JUDGE_REASON = "winddown_judge_unavailable"


def _entry(reason="", gate="continuation-harness", decision="allow"):
    return {"gate": gate, "decision": decision, "reason": reason, "extras": {}}


def _corpus(unavailable=0, healthy=0, repo="escapement"):
    entries = [_entry(JUDGE_REASON) for _ in range(unavailable)]
    entries += [_entry("verification_passed") for _ in range(healthy)]
    return {repo: entries}


# --- the defect: an outage must surface ----------------------------------


def test_judge_outage_is_reported():
    summary = mon.analyze(_corpus(unavailable=391, healthy=9), [])
    ja = summary["judge_availability"]
    assert ja["unavailable"] == 391
    assert ja["stop_events"] == 400
    assert ja["rate"] == 0.98


def test_outage_appears_in_the_human_report():
    summary = mon.analyze(_corpus(unavailable=391, healthy=9), [])
    text = mon.render_human(summary, "7d")
    assert "JUDGE" in text.upper()
    assert "391" in text


def test_outage_is_reported_per_repo():
    """The operator needs to know it is machine-wide, not one repo's config."""
    corpus = {
        "escapement": [_entry(JUDGE_REASON)] * 391,
        "cake": [_entry(JUDGE_REASON)] * 1537,
        "dashboards": [_entry(JUDGE_REASON)] * 1237,
    }
    ja = mon.analyze(corpus, [])["judge_availability"]
    assert ja["unavailable"] == 3165
    assert ja["by_repo"] == {"escapement": 391, "cake": 1537, "dashboards": 1237}


# --- negative controls: silence when healthy ------------------------------


def test_healthy_judge_reports_nothing():
    summary = mon.analyze(_corpus(unavailable=0, healthy=400), [])
    ja = summary["judge_availability"]
    assert ja["unavailable"] == 0
    assert ja["rate"] == 0.0
    text = mon.render_human(summary, "7d")
    assert "JUDGE OUTAGE" not in text.upper()


def test_empty_corpus_does_not_warn():
    summary = mon.analyze({}, [])
    assert summary["judge_availability"]["unavailable"] == 0
    assert summary["judge_availability"]["rate"] == 0.0


def test_a_single_blip_does_not_warn():
    """One transient failure in a healthy week is not an outage."""
    summary = mon.analyze(_corpus(unavailable=1, healthy=999), [])
    assert summary["judge_availability"]["rate"] < 0.05
    assert "JUDGE OUTAGE" not in mon.render_human(summary, "7d").upper()


def test_unrelated_allows_are_not_counted_as_judge_events():
    """Only the winddown rung's allows form the denominator."""
    corpus = {
        "escapement": [
            _entry(JUDGE_REASON),
            _entry("verification_passed"),
            _entry("bd_queue_drained", gate="beads_worktree_guard", decision="deny"),
        ]
    }
    ja = mon.analyze(corpus, [])["judge_availability"]
    assert ja["stop_events"] == 2  # the deny from another gate is excluded
    assert ja["unavailable"] == 1


# --- the actuator: an outage must file a bead -----------------------------


def _summary(unavailable, healthy):
    return mon.analyze(_corpus(unavailable=unavailable, healthy=healthy), [])


def test_outage_files_a_bead(tmp_path, monkeypatch):
    filed = []
    monkeypatch.setattr(mon, "_list_open_monitor_beads", lambda repo: [])
    monkeypatch.setattr(
        mon, "_file_bead",
        lambda repo, title, desc, priority=2: filed.append((title, desc, priority)) or "esc-1",
    )
    actions = mon.file_concerning_patterns(_summary(391, 9), tmp_path, "7d")

    judge_actions = [a for a in actions if "judge" in a["title"].lower()]
    assert len(judge_actions) == 1
    assert judge_actions[0]["action"] == "filed"
    title, desc, priority = next(f for f in filed if "judge" in f[0].lower())
    assert priority == 1  # a dead continuation gate outranks a noisy one
    assert "391" in desc


def test_healthy_judge_files_nothing(tmp_path, monkeypatch):
    """Negative control: the actuator must stay silent on a healthy week."""
    filed = []
    monkeypatch.setattr(mon, "_list_open_monitor_beads", lambda repo: [])
    monkeypatch.setattr(
        mon, "_file_bead",
        lambda repo, title, desc, priority=2: filed.append(title) or "esc-1",
    )
    actions = mon.file_concerning_patterns(_summary(0, 400), tmp_path, "7d")

    assert [a for a in actions if "judge" in a["title"].lower()] == []
    assert [t for t in filed if "judge" in t.lower()] == []


def test_outage_bead_dedups_across_weeks(tmp_path, monkeypatch):
    """A standing outage must not file a new bead every week."""
    title = f"{mon._BEAD_TITLE_PREFIX} judge outage: continuation gate failing open"
    monkeypatch.setattr(
        mon, "_list_open_monitor_beads", lambda repo: [{"title": title}]
    )
    monkeypatch.setattr(
        mon, "_file_bead",
        lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not file")),
    )
    actions = mon.file_concerning_patterns(_summary(391, 9), tmp_path, "7d")
    judge_actions = [a for a in actions if "judge" in a["title"].lower()]
    assert len(judge_actions) == 1
    assert judge_actions[0]["action"] == "deduped"
