"""_git_work_remains must not count churny beads telemetry as work-to-finish.

Dogfood finding (2026-06-14): Fix 1 (verification_passed_git_work_remains) and the
conversational wind-down path both use _git_work_remains. `bd` rewrites
.beads/interactions.jsonl (+ gate-signal/waiver logs) on every command, and on a
protected main they can't be pushed — so counting them false-positives the Stop gate
after any bd activity, with no clean resolution. issues.jsonl stays counted (real state).
"""
import pathlib
import sys

BIN = pathlib.Path(__file__).resolve().parent.parent / "bin"
sys.path.insert(0, str(BIN))

import stop_hook as sh


class _R:
    def __init__(self, out): self.stdout = out


def _git(status_lines, ahead="0"):
    def run_git(args):
        if args[:2] == ["status", "--porcelain"]:
            return _R("\n".join(status_lines))
        if args and args[0] == "rev-list":
            return _R(ahead)
        return None
    return run_git


def test_beads_telemetry_only_is_not_work():
    """The actual trap: only .beads/interactions.jsonl modified -> not work."""
    assert sh._git_work_remains("/repo", run_git=_git([" M .beads/interactions.jsonl"])) is False


def test_all_telemetry_files_excluded():
    g = _git([
        " M .beads/interactions.jsonl",
        " M .beads/.gate-signal.jsonl",
        " M .beads/.gate-waivers.jsonl",
    ])
    assert sh._git_work_remains("/repo", run_git=g) is False


def test_issues_jsonl_still_counts():
    """issues.jsonl is real issue state, not telemetry -> still work-remaining."""
    assert sh._git_work_remains("/repo", run_git=_git([" M .beads/issues.jsonl"])) is True


def test_real_tracked_change_still_counts():
    assert sh._git_work_remains("/repo", run_git=_git([" M harness/bin/foo.py"])) is True


def test_telemetry_plus_real_change_counts():
    g = _git([" M .beads/interactions.jsonl", " M src/app.py"])
    assert sh._git_work_remains("/repo", run_git=g) is True


def test_untracked_only_still_not_work():
    assert sh._git_work_remains("/repo", run_git=_git(["?? scratch.txt"])) is False


def test_unpushed_commit_still_counts():
    assert sh._git_work_remains("/repo", run_git=_git([], ahead="2")) is True
