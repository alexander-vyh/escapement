"""Behavioral oracle for the git-completion-ceiling push-cap (escapement-8d2.2).

Business invariant
------------------
In a repo whose ceiling is ``local``, an agent ``git push`` Bash tool-call is
DENIED; in ``pr`` / ``merge`` / unconfigured repos it is ALLOWED. A substantive
``CEILING_WAIVER="..."`` prefix permits the push (recorded as a waiver signal);
a placeholder or echo-only reason does not.

Fragile implementations this suite rejects
-------------------------------------------
- substring matching (``"git push" in command``) -> ``test_push_in_commit_message_allowed``
  and ``test_non_push_git_allowed`` reject it (arg-parse required).
- ignoring env-prefixes / ``-C`` -> ``test_env_prefixed_push_denied``,
  ``test_dash_C_push_uses_that_repo``.
- over-blocking pr/merge/unconfigured -> the ``*_allowed`` controls.
- presence-only waiver (any CEILING_WAIVER passes) -> ``test_placeholder_waiver_denied``,
  ``test_echo_only_waiver_denied``.
- blocking out-of-band (non-Bash) events -> ``test_non_bash_event_allowed`` (the
  human ``!``-shell scoping control).
"""
import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

TEST_DIR = Path(__file__).resolve().parent
MOD_PATH = TEST_DIR / "ceiling_push_cap.py"
if not MOD_PATH.exists():
    MOD_PATH = TEST_DIR.parent / "ceiling_push_cap.py"
_spec = importlib.util.spec_from_file_location("ceiling_push_cap", MOD_PATH)
cap = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules["ceiling_push_cap"] = cap
_spec.loader.exec_module(cap)


def _repo(tmp_path, ceiling=None):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    if ceiling is not None:
        (tmp_path / ".claude").mkdir(parents=True, exist_ok=True)
        (tmp_path / ".claude" / "repo-policy.json").write_text(
            json.dumps({"git_completion_ceiling": ceiling}))
    return tmp_path


def _run(command, cwd, event="PreToolUse", tool="Bash"):
    payload = {"hook_event_name": event, "tool_name": tool,
               "tool_input": {"command": command}, "cwd": str(cwd)}
    buf = io.StringIO()
    with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), \
         patch.object(sys, "stdout", buf):
        rc = cap.main()
    return rc, buf.getvalue()


def _is_deny(output):
    if not output.strip():
        return False
    parsed = json.loads(output)
    return parsed.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"


# --- the core cap: local denies push, others allow -------------------------

def test_push_denied_in_local_repo(tmp_path):
    repo = _repo(tmp_path, ceiling="local")
    rc, out = _run("git push", repo)
    assert _is_deny(out), out
    assert "ceiling" in out.lower() and "CEILING_WAIVER" in out


def test_push_allowed_in_pr_repo(tmp_path):
    repo = _repo(tmp_path, ceiling="pr")
    _, out = _run("git push origin main", repo)
    assert not _is_deny(out)


def test_push_allowed_in_merge_repo(tmp_path):
    repo = _repo(tmp_path, ceiling="merge")
    _, out = _run("git push -u origin feature", repo)
    assert not _is_deny(out)


def test_push_allowed_in_unconfigured_repo(tmp_path):
    repo = _repo(tmp_path)  # negative control: no policy -> default pr -> allow
    _, out = _run("git push", repo)
    assert not _is_deny(out)


# --- arg-parsing, not substring --------------------------------------------

def test_push_in_commit_message_allowed(tmp_path):
    repo = _repo(tmp_path, ceiling="local")
    # subcommand is commit, not push — a substring matcher would wrongly deny.
    _, out = _run('git commit -m "wip: will git push later"', repo)
    assert not _is_deny(out), out


def test_non_push_git_allowed(tmp_path):
    repo = _repo(tmp_path, ceiling="local")
    for cmd in ("git status", "git commit -m done", "git log --oneline"):
        _, out = _run(cmd, repo)
        assert not _is_deny(out), cmd


def test_env_prefixed_push_denied(tmp_path):
    repo = _repo(tmp_path, ceiling="local")
    _, out = _run("GIT_TRACE=1 git push", repo)
    assert _is_deny(out), out


def test_dash_C_push_uses_that_repo(tmp_path):
    # cwd is NOT a local repo, but the push targets a local repo via -C.
    local_repo = _repo(tmp_path / "loc", ceiling="local")
    other = _repo(tmp_path / "oth", ceiling="merge")
    _, out = _run(f"git -C {local_repo} push", other)
    assert _is_deny(out), out


# --- waiver: value-not-presence --------------------------------------------

def test_valid_waiver_permits_and_signals(tmp_path):
    repo = _repo(tmp_path, ceiling="local")
    cmd = 'CEILING_WAIVER="release pipeline is down, shipping hotfix branch" git push'
    with patch.object(cap, "_record_signal") as rec:
        _, out = _run(cmd, repo)
    assert not _is_deny(out), out
    assert rec.called
    assert rec.call_args.args[0] == "git-completion-ceiling"
    assert rec.call_args.args[1] == "waiver-accepted"


def test_placeholder_waiver_denied(tmp_path):
    repo = _repo(tmp_path, ceiling="local")
    _, out = _run('CEILING_WAIVER="tbd" git push', repo)
    assert _is_deny(out), out


def test_echo_only_waiver_denied(tmp_path):
    repo = _repo(tmp_path, ceiling="local")
    # reason restates only ceiling vocabulary -> no substance -> rejected.
    _, out = _run('CEILING_WAIVER="local push ceiling git" git push', repo)
    assert _is_deny(out), out


def test_deny_records_signal(tmp_path):
    repo = _repo(tmp_path, ceiling="local")
    with patch.object(cap, "_record_signal") as rec:
        _, out = _run("git push", repo)
    assert _is_deny(out)
    assert rec.called and rec.call_args.args[1] == "deny"


# --- scoping control: out-of-band events are not the gate's business -------

def test_non_bash_event_allowed(tmp_path):
    repo = _repo(tmp_path, ceiling="local")
    # A non-Bash tool event (and, by extension, a human !-shell push that never
    # transits PreToolUse) must not be touched.
    _, out = _run("git push", repo, tool="Read")
    assert not _is_deny(out)
    _, out2 = _run("git push", repo, event="PostToolUse")
    assert not _is_deny(out2)
