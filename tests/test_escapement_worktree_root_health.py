"""Behavioral oracle for repair of a primary checkout flipped to bare.

The oracle is Git itself: after a repair the primary must again be a usable
work tree holding the same commit, branch and files it held while broken, and
a repository that is legitimately bare must come through untouched.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from worktree_fixtures import git, make_remote_scenario, rev, run_cli, snapshot_primary


def _flip_to_bare(primary: Path) -> None:
    """Reproduce the observed corruption exactly: a stray bare init."""
    subprocess.run(
        ["git", "init", "--quiet", "--bare"],
        cwd=primary,
        env={"GIT_DIR": ".git", "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"},
        check=True,
        capture_output=True,
    )


def _bare_value(repo_config: Path) -> str | None:
    result = subprocess.run(
        ["git", "config", "--file", str(repo_config), "--get", "core.bare"],
        text=True,
        capture_output=True,
        check=False,
    )
    return None if result.returncode else result.stdout.strip()


def _records(primary: Path) -> list[dict[str, object]]:
    record = primary / ".beads" / "root-health.jsonl"
    if not record.is_file():
        record = primary / ".git" / "escapement-root-health.jsonl"
    if not record.is_file():
        return []
    return [json.loads(line) for line in record.read_text().splitlines() if line]


def test_flipped_primary_is_unusable_before_repair(tmp_path: Path) -> None:
    """Negative control: the reproduction really does break the work tree."""
    scenario = make_remote_scenario(tmp_path)
    _flip_to_bare(scenario.primary)

    assert _bare_value(scenario.primary / ".git" / "config") == "true"
    assert git(scenario.primary, "status", "--porcelain", check=False).returncode != 0
    assert (
        git(scenario.primary, "rev-parse", "--show-toplevel", check=False).returncode
        != 0
    )


def test_sync_root_restores_flipped_primary_to_a_usable_checkout(
    tmp_path: Path,
) -> None:
    scenario = make_remote_scenario(tmp_path)
    git(scenario.primary, "switch", "trunk")
    head_before = rev(scenario.primary)
    _flip_to_bare(scenario.primary)

    result = run_cli(scenario.primary, "sync-root", "--repo", str(scenario.primary))

    assert result.returncode == 0, result.stderr
    assert _bare_value(scenario.primary / ".git" / "config") == "false"
    assert git(scenario.primary, "status", "--porcelain").returncode == 0
    assert (
        git(scenario.primary, "symbolic-ref", "--short", "HEAD").stdout.strip()
        == "trunk"
    )
    # Repair restores the work tree; sync-root then performs only its own
    # documented fast-forward, starting from the commit the repo was stranded on.
    assert (scenario.primary / "oracle.txt").read_text() == "remote-default\n"
    assert rev(scenario.primary) == scenario.remote_head_sha
    assert json.loads(result.stdout)["previous_sha"] == head_before


def test_repair_records_evidence_naming_the_prior_config(tmp_path: Path) -> None:
    scenario = make_remote_scenario(tmp_path)
    git(scenario.primary, "switch", "trunk")
    head_before = rev(scenario.primary)
    _flip_to_bare(scenario.primary)

    run_cli(scenario.primary, "sync-root", "--repo", str(scenario.primary))

    records = _records(scenario.primary)
    assert len(records) == 1
    entry = records[0]
    assert entry["outcome"] == "repaired"
    assert entry["recurrence"] == 1
    assert entry["head_sha"] == head_before
    assert entry["branch"] == "trunk"
    assert "bare = true" in str(entry["config_before"])


def test_second_repair_in_the_window_is_reported_as_a_recurrence(
    tmp_path: Path,
) -> None:
    scenario = make_remote_scenario(tmp_path)
    git(scenario.primary, "switch", "trunk")

    for _ in range(2):
        _flip_to_bare(scenario.primary)
        run_cli(scenario.primary, "sync-root", "--repo", str(scenario.primary))

    recurrences = [entry["recurrence"] for entry in _records(scenario.primary)]
    assert recurrences == [1, 2]


def test_legitimately_bare_repository_is_never_repaired(tmp_path: Path) -> None:
    """A bare repo with linked worktrees carries the same core.bare signature.

    Writing core.bare=false into it would make Git adopt its parent directory
    as a work tree, so the lifecycle must refuse rather than 'repair'.
    """
    scenario = make_remote_scenario(tmp_path)
    bare = tmp_path / "mirror.git"
    git(tmp_path, "clone", "--bare", str(scenario.remote), str(bare))
    git(bare, "worktree", "add", str(tmp_path / "mirror-wt"), "trunk")
    assert _bare_value(bare / "config") == "true"

    result = run_cli(scenario.primary, "sync-root", "--repo", str(bare))

    assert result.returncode != 0
    assert "not a primary checkout" in (result.stderr + result.stdout)
    assert _bare_value(bare / "config") == "true"
    assert _records(bare) == []


def test_separate_git_dir_checkout_is_never_repaired(tmp_path: Path) -> None:
    """--separate-git-dir puts a .git *file* beside the tree; not our fault."""
    external = tmp_path / "external-gitdir"
    work = tmp_path / "work"
    subprocess.run(
        ["git", "init", "--quiet", f"--separate-git-dir={external}", str(work)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "--file", str(external / "config"), "core.bare", "true"],
        check=True,
        capture_output=True,
    )

    result = run_cli(work, "sync-root", "--repo", str(work))

    assert result.returncode != 0
    assert _bare_value(external / "config") == "true"


def test_healthy_primary_is_not_probed_or_recorded(tmp_path: Path) -> None:
    scenario = make_remote_scenario(tmp_path)
    git(scenario.primary, "switch", "trunk")
    before = snapshot_primary(scenario.primary)

    result = run_cli(scenario.primary, "sync-root", "--repo", str(scenario.primary))

    assert result.returncode == 0, result.stderr
    assert _records(scenario.primary) == []
    assert _bare_value(scenario.primary / ".git" / "config") == "false"
    assert snapshot_primary(scenario.primary).branch == before.branch


def test_unwritable_config_fails_loudly_without_removing_the_lock(
    tmp_path: Path,
) -> None:
    scenario = make_remote_scenario(tmp_path)
    _flip_to_bare(scenario.primary)
    lock = scenario.primary / ".git" / "config.lock"
    lock.write_text("held by another writer\n", encoding="utf-8")

    result = run_cli(scenario.primary, "sync-root", "--repo", str(scenario.primary))

    assert result.returncode != 0
    assert lock.is_file(), "a contended repair must never break another writer's lock"
    assert _bare_value(scenario.primary / ".git" / "config") == "true"
    records = _records(scenario.primary)
    assert [entry["outcome"] for entry in records] == ["contended"]
