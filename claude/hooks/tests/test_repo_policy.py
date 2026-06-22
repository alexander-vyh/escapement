"""Behavioral oracle for resolve_ceiling (escapement-8d2.1).

Business invariant
------------------
A repo's git completion ceiling (local|pr|merge) is declared in
``<git_root>/.claude/repo-policy.json`` and resolves correctly from ANY
subdirectory. Absence or malformed config resolves to the permissive default
``pr`` — never to a blocking value; malformed config additionally emits a gate
signal.

Fragile implementations this suite rejects
-------------------------------------------
- cwd-only resolution (reads ``./.claude/repo-policy.json`` ignoring the git
  root) -> ``test_resolves_from_nested_subdirectory`` fails it.
- absent-config raises / returns a non-pr value -> ``test_absent_*`` and
  ``test_missing_field_*``.
- presence-only / no fail-safe on malformed config -> ``test_malformed_*`` and
  ``test_out_of_range_*`` assert both the ``pr`` return AND a gate signal.
- over-signalling on a valid config -> ``test_valid_config_does_not_signal``
  (negative control on the signal).
"""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

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


def _write_policy(repo: Path, *, ceiling=None, raw=None) -> None:
    (repo / ".claude").mkdir(parents=True, exist_ok=True)
    content = raw if raw is not None else json.dumps({"git_completion_ceiling": ceiling})
    (repo / ".claude" / "repo-policy.json").write_text(content)


# --- the three valid tiers -------------------------------------------------

def test_local(tmp_path):
    _git_init(tmp_path)
    _write_policy(tmp_path, ceiling="local")
    assert policy.resolve_ceiling(str(tmp_path)) == "local"


def test_pr(tmp_path):
    _git_init(tmp_path)
    _write_policy(tmp_path, ceiling="pr")
    assert policy.resolve_ceiling(str(tmp_path)) == "pr"


def test_merge(tmp_path):
    _git_init(tmp_path)
    _write_policy(tmp_path, ceiling="merge")
    assert policy.resolve_ceiling(str(tmp_path)) == "merge"


# --- negative controls: absence must default to pr, never block ------------

def test_absent_config_defaults_to_pr(tmp_path):
    _git_init(tmp_path)  # git repo, no policy file at all
    assert policy.resolve_ceiling(str(tmp_path)) == "pr"


def test_missing_field_defaults_to_pr(tmp_path):
    _git_init(tmp_path)
    _write_policy(tmp_path, raw=json.dumps({"some_other_key": "x"}))
    assert policy.resolve_ceiling(str(tmp_path)) == "pr"


def test_not_a_git_repo_defaults_to_pr(tmp_path):
    # No git init -> cwd is outside any repo.
    assert policy.resolve_ceiling(str(tmp_path)) == "pr"


# --- the subdirectory test: rejects cwd-only resolution --------------------

def test_resolves_from_nested_subdirectory(tmp_path):
    _git_init(tmp_path)
    _write_policy(tmp_path, ceiling="local")
    nested = tmp_path / "src" / "deep" / "pkg"
    nested.mkdir(parents=True)
    # A cwd-only implementation sees no ./.claude here and would return "pr".
    assert policy.resolve_ceiling(str(nested)) == "local"


# --- malformed config: fail-safe to pr AND emit a signal -------------------

def test_malformed_json_defaults_to_pr_and_signals(tmp_path):
    _git_init(tmp_path)
    _write_policy(tmp_path, raw="{ this is : not valid json ")
    with patch.object(policy, "_record_signal") as rec:
        assert policy.resolve_ceiling(str(tmp_path)) == "pr"
    assert rec.called
    assert rec.call_args.args[0] == "git-completion-ceiling"


def test_out_of_range_value_defaults_to_pr_and_signals(tmp_path):
    _git_init(tmp_path)
    _write_policy(tmp_path, ceiling="yolo")
    with patch.object(policy, "_record_signal") as rec:
        assert policy.resolve_ceiling(str(tmp_path)) == "pr"
    assert rec.called
    assert rec.call_args.args[0] == "git-completion-ceiling"


def test_non_object_json_defaults_to_pr_and_signals(tmp_path):
    # A parseable but wrong-shaped top-level (a bare number) must not crash.
    _git_init(tmp_path)
    _write_policy(tmp_path, raw="42")
    with patch.object(policy, "_record_signal") as rec:
        assert policy.resolve_ceiling(str(tmp_path)) == "pr"
    assert rec.called


# --- positive control on the signal: valid config must NOT warn ------------

def test_valid_config_does_not_signal(tmp_path):
    _git_init(tmp_path)
    _write_policy(tmp_path, ceiling="local")
    with patch.object(policy, "_record_signal") as rec:
        assert policy.resolve_ceiling(str(tmp_path)) == "local"
    assert not rec.called
