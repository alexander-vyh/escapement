"""Wire the repair-attribution controls into the suite.

The controls themselves live in `tools/repair_attribution.py --self-test`, next to the
code they constrain, because the CLI is also the surface a person runs by hand. They are
not restated here — a second copy would drift from the first. This module exists so CI
runs them, and so the ranking is checked against this repository's real history rather
than only against a synthetic fixture.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "tools" / "repair_attribution.py"

sys.path.insert(0, str(ROOT / "tools"))
import repair_attribution  # noqa: E402


def test_self_test_controls_pass():
    """1 positive + 3 negative controls over a synthetic history with known truth."""
    result = subprocess.run([sys.executable, str(LEDGER), "--self-test"],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr


def test_ranks_this_repository_by_repair_not_by_churn():
    """On real history, the ledger must separate 'changed often' from 'repaired often'.

    A ranking by raw touch count would put any busy file on top. The two files this
    repository actually repairs most are `render_agent_surfaces.py` (29 repairs / 51
    touches) and `stop_hook.py` (20 / 36) — both must lead, and a file with comparable
    churn but few repairs must not.
    """
    report = repair_attribution.analyze(repair_attribution.read_history(ROOT))
    ranked = [sink["path"] for sink in report["repair_sinks"]]
    assert ranked, "this repository has repair history; an empty ranking is a bug"

    leaders = set(ranked[:3])
    assert "tools/render_agent_surfaces.py" in leaders
    assert "harness/bin/stop_hook.py" in leaders

    for sink in report["repair_sinks"]:
        assert sink["repairs"] or sink["repairs_within_7d"], (
            f"{sink['path']} is ranked with no repairs at all — the ledger is ranking "
            f"churn, not repair"
        )


def test_every_within_window_repair_names_the_landing_it_followed():
    """Attribution is the point; a count without a blamed landing is just a histogram."""
    report = repair_attribution.analyze(repair_attribution.read_history(ROOT))
    for sink in report["repair_sinks"]:
        assert len(sink["inducing_commits"]) == sink["repairs_within_7d"], (
            f"{sink['path']} reports {sink['repairs_within_7d']} in-window repairs but "
            f"names {len(sink['inducing_commits'])} inducing landings"
        )


def test_window_is_load_bearing():
    """Widening the window must not shrink the attributed set; a window that changes
    nothing would mean the time dimension is decorative."""
    commits = repair_attribution.read_history(ROOT)
    narrow = repair_attribution.analyze(commits, window_days=1)
    wide = repair_attribution.analyze(commits, window_days=30)
    assert wide["repairs_within_7d"] > narrow["repairs_within_7d"]
