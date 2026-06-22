"""Behavioral oracle for set_ceiling (escapement-8d2.5 — per-repo setup).

Business invariant
------------------
Running the setup writes a valid ``<git_root>/.claude/repo-policy.json`` with the
chosen tier such that ``resolve_ceiling`` then returns that tier — the round trip
is the proof, not "a file appeared". Not running it leaves no file (the resolver
defaults to ``pr``).

Fragile implementations this suite rejects
-------------------------------------------
- writes to cwd instead of the git root -> ``test_set_from_subdir_writes_to_root``.
- accepts an invalid tier -> ``test_invalid_tier_rejected_and_no_file`` (must also
  write nothing).
- writes a file the resolver can't read back -> every test asserts via
  ``resolve_ceiling``, not by reading the JSON directly.
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

TEST_DIR = Path(__file__).resolve().parent
MOD_PATH = TEST_DIR / "_repo_policy.py"
if not MOD_PATH.exists():
    MOD_PATH = TEST_DIR.parent / "_repo_policy.py"
_spec = importlib.util.spec_from_file_location("_repo_policy", MOD_PATH)
policy = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules["_repo_policy"] = policy
_spec.loader.exec_module(policy)


def _git_init(path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(path)], check=True)


def test_set_then_resolve_roundtrip(tmp_path):
    _git_init(tmp_path)
    policy.set_ceiling(str(tmp_path), "local")
    assert policy.resolve_ceiling(str(tmp_path)) == "local"


def test_set_each_valid_tier(tmp_path):
    for tier in ("local", "pr", "merge"):
        repo = tmp_path / tier
        _git_init(repo)
        policy.set_ceiling(str(repo), tier)
        assert policy.resolve_ceiling(str(repo)) == tier


def test_set_from_subdir_writes_to_root(tmp_path):
    _git_init(tmp_path)
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    policy.set_ceiling(str(nested), "merge")
    # File must land at the git root, not in the subdir.
    assert (tmp_path / ".claude" / "repo-policy.json").is_file()
    assert not (nested / ".claude" / "repo-policy.json").exists()
    assert policy.resolve_ceiling(str(nested)) == "merge"


def test_overwrites_existing(tmp_path):
    _git_init(tmp_path)
    policy.set_ceiling(str(tmp_path), "pr")
    policy.set_ceiling(str(tmp_path), "merge")
    assert policy.resolve_ceiling(str(tmp_path)) == "merge"


def test_invalid_tier_rejected_and_no_file(tmp_path):
    _git_init(tmp_path)
    with pytest.raises(ValueError):
        policy.set_ceiling(str(tmp_path), "yolo")
    # negative control: a rejected tier must write nothing.
    assert not (tmp_path / ".claude" / "repo-policy.json").exists()


def test_not_a_git_repo_raises(tmp_path):
    with pytest.raises(ValueError):
        policy.set_ceiling(str(tmp_path), "pr")


def test_cli_roundtrip(tmp_path):
    # The CLI entry (python -m / direct) writes a file the resolver reads back.
    _git_init(tmp_path)
    res = subprocess.run(
        [sys.executable, str(MOD_PATH), "set", "local"],
        cwd=str(tmp_path), capture_output=True, text=True,
    )
    assert res.returncode == 0, res.stderr
    assert policy.resolve_ceiling(str(tmp_path)) == "local"


def test_cli_invalid_tier_nonzero(tmp_path):
    _git_init(tmp_path)
    res = subprocess.run(
        [sys.executable, str(MOD_PATH), "set", "nonsense"],
        cwd=str(tmp_path), capture_output=True, text=True,
    )
    assert res.returncode != 0
    assert not (tmp_path / ".claude" / "repo-policy.json").exists()
