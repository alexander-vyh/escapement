#!/usr/bin/env python3
"""
Codex Stop-event adapter over the shared stop-decision core.

Codex hooks (GA) deliver a Stop payload whose block response is the same
`{"decision": "block", "reason": ...}` contract Claude Code uses, so this
adapter is thin: translate the Codex payload into thread state, ask
`would_block_stop`, and add ONE Codex-specific rung — the deterministic
conversational wind-down check (completion-claim message AND git residue in
cwd) that catches the no-contract laziness class (2026-07-07
cro-reporting incident: "Shipped." on an upstream-gone branch with a dirty
tracked file).

Design contract (openspec/changes/codex-stop-gate/):
- Decision logic is imported from would_block_stop; never reimplemented here.
- Double-keyed rung: git residue alone must not block (dirty-repo Q&A stays
  free); a completion claim alone must not block (clean finishes stay free).
- Fail-open: any internal error allows the stop AND appends an incident
  record — a gate bug degrades to "no gate", never a stuck session, and the
  degradation is observable (never-suppress).
- stdout carries at most the single decision JSON; nothing else may print.

User release comes from last_user_message.json in the session's thread dir,
written by codex_prompt_recorder.py (UserPromptSubmit) — Codex transcripts
are not parsed (nullable path, undocumented format).
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
import time

# The decision core is a vendored sibling, so its absence is a packaging
# failure, not a logic one -- and it must land on the SAME fail-open path as
# every other error. Left as a bare module-level import it raised before main()
# could catch anything: exit 1, no incident record, no trace that the gate had
# failed at all. That is the one failure mode this gate exists to make visible.
try:
    from would_block_stop import (
        load_thread_state,
        thread_dir_for_session,
        would_block_stop,
    )
except ImportError as exc:  # pragma: no cover - exercised via subprocess
    _CORE_IMPORT_ERROR: str | None = str(exc)
else:
    _CORE_IMPORT_ERROR = None

# Completion-claim / wind-down shape. Deliberately a small, legible class of
# phrasings, not a golden string; tuned via the incident log the gate emits
# (anti-metric: empty fires on conversational turns). Double-keying with git
# residue is the false-positive control, so moderate recall is acceptable.
_CLAIM_RE = re.compile(
    r"\bshipped\b"
    r"|\ball done\b"
    r"|\bdone[.!]"
    r"|\bmerged and deployed\b"
    r"|\bis complete\b"
    r"|\bcomplete and\b"
    r"|\bfinished[.!]"
    r"|\bwraps? (?:it|this|things) up\b"
    r"|\bthat wraps it\b"
    r"|\bi'?ll stop here\b"
    r"|\bstopping point\b"
    r"|\bremaining (?:work|items?|tasks?) (?:is|are) listed\b",
    re.IGNORECASE,
)

_RESUMPTION = (
    "Escapement Codex stop gate ({reason}): this turn ends with unproven work. "
    "Ways forward: (1) finish the outcome and run the contract verify "
    "(~/.claude/harness/bin/verify) until it exits 0; (2) resolve the git "
    "residue in {cwd} (dirty tracked files / unpushed commits / upstream-gone "
    "branch) — commit, push, or clean up deliberately; (3) if this really is "
    "the end, the user can release with 'stop'."
)


def is_completion_claim(text) -> bool:
    """True when the assistant's final message claims/offers completion."""
    if not isinstance(text, str) or not text.strip():
        return False
    return bool(_CLAIM_RE.search(text))


def _git_status_lines(cwd: str):
    proc = subprocess.run(
        ["git", "-C", cwd, "status", "--porcelain=v1", "-b"],
        capture_output=True,
        text=True,
        timeout=10,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if proc.returncode != 0:
        return None
    return proc.stdout.splitlines()


def git_work_remains(cwd) -> bool:
    """Deterministic residue check. False (not None) on any doubt — the rung
    abstains rather than blocks when it cannot positively confirm residue."""
    if not isinstance(cwd, str) or not os.path.isdir(cwd):
        return False
    try:
        lines = _git_status_lines(cwd)
    except (OSError, subprocess.SubprocessError):
        return False
    if lines is None:
        return False
    for line in lines:
        if line.startswith("## "):
            # "## branch...upstream [gone]" / "[ahead N]" — unpushed or orphaned.
            if "[gone]" in line or "ahead " in line:
                return True
            continue
        if line.startswith("??"):
            continue  # untracked alone is not residue (too noisy a key)
        if line.strip():
            return True  # modified/staged tracked file
    return False


def _harness_root() -> pathlib.Path:
    override = os.environ.get("HARNESS_ROOT")
    if override:
        return pathlib.Path(override)
    try:
        from would_block_stop import DEFAULT_HARNESS_ROOT  # single source of truth
    except ImportError:
        # Reached only when the core is unreachable -- which is exactly when the
        # incident record matters most. Mirrors would_block_stop's own default
        # so the record lands where the harness already looks for it.
        return pathlib.Path(
            os.environ.get(
                "CONTINUATION_HARNESS_HOME",
                pathlib.Path.home() / ".claude" / "harness",
            )
        )
    return pathlib.Path(DEFAULT_HARNESS_ROOT)


def _log_incident(record: dict) -> None:
    try:
        root = _harness_root()
        root.mkdir(parents=True, exist_ok=True)
        record.setdefault(
            "timestamp", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        )
        record.setdefault("source", "codex_stop_hook")
        with (root / "incidents.jsonl").open("a") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception:  # noqa: BLE001 — logging must never break the decision
        pass


def _read_recorded_user_message(thread_dir: pathlib.Path):
    try:
        data = json.loads((thread_dir / "last_user_message.json").read_text())
    except (OSError, ValueError):
        return None
    text = data.get("text") if isinstance(data, dict) else None
    return text if isinstance(text, str) else None


def main() -> int:
    if _CORE_IMPORT_ERROR is not None:
        # Allow the stop, but say so. A gate that cannot decide must not look
        # like a gate that decided "allow".
        _log_incident({"decision": "allow", "reason": "core_import_failed",
                       "error": _CORE_IMPORT_ERROR[:200]})
        return 0

    try:
        payload = json.loads(sys.stdin.read())
        if not isinstance(payload, dict):
            raise ValueError("payload is not an object")
    except Exception as exc:  # noqa: BLE001 — fail-open with signal
        _log_incident({"decision": "allow", "reason": "malformed_payload",
                       "error": str(exc)[:200]})
        return 0

    try:
        if payload.get("stop_hook_active"):
            return 0

        session_id = payload.get("session_id") or "codex-unknown"
        thread_dir = thread_dir_for_session(session_id, _harness_root())
        thread_dir.mkdir(parents=True, exist_ok=True)

        recent_user_message = _read_recorded_user_message(thread_dir)
        state = load_thread_state(
            thread_dir, recent_user_message=recent_user_message
        )
        decision, reason = would_block_stop(state)

        cwd = payload.get("cwd") or ""
        if decision == "allow" and reason == "conversational":
            # Codex-specific double-keyed wind-down rung (see module docstring).
            if is_completion_claim(payload.get("last_assistant_message")) and \
                    git_work_remains(cwd):
                decision, reason = "block", "winddown_claim_work_remains"

        _log_incident({
            "decision": decision,
            "reason": reason,
            "session_id": session_id,
            # Probe observability: which fields Codex actually sent, to diff
            # against the documented payload contract (task 2 of the change).
            "payload_keys": sorted(payload.keys()),
        })

        if decision == "block":
            print(json.dumps({
                "decision": "block",
                "reason": _RESUMPTION.format(reason=reason, cwd=cwd or "the cwd"),
            }))
        return 0
    except Exception as exc:  # noqa: BLE001 — fail-open with signal
        _log_incident({"decision": "allow", "reason": "adapter_error",
                       "error": str(exc)[:200]})
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
