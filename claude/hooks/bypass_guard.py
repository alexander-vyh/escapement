#!/usr/bin/env python3
"""PreToolUse gate: deny finishing commands that DISABLE verification hooks.

Part of the outcome-shirking rework (bead claude-workflow-setup-e9v, move 2). The
hard outcome standard ("ship verified-working code or you failed") is hollow if an
agent can silently switch the verification off. This guard closes that seam.

Disabling = any of:
  - `git commit --no-verify` / `-n` (incl. combined short clusters like `-nm`)
  - `git push --no-verify`            (NOT `git push -n`, which is --dry-run)
  - a pre-commit `SKIP=` env on a commit, or husky `HUSKY=0`
  - `git -c core.hooksPath=/dev/null` (or empty) to point hooks at nothing

Detection arg-PARSES the command (not substring): so `--no-verify` inside a commit
*message* and `git push -n` (dry-run) are correctly allowed.

Escape (gate-design Rule 1): prefix the command with
  `BYPASS_WAIVER="<>=20-char reason naming the broken hook / ticket>"`
The reason is value-validated (Rule 3) and recorded as signal (Rule 2).

Input: PreToolUse JSON on stdin. Output: deny JSON on stdout (exit 0) or nothing.
"""

from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
try:
    from _gate_signal import record as _record_signal
except ImportError:  # pragma: no cover
    def _record_signal(*_args, **_kwargs) -> None:
        return None

_MIN_WAIVER_LEN = 20
_PLACEHOLDERS = frozenset({"none", "tbd", "todo", "wip", "n/a", "na", "fixme", "xxx", "?", "??", "???"})

# Short flags (in a `git commit` cluster) that consume the NEXT token as a value.
_COMMIT_VALUE_SHORTS = frozenset({"m", "F", "C", "S"})
# Long flags on commit that take a separate-token value (skip their argument).
_COMMIT_VALUE_LONGS = frozenset(
    {"--message", "--file", "--reuse-message", "--reedit-message", "--author", "--date", "--gpg-sign"}
)
# git global options (before the subcommand) that consume the next token.
_GIT_GLOBAL_VALUE_OPTS = frozenset({"-c", "-C", "--git-dir", "--work-tree", "--namespace", "--exec-path"})


def _segments(command: str) -> list[list[str]]:
    """Split a shell command on && || ; | and shlex-tokenize each piece."""
    segments: list[list[str]] = []
    for raw in re.split(r"\s*(?:&&|\|\||;|\|)\s*", command.replace("\\\n", " ")):
        try:
            parts = shlex.split(raw)
        except ValueError:
            continue
        if parts:
            segments.append(parts)
    return segments


def _split_env(tokens: list[str]) -> tuple[dict[str, str], list[str]]:
    """Peel leading VAR=value assignments off the front of a segment."""
    envs: dict[str, str] = {}
    i = 0
    while i < len(tokens) and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", tokens[i]):
        key, _, val = tokens[i].partition("=")
        envs[key] = val
        i += 1
    return envs, tokens[i:]


def _git_subcommand(argv: list[str]) -> str | None:
    i = 1
    while i < len(argv):
        t = argv[i]
        if t in _GIT_GLOBAL_VALUE_OPTS:
            i += 2
            continue
        if t.startswith("-"):
            i += 1
            continue
        return t
    return None


def _hookspath_disabled(argv: list[str]) -> bool:
    """`-c core.hooksPath=<disable>` points hooks at nothing."""
    for i, t in enumerate(argv):
        kv = None
        if t == "-c" and i + 1 < len(argv):
            kv = argv[i + 1]
        elif t.startswith("core.hooksPath="):
            kv = t
        if kv and kv.startswith("core.hooksPath="):
            val = kv.split("=", 1)[1]
            if val == "" or val == "/dev/null" or val.endswith("/dev/null"):
                return True
    return False


def _has_no_verify(argv: list[str], sub: str) -> bool:
    try:
        i = argv.index(sub) + 1
    except ValueError:
        return False
    while i < len(argv):
        t = argv[i]
        if t == "--":  # end of options; remainder are pathspecs
            break
        if t == "--no-verify":
            return True
        if t.startswith("--"):
            name = t.split("=", 1)[0]
            if name in _COMMIT_VALUE_LONGS and "=" not in t:
                i += 2  # skip its separate-token value
                continue
            i += 1
            continue
        if t.startswith("-") and len(t) > 1:
            cluster = t[1:]
            if sub == "commit" and "n" in cluster:  # -n / -nm / -an...
                return True
            if cluster and cluster[-1] in _COMMIT_VALUE_SHORTS:
                i += 2  # cluster ends in a value-taking short (e.g. -m): skip the value
                continue
            i += 1
            continue
        i += 1  # positional (pathspec / message text already consumed)
    return False


def detect_bypass(command: str) -> str | None:
    """Return a bypass category if the command disables hooks, else None."""
    for tokens in _segments(command):
        envs, argv = _split_env(tokens)
        is_git = bool(argv) and argv[0] == "git"
        sub = _git_subcommand(argv) if is_git else None
        if envs.get("HUSKY") == "0":
            return "hooks-disabled"
        if envs.get("SKIP") and sub == "commit":
            return "skip-env"
        if not is_git:
            continue
        if sub in ("commit", "push") and _hookspath_disabled(argv):
            return "hooks-path"
        if sub in ("commit", "push") and _has_no_verify(argv, sub):
            return "no-verify"
    return None


def _extract_waiver(command: str) -> str | None:
    for tokens in _segments(command):
        envs, _ = _split_env(tokens)
        if "BYPASS_WAIVER" in envs:
            return envs["BYPASS_WAIVER"]
    return None


def _waiver_ok(reason: str) -> bool:
    stripped = reason.strip()
    return len(stripped) >= _MIN_WAIVER_LEN and stripped.lower() not in _PLACEHOLDERS


_CATEGORY_DESC = {
    "no-verify": "disables git's pre-commit/pre-push hooks (--no-verify / -n)",
    "skip-env": "skips pre-commit hooks via the SKIP= env var",
    "hooks-disabled": "disables hooks via HUSKY=0",
    "hooks-path": "points core.hooksPath at nothing, disabling all hooks",
}


def build_message(category: str, waiver: str | None) -> str:
    what = _CATEGORY_DESC.get(category, "disables verification hooks")
    waiver_note = ""
    if waiver is not None:
        waiver_note = (
            f'\nYour BYPASS_WAIVER ("{waiver.strip()[:60]}") was rejected: it must be '
            f"at least {_MIN_WAIVER_LEN} characters and not a placeholder.\n"
        )
    return (
        f"VERIFICATION-BYPASS GATE: this command {what}.\n"
        "The outcome standard is 'ship verified-working code or you failed' — turning "
        "verification off is not a way to reach green.\n"
        f"{waiver_note}\n"
        "Two paths forward:\n"
        "  (1) **Don't bypass** — let the hooks run and fix what they flag. That is the work.\n"
        "  (2) **Waiver** (only if a hook is itself broken / irrelevant): prefix the command with\n"
        '       BYPASS_WAIVER="<reason naming the broken hook and the tracking ticket>"\n'
        "     The reason must name a real cause (>=20 chars, no placeholder); it is recorded as signal."
    )


def allow() -> int:
    return 0


def deny(message: str) -> int:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": message,
        }
    }))
    return 0


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        return allow()
    if data.get("hook_event_name") != "PreToolUse" or data.get("tool_name") != "Bash":
        return allow()
    command = (data.get("tool_input") or {}).get("command")
    if not isinstance(command, str):
        return allow()

    category = detect_bypass(command)
    if category is None:
        return allow()

    waiver = _extract_waiver(command)
    if waiver is not None and _waiver_ok(waiver):
        _record_signal(gate_name="bypass_guard", decision="waiver-accepted",
                       reason=waiver.strip(), category=category)
        return allow()

    _record_signal(gate_name="bypass_guard", decision="deny",
                   reason=f"bypass attempt ({category})", category=category,
                   waiver_present=waiver is not None)
    return deny(build_message(category, waiver))


if __name__ == "__main__":
    raise SystemExit(main())
