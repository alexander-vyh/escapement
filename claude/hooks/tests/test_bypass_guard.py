"""Oracle for the verification-bypass guard.

Business invariant
------------------
A session cannot disable verification hooks at the finishing boundary without a
substantive waiver. Disabling means: `--no-verify` / `-n` on `git commit`, a
pre-commit `SKIP=` env, husky `HUSKY=0`, or `git -c core.hooksPath=<disable>`.

Fragile implementation this suite must reject
---------------------------------------------
`"--no-verify" in command` (substring). It (a) false-positives when `--no-verify`
is text inside a commit *message* (`test_no_verify_in_message_allowed`), and
(b) confuses `git push -n` — which is `--dry-run`, NOT a bypass
(`test_push_dry_run_allowed`). Only real arg-parsing passes both.
"""

import importlib.util
import io
import json
import sys
from pathlib import Path
from unittest.mock import patch


TEST_DIR = Path(__file__).resolve().parent
HOOK_PATH = TEST_DIR / "bypass_guard.py"
if not HOOK_PATH.exists():
    HOOK_PATH = TEST_DIR.parent / "bypass_guard.py"
spec = importlib.util.spec_from_file_location("bypass_guard", HOOK_PATH)
guard = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["bypass_guard"] = guard
spec.loader.exec_module(guard)


def run_hook(command: str) -> tuple[int, dict | None]:
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
               "tool_input": {"command": command}}
    out = io.StringIO()
    with patch("sys.stdin", io.StringIO(json.dumps(payload))), patch("sys.stdout", out):
        code = guard.main()
    text = out.getvalue().strip()
    return code, (json.loads(text) if text else None)


def assert_denied(code, output):
    assert code == 0, "deny is carried by the stdout JSON decision, not exit 2"
    assert output is not None
    assert output["hookSpecificOutput"]["permissionDecision"] == "deny"


def assert_allowed(code, output):
    assert code == 0
    assert output is None


# --- detection unit tests (NEGATIVE controls: these DISABLE hooks) ----------

def test_detect_commit_no_verify_long():
    assert guard.detect_bypass('git commit --no-verify -m "x"') is not None


def test_detect_commit_no_verify_short():
    assert guard.detect_bypass('git commit -n -m "x"') is not None


def test_detect_commit_no_verify_combined_short():
    # -nm = -n -m ; the 'n' is --no-verify, 'm' consumes the message
    assert guard.detect_bypass('git commit -nm "x"') is not None


def test_detect_skip_env():
    assert guard.detect_bypass('SKIP=flake8 git commit -m "x"') is not None


def test_detect_husky_disable():
    assert guard.detect_bypass('HUSKY=0 git commit -m "x"') is not None


def test_detect_hooks_path_disable():
    assert guard.detect_bypass('git -c core.hooksPath=/dev/null commit -m "x"') is not None


def test_hooks_path_disable_on_pull_or_checkout_allowed():
    # Disabling hooks on pull/checkout is the documented beads-jsonl-desync
    # workaround, NOT a verification bypass at a finishing boundary (e9v.6).
    assert guard.detect_bypass("git -c core.hooksPath=/dev/null pull") is None
    assert guard.detect_bypass("git -c core.hooksPath=/dev/null checkout main") is None


def test_detect_hooks_path_disable_on_push():
    assert guard.detect_bypass("git -c core.hooksPath=/dev/null push") is not None


def test_detect_push_no_verify():
    assert guard.detect_bypass("git push --no-verify") is not None


# --- detection unit tests (POSITIVE controls: NOT a bypass) -----------------

def test_plain_commit_not_flagged():
    assert guard.detect_bypass('git commit -m "x"') is None


def test_plain_push_not_flagged():
    assert guard.detect_bypass("git push") is None


def test_push_dry_run_allowed():
    # -n on push is --dry-run, not --no-verify. MUST NOT be flagged.
    assert guard.detect_bypass("git push -n") is None
    assert guard.detect_bypass("git push --dry-run") is None


def test_no_verify_in_message_allowed():
    # The flag text lives inside the -m argument, not as a real flag.
    assert guard.detect_bypass('git commit -m "document the --no-verify flag"') is None


def test_non_git_command_not_flagged():
    assert guard.detect_bypass("pytest -n auto") is None  # pytest-xdist -n, unrelated


# --- waiver escape (value-not-presence) -------------------------------------

def test_valid_waiver_releases():
    cmd = 'BYPASS_WAIVER="pre-commit black hook segfaults on this repo, tracked in ESC-412" git commit --no-verify -m "x"'
    code, output = run_hook(cmd)
    assert_allowed(code, output)


def test_placeholder_waiver_still_denied():
    code, output = run_hook('BYPASS_WAIVER="tbd" git commit --no-verify -m "x"')
    assert_denied(code, output)


# --- full hook behavior -----------------------------------------------------

def test_hook_denies_no_verify_commit():
    code, output = run_hook('git commit --no-verify -m "x"')
    assert_denied(code, output)
    reason = output["hookSpecificOutput"]["permissionDecisionReason"]
    assert "BYPASS_WAIVER" in reason  # escape path named in the denial (gate-design Rule 1)


def test_hook_allows_plain_commit():
    assert_allowed(*run_hook('git commit -m "x"'))


def test_hook_allows_push_dry_run():
    assert_allowed(*run_hook("git push -n"))


def test_hook_ignores_non_bash():
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Edit", "tool_input": {}}
    out = io.StringIO()
    with patch("sys.stdin", io.StringIO(json.dumps(payload))), patch("sys.stdout", out):
        code = guard.main()
    assert code == 0 and out.getvalue().strip() == ""
