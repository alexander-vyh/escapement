"""Resolve a repo's git completion ceiling from .claude/repo-policy.json.

Business invariant: how far an agent may take work — ``local`` (commit only),
``pr`` (push + open PR), or ``merge`` (push + merge) — is declared per-repo. The
ceiling is read at the GIT ROOT (walking up from cwd), so it resolves correctly
from any subdirectory. Absence or malformed config resolves to the permissive
default ``pr`` — never to a blocking value — and malformed config additionally
emits a gate signal (fail-safe, not fail-closed).

Part of the git-completion-ceiling capability (openspec/changes/
git-completion-ceiling/). This module is the resolver; the PreToolUse cap that
enforces it is escapement-8d2.2.
"""
import json
import subprocess
import sys
from pathlib import Path

# Shared signal capture per claude/rules/gate-design.md Rule 2. Bound as a
# module attribute so tests can monkeypatch `_repo_policy._record_signal`.
sys.path.insert(0, str(Path(__file__).parent))
try:
    from _gate_signal import record as _record_signal
except ImportError:  # pragma: no cover
    def _record_signal(*_args, **_kwargs) -> None:
        return None

VALID_CEILINGS = ("local", "pr", "merge")
DEFAULT_CEILING = "pr"
_GATE = "git-completion-ceiling"


def _git_root(cwd: str):
    """Return the git worktree root containing ``cwd``, or None outside a repo
    (or when git is unavailable). Never raises into the caller."""
    try:
        out = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, check=False,
        )
    except (OSError, ValueError):
        return None
    if out.returncode != 0:
        return None
    root = out.stdout.strip()
    return root or None


def resolve_ceiling(cwd: str) -> str:
    """Return the git completion ceiling ('local' | 'pr' | 'merge') for the repo
    containing ``cwd``.

    Defaults to 'pr' (permissive) when: not in a git repo, the config file is
    absent, or the ``git_completion_ceiling`` field is absent. Fails safe to 'pr'
    — emitting a gate signal — when the config file is present but unparseable,
    not a JSON object, or carries a value outside {local, pr, merge}.
    """
    root = _git_root(cwd)
    if root is None:
        return DEFAULT_CEILING

    policy_path = Path(root) / ".claude" / "repo-policy.json"
    if not policy_path.is_file():
        return DEFAULT_CEILING

    try:
        data = json.loads(policy_path.read_text())
    except (OSError, ValueError) as exc:
        _record_signal(
            _GATE, "allow-with-warning",
            reason=(f"unparseable repo-policy.json ({exc.__class__.__name__}); "
                    f"defaulting to {DEFAULT_CEILING}"),
            path=str(policy_path),
        )
        return DEFAULT_CEILING

    if not isinstance(data, dict):
        _record_signal(
            _GATE, "allow-with-warning",
            reason=f"repo-policy.json is not a JSON object; defaulting to {DEFAULT_CEILING}",
            path=str(policy_path),
        )
        return DEFAULT_CEILING

    if "git_completion_ceiling" not in data:
        # Present file, unconfigured field — not malformed, just unset.
        return DEFAULT_CEILING

    value = data.get("git_completion_ceiling")
    if value not in VALID_CEILINGS:
        _record_signal(
            _GATE, "allow-with-warning",
            reason=(f"repo-policy.json git_completion_ceiling={value!r} not in "
                    f"{VALID_CEILINGS}; defaulting to {DEFAULT_CEILING}"),
            path=str(policy_path),
        )
        return DEFAULT_CEILING

    return value


def set_ceiling(cwd: str, tier: str) -> str:
    """Write ``git_completion_ceiling=tier`` to ``<git_root>/.claude/repo-policy.json``
    for the repo containing ``cwd``; return the file path.

    The tier is validated BEFORE the filesystem is touched, so an invalid tier
    writes nothing. Raises ValueError on an invalid tier, or when ``cwd`` is not
    inside a git repository (the ceiling is repo-scoped, so a root is required).
    Skipping setup entirely leaves no file — ``resolve_ceiling`` then defaults to
    ``pr``.
    """
    if tier not in VALID_CEILINGS:
        raise ValueError(f"invalid ceiling {tier!r}; expected one of {VALID_CEILINGS}")
    root = _git_root(cwd)
    if root is None:
        raise ValueError(f"not inside a git repository: {cwd}")
    policy_dir = Path(root) / ".claude"
    policy_dir.mkdir(parents=True, exist_ok=True)
    policy_path = policy_dir / "repo-policy.json"
    policy_path.write_text(json.dumps({"git_completion_ceiling": tier}, indent=2) + "\n")
    return str(policy_path)


def _main(argv) -> int:
    """CLI: ``set <local|pr|merge>`` writes the ceiling for the current repo;
    no args prints the resolved ceiling + usage. Default (skip) → no file → pr."""
    if len(argv) >= 2 and argv[0] == "set":
        try:
            path = set_ceiling(".", argv[1])
        except ValueError as exc:
            print(f"set-repo-ceiling: {exc}", file=sys.stderr)
            return 2
        print(f"git_completion_ceiling = {argv[1]}  ->  {path}")
        return 0
    print(f"git_completion_ceiling = {resolve_ceiling('.')} "
          "(resolved; defaults to 'pr' when unset)")
    print("usage: set-repo-ceiling set <local|pr|merge>")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
