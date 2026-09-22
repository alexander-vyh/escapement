"""Invariants the repair ledger must hold on any history.

The controls for the core classification live in `tools/repair_attribution.py
--self-test`, beside the code they constrain, because the CLI is also the surface a
person runs by hand. They are wired into CI here rather than restated.

Everything else in this module builds its own history. An earlier version asserted
against *this* repository's git log — that `render_agent_surfaces.py` leads the ranking,
that the in-window count is non-zero. Those assertions were wrong twice over: they fail
under CI's shallow checkout, and they pin a moving corpus, so they would have started
failing on their own as history grew. The real-history numbers belong in the design
document as measurement, not in a test that pretends they are contracts.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "tools" / "repair_attribution.py"

sys.path.insert(0, str(ROOT / "tools"))
import repair_attribution  # noqa: E402

DAY = 86400
BASE_TS = 1_700_000_000


def _git(repo: Path, *args: str, ts: int | None = None) -> None:
    env = dict(os.environ)
    env.update({
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
    })
    if ts is not None:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = f"{ts} +0000"
    subprocess.run(["git", *args], cwd=str(repo), env=env, check=True,
                   capture_output=True, text=True)


def _commit(repo: Path, path: str, body: str, subject: str, ts: int) -> None:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body)
    _git(repo, "add", path, ts=ts)
    _git(repo, "commit", "-m", subject, ts=ts)


def _history(tmp_path: Path) -> Path:
    """A history with three distinct shapes: repaired fast, never repaired, repaired late."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")

    # hot.py: landed, then repaired twice inside a week.
    _commit(repo, "hot.py", "v1\n", "add hot path", BASE_TS)
    _commit(repo, "hot.py", "v2\n", "fix: hot path drops the last row", BASE_TS + 3600)
    _commit(repo, "hot.py", "v3\n", "feat: extend hot path", BASE_TS + 2 * DAY)
    _commit(repo, "hot.py", "v4\n", "fix: hot path regression on empty input",
            BASE_TS + 2 * DAY + 7200)

    # calm.py: changed just as often, never repaired.
    for index, offset in enumerate((0, DAY, 2 * DAY, 3 * DAY)):
        _commit(repo, "calm.py", f"v{index}\n", f"feat: calm step {index}", BASE_TS + offset)

    # slow.py: landed, repaired 40 days later — a repair, but not an in-window one.
    _commit(repo, "slow.py", "v1\n", "add slow path", BASE_TS)
    _commit(repo, "slow.py", "v2\n", "fix: slow path dormant regression", BASE_TS + 40 * DAY)
    return repo


def test_self_test_controls_pass():
    """1 positive + 3 negative controls over a synthetic history with known truth."""
    result = subprocess.run([sys.executable, str(LEDGER), "--self-test"],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr


def test_ranks_by_repair_not_by_churn(tmp_path):
    """`calm.py` changes as often as `hot.py` and is never repaired; only one may rank."""
    report = repair_attribution.analyze(repair_attribution.read_history(_history(tmp_path)))
    ranked = {sink["path"]: sink for sink in report["repair_sinks"]}

    assert "hot.py" in ranked
    assert ranked["hot.py"]["repairs_within_7d"] == 2
    assert "calm.py" not in ranked, "a file that is only busy is not a repair sink"


def test_every_in_window_repair_names_the_landing_it_followed(tmp_path):
    """Attribution is the point; a count without a blamed landing is just a histogram."""
    report = repair_attribution.analyze(repair_attribution.read_history(_history(tmp_path)))
    for sink in report["repair_sinks"]:
        assert len(sink["inducing_commits"]) == sink["repairs_within_7d"], (
            f"{sink['path']} reports {sink['repairs_within_7d']} in-window repairs but "
            f"names {len(sink['inducing_commits'])} inducing landings"
        )
    assert report["inducing_landings"], "a repaired history must blame at least one landing"


def test_window_is_load_bearing(tmp_path):
    """`slow.py` is repaired at 40 days: outside a 7-day window, inside a 90-day one."""
    commits = repair_attribution.read_history(_history(tmp_path))
    narrow = repair_attribution.analyze(commits, window_days=7)
    wide = repair_attribution.analyze(commits, window_days=90)

    narrow_slow = next(s for s in narrow["repair_sinks"] if s["path"] == "slow.py")
    wide_slow = next(s for s in wide["repair_sinks"] if s["path"] == "slow.py")

    assert narrow_slow["repairs"] == 1 and narrow_slow["repairs_within_7d"] == 0
    assert wide_slow["repairs_within_7d"] == 1
    assert wide["repairs_within_7d"] > narrow["repairs_within_7d"]


def test_runs_on_a_shallow_checkout(tmp_path):
    """CI checks out with fetch-depth 1. The ledger must degrade to an empty report,
    not crash — a measurement tool that dies on a shallow clone silently stops
    measuring."""
    source = _history(tmp_path)
    shallow = tmp_path / "shallow"
    subprocess.run(["git", "clone", "-q", "--depth", "1", f"file://{source}", str(shallow)],
                   check=True, capture_output=True, text=True)
    report = repair_attribution.analyze(repair_attribution.read_history(shallow))
    assert report["commits"] == 1
    assert report["repair_sinks"] == []
