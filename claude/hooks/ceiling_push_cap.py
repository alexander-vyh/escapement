"""PreToolUse gate: enforce a repo's git completion ceiling (local tier).

Business invariant (openspec/changes/git-completion-ceiling/): a repo whose
``.claude/repo-policy.json`` sets ``git_completion_ceiling=local`` permits commits
but NOT pushes. An agent ``git push`` in such a repo is denied here; ``pr`` /
``merge`` / unconfigured repos are unaffected (default ``pr`` allows push).
Governs agent Bash tool-calls only — a human ``!``-shell push never transits
PreToolUse, so it is structurally out of scope.

Detection arg-PARSES the command (per ``bypass_guard``): ``git push`` appearing
inside a commit *message* is not a push, and ``git -C <dir> push`` /
``FOO=bar git push`` / ``git push -u origin main`` all are.

Escape (gate-design Rule 1): prefix the command with
  CEILING_WAIVER="<substantive reason>"
The reason must be real (>=20 chars, not a placeholder, and not a bare echo of
the ceiling vocabulary); it is recorded as a waiver signal.

Resolver: ``_repo_policy.resolve_ceiling`` (escapement-8d2.1). This is the cap
(escapement-8d2.2).
"""
import json
import os
import re
import shlex
import sys
from pathlib import Path

# Shared signal capture per claude/rules/gate-design.md Rule 2; bound as a module
# attribute so tests can monkeypatch ``ceiling_push_cap._record_signal``.
sys.path.insert(0, str(Path(__file__).parent))
try:
    from _gate_signal import record as _record_signal
except ImportError:  # pragma: no cover
    def _record_signal(*_args, **_kwargs) -> None:
        return None
from _repo_policy import resolve_ceiling

_GATE = "git-completion-ceiling"
_MIN_WAIVER_LEN = 20
_PLACEHOLDERS = frozenset({"none", "tbd", "todo", "wip", "n/a", "na", "fixme", "xxx", "?", "??", "???"})
# Reasons that merely restate the ceiling vocabulary carry no substance.
_ECHO_TOKENS = frozenset({"local", "pr", "merge", "ceiling", "push", "git", "git_completion_ceiling"})
_ENV_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# git global options that take a value, so the subcommand scan can skip them.
_GIT_OPTS_WITH_VALUE = frozenset({"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--exec-path"})


def _segments(command: str) -> list:
    """Split a shell command on && || ; | and shlex-tokenize each piece."""
    segments = []
    for raw in re.split(r"&&|\|\||;|\|", command):
        raw = raw.strip()
        if not raw:
            continue
        try:
            parts = shlex.split(raw)
        except ValueError:
            continue
        if parts:
            segments.append(parts)
    return segments


def _split_env(tokens: list):
    """Partition leading VAR=VALUE assignments from the rest of the argv."""
    envs = {}
    i = 0
    while i < len(tokens) and _ENV_RE.match(tokens[i]):
        key, _, val = tokens[i].partition("=")
        envs[key] = val
        i += 1
    return envs, tokens[i:]


def _is_git_push(argv: list) -> bool:
    """True if argv (post-env) is a ``git ... push`` invocation, skipping git
    global options so ``git -C /x push`` matches and a non-push subcommand
    (status, commit, ...) does not."""
    if not argv or argv[0] != "git":
        return False
    i = 1
    while i < len(argv):
        tok = argv[i]
        if tok in _GIT_OPTS_WITH_VALUE:
            i += 2
            continue
        if tok.startswith("-"):
            i += 1
            continue
        return tok == "push"
    return False


def _find_push_argv(command: str):
    """Return the post-env argv of the first ``git push`` segment, or None."""
    for tokens in _segments(command):
        _, argv = _split_env(tokens)
        if _is_git_push(argv):
            return argv
    return None


def _cwd_for(push_argv: list, default_cwd: str) -> str:
    """If the push uses ``git -C <dir>``, resolve the ceiling for <dir>."""
    for j, tok in enumerate(push_argv):
        if tok == "-C" and j + 1 < len(push_argv):
            return push_argv[j + 1]
    return default_cwd


def _extract_waiver(command: str):
    for tokens in _segments(command):
        envs, _ = _split_env(tokens)
        if "CEILING_WAIVER" in envs:
            return envs["CEILING_WAIVER"]
    return None


def _waiver_ok(reason: str) -> bool:
    stripped = reason.strip()
    if len(stripped) < _MIN_WAIVER_LEN or stripped.lower() in _PLACEHOLDERS:
        return False
    significant = [w for w in re.findall(r"[a-z0-9_]+", stripped.lower()) if w not in _ECHO_TOKENS]
    return len(significant) >= 2


def build_message(waiver) -> str:
    waiver_note = ""
    if waiver is not None:
        waiver_note = (
            f'\nYour CEILING_WAIVER ("{waiver.strip()[:60]}") was rejected: it must be '
            f">={_MIN_WAIVER_LEN} chars, not a placeholder, and name a real reason "
            "(not just echo 'local'/'push').\n"
        )
    return (
        "GIT COMPLETION CEILING: this repo's ceiling is 'local' — commit, do not push.\n"
        "The repo declares git_completion_ceiling=local in .claude/repo-policy.json, so a "
        "push exceeds the limit this repo set for agent work.\n"
        f"{waiver_note}\n"
        "Two paths forward:\n"
        "  (1) **Stop at the ceiling** — commit your work and end here. A local commit is a "
        "complete outcome in this repo; stopping here is NOT shirking.\n"
        "  (2) **Waiver** (only if the ceiling is wrong for this case): prefix the command with\n"
        '       CEILING_WAIVER="<why this push is needed despite the local ceiling>"\n'
        "     The reason is recorded as a waiver signal. To change the policy itself, edit "
        ".claude/repo-policy.json."
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

    push_argv = _find_push_argv(command)
    if push_argv is None:
        return allow()

    cwd = _cwd_for(push_argv, data.get("cwd") or os.getcwd())
    if resolve_ceiling(cwd) != "local":
        return allow()  # pr / merge / unconfigured -> push is at or below the ceiling

    waiver = _extract_waiver(command)
    if waiver is not None and _waiver_ok(waiver):
        _record_signal(_GATE, "waiver-accepted", reason=waiver.strip(),
                       event_type="waiver", ceiling="local", action="push")
        return allow()

    _record_signal(_GATE, "deny", reason="push blocked by local ceiling",
                   ceiling="local", action="push", waiver_present=waiver is not None)
    return deny(build_message(waiver))


if __name__ == "__main__":
    raise SystemExit(main())
