"""Behavioral tests for oracle_downgrade_stop.py (the Stop-time advisory wiring).

Proves the differ actually RUNS at Stop over a real git diff and surfaces a
non-blocking systemMessage on a downgrade — while staying silent on a
strengthening, a non-Stop event, and outside a git repo (fail-open). These run the
hook as a subprocess with a real Stop payload, so they exercise the wiring
end-to-end (git diff -> differ -> systemMessage), not just helpers.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_HOOK = Path(__file__).resolve().parents[1] / "oracle_downgrade_stop.py"

_STRONG = "def test_x():\n    assert compute() == 42\n    assert other() == 7\n"
_WEAK = "def test_x():\n    assert compute()\n"  # lost both == comparisons


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "t")
    return repo


def _commit(repo: Path, rel: str, content: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed")


def _run(repo: Path, event: str = "Stop") -> subprocess.CompletedProcess:
    payload = json.dumps({"hook_event_name": event, "cwd": str(repo)})
    return subprocess.run(
        [sys.executable, str(_HOOK)],
        input=payload,
        cwd=str(repo),
        capture_output=True,
        text=True,
    )


def test_in_place_weakening_emits_advisory(tmp_path):
    repo = _init_repo(tmp_path)
    _commit(repo, "tests/test_thing.py", _STRONG)
    (repo / "tests/test_thing.py").write_text(_WEAK)  # weaken in working tree
    r = _run(repo)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert "systemMessage" in out
    assert "tests/test_thing.py" in out["systemMessage"]


def test_whole_file_deletion_emits_advisory(tmp_path):
    repo = _init_repo(tmp_path)
    _commit(repo, "tests/test_thing.py", _STRONG)
    (repo / "tests/test_thing.py").unlink()  # delete the whole test file
    r = _run(repo)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout or "{}")
    assert "systemMessage" in out
    assert "test_thing.py" in out["systemMessage"]


def test_strengthening_is_silent(tmp_path):
    repo = _init_repo(tmp_path)
    _commit(repo, "tests/test_thing.py", _STRONG)
    (repo / "tests/test_thing.py").write_text(_STRONG + "    assert third() == 9\n")
    r = _run(repo)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == "", f"expected silence on strengthening; got {r.stdout!r}"


def test_non_stop_event_is_silent(tmp_path):
    repo = _init_repo(tmp_path)
    _commit(repo, "tests/test_thing.py", _STRONG)
    (repo / "tests/test_thing.py").write_text(_WEAK)
    r = _run(repo, event="PreToolUse")
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == ""


def test_outside_git_repo_fails_open(tmp_path):
    # tmp_path is not a git repo -> hook must return 0 with no output.
    payload = json.dumps({"hook_event_name": "Stop", "cwd": str(tmp_path)})
    r = subprocess.run(
        [sys.executable, str(_HOOK)],
        input=payload,
        cwd=str(tmp_path),
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == ""
