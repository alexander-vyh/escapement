#!/usr/bin/env python3
"""PreToolUse gate at landing: did any changed test actually fail before the fix?

`tdd-gate.py` asks whether test files were *touched* before an implementation file.
That is a proxy, and a weak one: a test written after the code, asserting what the code
already does, satisfies it completely. Nothing in this repository has ever executed the
stronger question, so every downstream oracle gate — `implementation_echo_test_gate`,
`outcome_assertion_gate`, `magic_number_echo` — has been reasoning about tests that were
never shown to detect anything.

This gate executes it. At a landing (`gh pr create`, `git push`, `bd close`) it reverts
the branch's production hunks, runs the tests the branch changed, and requires at least
one of them to fail or error. A test that passes without the production change did not
detect the change and is not evidence about it.

Severity is `ask`, not `deny`, and deliberately so. `oracle_strength_diff.py` learned on
a real corpus that oracle-shaped signals false-fire on legitimate work in ways no
mechanical rule separates; the blocking tier is earned by replay evidence, not assumed.
The replay that would earn it lives in `harness/bin/prepatch_verify.py --replay`.

Fail-open by construction: any error resolving the repository, the base ref, or the
scratch worktree allows the landing and records signal. A verifier that cannot run must
not become an outage.

Escape: write `.beads/.prepatch-waiver` containing a reason of at least 20 characters.
The reason is recorded to the waiver corpus as labeled training data, per
`claude/rules/gate-design.md`.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from _gate_signal import record as _record_signal
except ImportError:  # pragma: no cover
    def _record_signal(*_args, **_kwargs) -> bool:
        return False

# Waiver-reason substance is NOT re-implemented here. `oracle_reason_validation`
# already owns the too-short / placeholder / circular classification for this repo
# (gate-design.md Rule 3), and it was deliberately built with no gate dependency so
# callers pass in their own "asserted" token set. A second copy of that bar would
# drift from the first.
try:
    from oracle_reason_validation import asserted_tokens, validate_oracle_reason
except ImportError:  # pragma: no cover - fail open rather than accept anything
    asserted_tokens = None
    validate_oracle_reason = None

GATE = "prepatch_failure"
WAIVER_FILENAME = ".prepatch-waiver"

# Landing actions. `bd close` is included because this repository treats a closed bead
# as delivered work, not as an intermediate state.
LANDING_PATTERNS = (
    re.compile(r"\bgh\s+pr\s+create\b"),
    re.compile(r"\bgit\s+push\b"),
    re.compile(r"\bbd\s+close\b"),
    re.compile(r"\bbd\s+update\s+.*--status[=\s]+closed\b"),
)

# Verdicts that mean a changed test demonstrably reacted to the production change.
DETECTING = {"detecting-failure", "detecting-error"}
# Verdicts that carry no evidence either way; the gate must not manufacture one.
INCONCLUSIVE = {"not-applicable", "skipped"}


def _run(args: list[str], cwd: str, timeout: int = 60):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout)


def is_landing(command: str) -> bool:
    return any(pattern.search(command) for pattern in LANDING_PATTERNS)


def resolve_repo(cwd: str) -> str | None:
    try:
        result = _run(["git", "rev-parse", "--show-toplevel"], cwd)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() or None


def resolve_base(repo: str) -> str | None:
    """Merge-base between HEAD and the landing branch.

    Tries the remote default branch, then common local names. Returns None when no
    base can be resolved — the gate then allows, because a change with no base is a
    change this check cannot reason about.
    """
    candidates: list[str] = []
    head = _run(["git", "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"], repo)
    if head.returncode == 0 and head.stdout.strip():
        candidates.append(head.stdout.strip().removeprefix("refs/remotes/"))
    candidates += ["origin/main", "origin/master", "main", "master"]

    for ref in candidates:
        verify = _run(["git", "rev-parse", "--verify", "--quiet", ref], repo)
        if verify.returncode != 0:
            continue
        base = _run(["git", "merge-base", "HEAD", ref], repo)
        candidate = base.stdout.strip()
        if base.returncode == 0 and candidate:
            head_sha = _run(["git", "rev-parse", "HEAD"], repo).stdout.strip()
            if candidate != head_sha:
                return candidate
    return None


def read_waiver(repo: str, changed: list[str] | None = None) -> tuple[str | None, str]:
    """Return (accepted_reason, rejection_category).

    Presence of the file is not acceptance. The reason must clear the same substance
    bar every other waiver in this repo clears, and must name something beyond the
    paths it is excusing — a waiver reading "prepatch_verify.py has no test" echoes
    the artifact and teaches the corpus nothing.
    """
    path = Path(repo) / ".beads" / WAIVER_FILENAME
    try:
        reason = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None, "absent"
    if not reason:
        return None, "empty"
    if validate_oracle_reason is None or asserted_tokens is None:
        return None, "validator-unavailable"
    asserted = asserted_tokens(changed or [])
    category = validate_oracle_reason(reason, asserted)
    return (None, category) if category else (reason, "")


def load_verifier(repo: str):
    """Import `prepatch_verify` from the plugin bundle or the repository under test.

    `PREPATCH_VERIFY_DIR` overrides the search. It exists because the gate must run in
    repositories that do not vendor Escapement's harness — the governed repo has the
    code under test, the installed plugin has the verifier — and because tests exercise
    the gate against synthetic repositories. Same operator-hook shape as
    `GATE_SIGNAL_FALLBACK_DIR`.
    """
    here = Path(__file__).resolve().parent
    candidates = []
    override = os.environ.get("PREPATCH_VERIFY_DIR")
    if override:
        candidates.append(Path(override))
    candidates += [
        here.parent / "harness" / "bin",       # installed plugin layout
        here.parent.parent / "harness" / "bin",  # source checkout layout
        Path(repo) / "harness" / "bin",
    ]
    for candidate in candidates:
        if (candidate / "prepatch_verify.py").is_file():
            sys.path.insert(0, str(candidate))
            try:
                import prepatch_verify  # type: ignore
                return prepatch_verify
            except ImportError:
                continue
    return None


def allow(reason: str, **extras) -> int:
    _record_signal(GATE, decision="allow", reason=reason, **extras)
    return 0


def ask(hook_event: str, message: str, reason: str, **extras) -> int:
    _record_signal(GATE, decision="ask", reason=reason, **extras)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": hook_event,
            "permissionDecision": "ask",
            "permissionDecisionReason": message,
        }
    }))
    return 0


_WAIVER_REJECTION = {
    "too-short": "is too short to name why no failing test applies",
    "placeholder": "is a placeholder (tbd, n/a, ...) — it names nothing",
    "circular": "only echoes the files it excuses — it names no external reason",
    "empty": "is empty",
    "validator-unavailable": "could not be checked",
}


def _message(verdict, waiver_path: str, rejected: str = "") -> str:
    if verdict.verdict == "no-test":
        headline = (
            f"This landing changes {len(verdict.production)} production file(s) and no "
            f"test file."
        )
    else:
        headline = (
            f"Every test this landing changed still PASSES when its production changes "
            f"are reverted ({verdict.detail})."
        )
    prefix = ""
    if rejected in _WAIVER_REJECTION:
        prefix = (
            f"The waiver in {waiver_path} {_WAIVER_REJECTION[rejected]}, so it was not "
            f"accepted.\n\n"
        )
    return (
        f"{prefix}{headline} No changed test has been shown to detect this change, so "
        f"the suite is not evidence about it.\n\n"
        f"Reproduce: python3 harness/bin/prepatch_verify.py --commit HEAD\n\n"
        f"Either add a test that fails without the production change, or write why "
        f"none applies to {waiver_path} (20+ characters, naming something beyond the "
        f"changed file names), or say 'proceed' where your host asks you to confirm. "
        f"Hosts without a confirm prompt (Codex, Pi) block this landing instead, so "
        f"there the test or the waiver is the way through."
    )


def main(argv: list[str] | None = None) -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    hook_event = data.get("hook_event_name", "") or data.get("hookEventName", "")
    if hook_event != "PreToolUse":
        return 0
    if data.get("tool_name") != "Bash":
        return 0

    tool_input = data.get("tool_input") or {}
    command = tool_input.get("command", "") if isinstance(tool_input, dict) else ""
    if not command or not is_landing(command):
        return 0

    cwd = data.get("cwd") or os.getcwd()
    repo = resolve_repo(cwd)
    if not repo:
        return allow("not a git repository")

    base = resolve_base(repo)
    if not base:
        return allow("no resolvable base ref; nothing to compare against")

    verifier = load_verifier(repo)
    if verifier is None:
        return allow("prepatch_verify unavailable; gate fails open")

    changed = verifier.range_files(Path(repo), base, "HEAD")
    waiver, rejection = read_waiver(repo, changed)
    if waiver:
        _record_signal(GATE, decision="waiver-accepted", reason=waiver,
                       event_type="waiver", command=command[:200])
        return 0
    if rejection not in ("absent", ""):
        _record_signal(GATE, decision="waiver-rejected", reason=rejection,
                       event_type="waiver", command=command[:200])

    try:
        verdict = verifier.evaluate_range(Path(repo), base, "HEAD")
    except Exception as exc:  # noqa: BLE001 - a verifier crash must never block landing
        return allow(f"verifier error, failing open: {type(exc).__name__}")

    if verdict.verdict in DETECTING:
        return allow(f"a changed test detected the change ({verdict.verdict})",
                     detail=verdict.detail, tests=verdict.tests)
    if verdict.verdict in INCONCLUSIVE:
        return allow(f"inconclusive: {verdict.verdict} ({verdict.detail})")

    waiver_path = str(Path(repo) / ".beads" / WAIVER_FILENAME)
    return ask(
        hook_event,
        _message(verdict, waiver_path, rejection),
        reason=f"{verdict.verdict}: no changed test failed against pre-patch code",
        verdict=verdict.verdict,
        production=verdict.production[:20],
        tests=verdict.tests[:20],
        command=command[:200],
    )


if __name__ == "__main__":
    sys.exit(main())
