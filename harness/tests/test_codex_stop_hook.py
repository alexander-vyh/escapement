#!/usr/bin/env python3
"""
Tests for the Codex Stop-event adapter (codex_stop_hook.py) and the
UserPromptSubmit recorder (codex_prompt_recorder.py).

Governed by .agent/runtime/test-oracle-brief.md § "codex-stop-gate walking
skeleton". The canonical fixture is a replay of the 2026-07-07 incident:
Codex declared "Shipped." and stopped on an upstream-gone branch with a dirty
tracked file, no contract, no release. Spec scenarios live in
openspec/changes/codex-stop-gate/specs/codex-stop-gate/spec.md.

Run: python3 -m pytest harness/tests/test_codex_stop_hook.py -q
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import subprocess
import sys

import pytest

HARNESS_DIR = pathlib.Path(__file__).resolve().parent.parent
BIN = HARNESS_DIR / "bin"
sys.path.insert(0, str(BIN))

import codex_stop_hook  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _git(repo: pathlib.Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )


def _make_repo(path: pathlib.Path) -> pathlib.Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "test@test.invalid")
    _git(path, "config", "user.name", "Test")
    (path / "tracked.txt").write_text("v1\n")
    _git(path, "add", "tracked.txt")
    _git(path, "commit", "-q", "-m", "init")
    return path


def _add_origin(repo: pathlib.Path, bare: pathlib.Path) -> None:
    subprocess.run(
        ["git", "init", "-q", "--bare", str(bare)], check=True, capture_output=True
    )
    _git(repo, "remote", "add", "origin", str(bare))
    _git(repo, "push", "-q", "-u", "origin", "main")


def _incident_repo(tmp_path: pathlib.Path) -> pathlib.Path:
    """The cro-reporting shape: upstream-gone branch + dirty tracked file."""
    repo = _make_repo(tmp_path / "incident-repo")
    _add_origin(repo, tmp_path / "incident-origin.git")
    _git(repo, "checkout", "-q", "-b", "fix/something")
    _git(repo, "push", "-q", "-u", "origin", "fix/something")
    _git(repo, "push", "-q", "origin", "--delete", "fix/something")
    _git(repo, "fetch", "-q", "--prune", "origin")
    (repo / "tracked.txt").write_text("v2 dirty\n")  # dirty tracked file
    return repo


def _clean_repo(tmp_path: pathlib.Path) -> pathlib.Path:
    repo = _make_repo(tmp_path / "clean-repo")
    _add_origin(repo, tmp_path / "clean-origin.git")
    return repo


def _dirty_repo(tmp_path: pathlib.Path) -> pathlib.Path:
    repo = _make_repo(tmp_path / "dirty-repo")
    _add_origin(repo, tmp_path / "dirty-origin.git")
    (repo / "tracked.txt").write_text("v2 dirty\n")
    return repo


INCIDENT_MESSAGE = (
    "Shipped.\n\nPR #329 is merged. Remote branch fix/beads-prime-team-maintainer "
    "is deleted.\n\nLocal state is unchanged apart from being on the now-merged "
    "branch with upstream gone; your unrelated .gitignore edit and untracked "
    "folders are still local and were not shipped."
)

PLAIN_ANSWER = (
    "The bug is in the loop condition on line 42 — it drops the last element "
    "because the range excludes the final index. Changing < to <= fixes it."
)


def _payload(
    *,
    session_id: str = "codex-test-session",
    cwd: str,
    message: str | None = INCIDENT_MESSAGE,
    stop_hook_active: bool = False,
) -> dict:
    return {
        "session_id": session_id,
        "transcript_path": None,
        "cwd": cwd,
        "hook_event_name": "Stop",
        "model": "gpt-test",
        "permission_mode": "default",
        "turn_id": "turn-1",
        "stop_hook_active": stop_hook_active,
        "last_assistant_message": message,
    }


def _run_hook(
    payload,
    thread_dir: pathlib.Path,
    harness_root: pathlib.Path,
    raw: str | None = None,
) -> subprocess.CompletedProcess:
    stdin = raw if raw is not None else json.dumps(payload)
    return subprocess.run(
        [sys.executable, "-B", str(BIN / "codex_stop_hook.py")],
        input=stdin,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HARNESS_THREAD_DIR": str(thread_dir),
            "HARNESS_ROOT": str(harness_root),
        },
    )


def _run_recorder(
    payload: dict, thread_dir: pathlib.Path, harness_root: pathlib.Path
) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-B", str(BIN / "codex_prompt_recorder.py")],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HARNESS_THREAD_DIR": str(thread_dir),
            "HARNESS_ROOT": str(harness_root),
        },
    )


def _decision(proc: subprocess.CompletedProcess):
    """Parse the hook's stdout. None = allow (no output). dict = decision JSON."""
    out = proc.stdout.strip()
    if not out:
        return None
    return json.loads(out)


@pytest.fixture()
def env_dirs(tmp_path):
    thread_dir = tmp_path / "thread"
    thread_dir.mkdir()
    harness_root = tmp_path / "harness-root"
    harness_root.mkdir()
    return thread_dir, harness_root


def _write_release(thread_dir: pathlib.Path, text: str = "stop") -> None:
    (thread_dir / "last_user_message.json").write_text(
        json.dumps({"text": text, "recorded_at": _dt.datetime.now(_dt.timezone.utc).isoformat()})
    )


def _write_green_contract(thread_dir: pathlib.Path) -> None:
    now = _dt.datetime.now(_dt.timezone.utc).isoformat()
    (thread_dir / "contract.json").write_text(
        json.dumps(
            {
                "goal": "test goal",
                "verification_command": "python3 -m pytest harness/tests/ -q",
                "expected_exit": 0,
                "created_at": now,
                "last_run": {"exit_code": 0, "timestamp": now},
            }
        )
    )


# ---------------------------------------------------------------------------
# Scenario (a): incident replay → block
# spec: conversational-winddown-rung / incident-replay-blocks
# ---------------------------------------------------------------------------

def test_codex_stop_hook_incident_replay_blocks(tmp_path, env_dirs):
    thread_dir, harness_root = env_dirs
    repo = _incident_repo(tmp_path)
    proc = _run_hook(_payload(cwd=str(repo)), thread_dir, harness_root)
    assert proc.returncode == 0, proc.stderr
    decision = _decision(proc)
    assert decision is not None, "incident replay must block, got allow"
    assert decision["decision"] == "block"
    assert decision["reason"].strip()


def test_block_reason_names_escape_path(tmp_path, env_dirs):
    # spec: block-output-contract / block-reason-names-escape-path
    thread_dir, harness_root = env_dirs
    repo = _incident_repo(tmp_path)
    proc = _run_hook(_payload(cwd=str(repo)), thread_dir, harness_root)
    decision = _decision(proc)
    assert decision is not None
    reason = decision["reason"].lower()
    # The denial must name at least one agent-invokable way forward.
    assert any(
        marker in reason for marker in ("verify", "stop", "finish", "commit", "push")
    ), f"reason gives no way forward: {decision['reason']!r}"


# ---------------------------------------------------------------------------
# Scenario (b): user release is unconditional
# spec: user-release-is-unconditional / recorded-stop-releases-gate
# ---------------------------------------------------------------------------

def test_recorded_stop_releases_gate(tmp_path, env_dirs):
    thread_dir, harness_root = env_dirs
    repo = _incident_repo(tmp_path)
    _write_release(thread_dir, "stop")
    proc = _run_hook(_payload(cwd=str(repo)), thread_dir, harness_root)
    assert proc.returncode == 0, proc.stderr
    assert _decision(proc) is None, "user release must allow unconditionally"


# ---------------------------------------------------------------------------
# Scenario (c): green contract → allow
# spec: stop-decision-reuses-shared-core / green-contract-allows-stop
# ---------------------------------------------------------------------------

def test_green_contract_allows_stop(tmp_path, env_dirs):
    thread_dir, harness_root = env_dirs
    repo = _clean_repo(tmp_path)
    _write_green_contract(thread_dir)
    proc = _run_hook(_payload(cwd=str(repo)), thread_dir, harness_root)
    assert proc.returncode == 0, proc.stderr
    assert _decision(proc) is None


def test_declared_unverified_contract_blocks(tmp_path, env_dirs):
    # spec: declared-but-unverified-contract-blocks — the shared core's teeth.
    thread_dir, harness_root = env_dirs
    repo = _clean_repo(tmp_path)
    (thread_dir / "contract.json").write_text(
        json.dumps(
            {
                "goal": "test goal",
                "verification_command": "python3 -m pytest harness/tests/ -q",
                "expected_exit": 0,
                "last_run": None,
            }
        )
    )
    proc = _run_hook(_payload(cwd=str(repo), message=PLAIN_ANSWER), thread_dir, harness_root)
    decision = _decision(proc)
    assert decision is not None, "declared-but-unverified contract must block"
    assert decision["decision"] == "block"
    assert "verify" in decision["reason"].lower()


# ---------------------------------------------------------------------------
# Scenario (d): loop guard
# spec: loop-guard-honored / second-stop-passes
# ---------------------------------------------------------------------------

def test_stop_hook_active_passes(tmp_path, env_dirs):
    thread_dir, harness_root = env_dirs
    repo = _incident_repo(tmp_path)
    proc = _run_hook(
        _payload(cwd=str(repo), stop_hook_active=True), thread_dir, harness_root
    )
    assert proc.returncode == 0, proc.stderr
    assert _decision(proc) is None


# ---------------------------------------------------------------------------
# Scenarios (e)/(f): double-keyed conversational rung — negative controls
# spec: conversational-winddown-rung / conversational-clean-repo-allows,
#       dirty-repo-plain-answer-allows
# ---------------------------------------------------------------------------

def test_conversational_clean_repo_allows(tmp_path, env_dirs):
    thread_dir, harness_root = env_dirs
    repo = _clean_repo(tmp_path)
    proc = _run_hook(_payload(cwd=str(repo), message=PLAIN_ANSWER), thread_dir, harness_root)
    assert proc.returncode == 0, proc.stderr
    assert _decision(proc) is None


def test_dirty_repo_plain_answer_allows(tmp_path, env_dirs):
    # Residue alone must not fire the rung (single-key = invalid solution class).
    thread_dir, harness_root = env_dirs
    repo = _dirty_repo(tmp_path)
    proc = _run_hook(_payload(cwd=str(repo), message=PLAIN_ANSWER), thread_dir, harness_root)
    assert proc.returncode == 0, proc.stderr
    assert _decision(proc) is None


def test_completion_claim_clean_repo_allows(tmp_path, env_dirs):
    # Phrase alone must not fire the rung either (the other single-key).
    thread_dir, harness_root = env_dirs
    repo = _clean_repo(tmp_path)
    proc = _run_hook(_payload(cwd=str(repo)), thread_dir, harness_root)
    assert proc.returncode == 0, proc.stderr
    assert _decision(proc) is None


# ---------------------------------------------------------------------------
# Scenario (g): fail-open with signal
# spec: fail-open-with-signal / malformed-payload-fails-open
# ---------------------------------------------------------------------------

def test_malformed_payload_fails_open_with_incident(tmp_path, env_dirs):
    thread_dir, harness_root = env_dirs
    proc = _run_hook(None, thread_dir, harness_root, raw="this is not json {")
    assert proc.returncode == 0
    assert _decision(proc) is None, "malformed payload must fail open (allow)"
    incidents = harness_root / "incidents.jsonl"
    assert incidents.exists(), "fail-open must be observable via an incident record"
    assert incidents.read_text().strip(), "incident record must not be empty"


def test_null_message_and_missing_cwd_fail_open(tmp_path, env_dirs):
    thread_dir, harness_root = env_dirs
    payload = _payload(cwd="/nonexistent/definitely/not/a/repo", message=None)
    proc = _run_hook(payload, thread_dir, harness_root)
    assert proc.returncode == 0, proc.stderr
    assert _decision(proc) is None


# ---------------------------------------------------------------------------
# Completion-claim detector — rejects the golden-string fragile implementation.
# The brief requires >=3 distinct claim phrasings and >=2 non-claims.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        INCIDENT_MESSAGE,
        "All done — merged and deployed. Let me know if anything else comes up.",
        "Done! PR #42 is merged and the remote branch is deleted.",
        "That wraps it up — the feature is complete and everything is in place.",
        "I'll stop here for now; the remaining items are listed above.",
    ],
)
def test_completion_claims_detected(text):
    assert codex_stop_hook.is_completion_claim(text) is True


@pytest.mark.parametrize(
    "text",
    [
        PLAIN_ANSWER,
        "Postgres uses MVCC, so readers never block writers; vacuum reclaims "
        "dead tuples afterwards.",
        None,
        "",
    ],
)
def test_non_claims_not_detected(text):
    assert codex_stop_hook.is_completion_claim(text) is False


# ---------------------------------------------------------------------------
# Recorder
# spec: prompt-recorder-persists-last-user-message / prompt-recorded-per-session
# ---------------------------------------------------------------------------

def test_codex_prompt_recorder_persists_last_user_message(tmp_path, env_dirs):
    thread_dir, harness_root = env_dirs
    payload = {
        "session_id": "codex-test-session",
        "transcript_path": None,
        "cwd": str(tmp_path),
        "hook_event_name": "UserPromptSubmit",
        "model": "gpt-test",
        "permission_mode": "default",
        "prompt": "stop",
    }
    proc = _run_recorder(payload, thread_dir, harness_root)
    assert proc.returncode == 0, proc.stderr
    recorded = json.loads((thread_dir / "last_user_message.json").read_text())
    assert recorded["text"] == "stop"


def test_recorder_then_stop_hook_end_to_end(tmp_path, env_dirs):
    # The pair working together: recorder writes, stop hook releases.
    thread_dir, harness_root = env_dirs
    repo = _incident_repo(tmp_path)
    recorder_payload = {
        "session_id": "codex-test-session",
        "hook_event_name": "UserPromptSubmit",
        "cwd": str(repo),
        "prompt": "stop",
    }
    _run_recorder(recorder_payload, thread_dir, harness_root)
    proc = _run_hook(_payload(cwd=str(repo)), thread_dir, harness_root)
    assert _decision(proc) is None, "recorded release must flow through to the gate"


def test_recorder_malformed_payload_fails_open(env_dirs):
    thread_dir, harness_root = env_dirs
    proc = subprocess.run(
        [sys.executable, "-B", str(BIN / "codex_prompt_recorder.py")],
        input="not json",
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HARNESS_THREAD_DIR": str(thread_dir),
            "HARNESS_ROOT": str(harness_root),
        },
    )
    assert proc.returncode == 0


# ---------------------------------------------------------------------------
# Shipped-package control: the hook Codex actually runs
#
# Codex loads hooks from the installed plugin tree, never from this checkout.
# Every test above exercises harness/bin/, so all of them stay green while the
# vendored copy is missing a sibling and fails open on every real session --
# the deployed-but-inert failure this gate exists to end. These two run the
# plugin copy through the same incident replay.
# ---------------------------------------------------------------------------

REPO_ROOT = HARNESS_DIR.parent
CODEX_PLUGIN_BIN = REPO_ROOT / "plugins" / "escapement" / "harness" / "bin"


def _run_plugin_script(
    name: str,
    payload: dict,
    thread_dir: pathlib.Path,
    harness_root: pathlib.Path,
) -> subprocess.CompletedProcess:
    script = CODEX_PLUGIN_BIN / name
    assert script.is_file(), (
        f"{script} is not vendored into the Codex plugin; Codex sessions "
        "would never run it"
    )
    return subprocess.run(
        [sys.executable, "-B", str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "HARNESS_THREAD_DIR": str(thread_dir),
            "HARNESS_ROOT": str(harness_root),
        },
    )


def test_codex_plugin_copy_blocks_the_incident_replay(tmp_path, env_dirs):
    thread_dir, harness_root = env_dirs
    repo = _incident_repo(tmp_path)
    proc = _run_plugin_script(
        "codex_stop_hook.py", _payload(cwd=str(repo)), thread_dir, harness_root
    )
    assert proc.returncode == 0, proc.stderr
    # A missing sibling shows up here first: the import fails, the hook fails
    # open, and stdout is empty while returncode is still 0.
    assert "Error" not in proc.stderr, proc.stderr
    decision = _decision(proc)
    assert decision is not None, (
        "vendored Codex hook allowed the incident replay; it is deployed but "
        f"inert. stderr={proc.stderr!r}"
    )
    assert decision["decision"] == "block"


def test_codex_plugin_recorder_persists_the_release(tmp_path, env_dirs):
    thread_dir, harness_root = env_dirs
    proc = _run_plugin_script(
        "codex_prompt_recorder.py",
        {
            "session_id": "codex-test-session",
            "cwd": str(tmp_path),
            "hook_event_name": "UserPromptSubmit",
            "prompt": "stop",
        },
        thread_dir,
        harness_root,
    )
    assert proc.returncode == 0, proc.stderr
    assert "Error" not in proc.stderr, proc.stderr
    recorded = json.loads((thread_dir / "last_user_message.json").read_text())
    assert recorded["text"] == "stop"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
