"""Behavioral tests for claude/hooks/beads_worktree_guard.py.

This hook protects one business outcome: new worktrees in a beads-managed
project use the repository-managed ``bd worktree create`` entrypoint instead
of bare ``git worktree add``. Existing linked worktrees use Beads 1.0.5's Git
common-directory tracker discovery and must be allowed to finish their normal
Git workflow without a legacy ``.beads/redirect`` marker.

Unlike no_direct_send_guard (which ALWAYS denies, because its tools are
inherently blocked), this guard is CONDITIONAL: it must deny ``git worktree
add`` only when the command runs inside a beads project, and let it pass
through everywhere else. That conditionality is where a fragile implementation
hides, so the controls are built around it:

  Negative control — ``git worktree add`` with a ``.beads/`` directory present
  is DENIED via the canonical single-mechanism contract (permissionDecision=
  "deny" JSON on stdout, exit 0 — NOT exit 2), and the denial names the
  concrete ``bd worktree create`` command to use instead (gate-design Rule 1:
  the escape path lives in the denial). If the hook allowed this through, the
  broken-worktree state the guard exists to prevent would recur.

  Positive control — the SAME command with NO ``.beads/`` present must be
  ALLOWED (exit 0, no decision). This is the load-bearing control: it fails the
  tempting-but-wrong "always deny git worktree add" implementation, which would
  break worktree creation in every non-beads repo on the machine.

  Walk-up control — ``.beads/`` in a PARENT directory while the command runs
  from a subdirectory must still DENY. Worktree commands are not always run
  from the repo root; an exact-cwd-only beads check would pass the simple
  negative control yet silently fail real usage.

  Settings registration — the guard is wired in settings.template.json on the
  ``Bash(git worktree add:*)`` matcher (scoped so it fires only on that command
  prefix — zero overhead on every other Bash call). Asserted against the real
  template, not the hook's internals, so a de-registration regression bites.

Assertions target externally-observable behavior (exit code, the JSON decision
the runtime acts on, the settings registration) — not private helpers — so
they are not implementation echoes.

Run from anywhere:
  python3 -m pytest claude/hooks/tests/test_beads_worktree_guard.py -v
"""

from __future__ import annotations

import io
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_hooks_dir = Path(__file__).resolve().parent.parent

_spec = importlib.util.spec_from_file_location(
    "beads_worktree_guard",
    _hooks_dir / "beads_worktree_guard.py",
)
assert _spec is not None and _spec.loader is not None
hook = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = hook
_spec.loader.exec_module(hook)


_SETTINGS_TEMPLATE = (
    Path(__file__).resolve().parents[2] / "claude" / "settings.template.json"
)
if not _SETTINGS_TEMPLATE.is_file():
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "settings.template.json"
        if candidate.is_file():
            _SETTINGS_TEMPLATE = candidate
            break

_EXPECTED_MATCHER = "Bash(git worktree add:*)"


def _run(command: str, cwd: Path) -> tuple[int, dict, str]:
    """Drive the hook's main() with a Bash PreToolUse payload.

    Returns (exit_code, parsed_stdout_json, raw_stdout). A deny is signaled by
    a permissionDecision="deny" JSON document on stdout plus exit 0 (NOT exit
    2). An allow is exit 0 with empty stdout.
    """
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(cwd),
    }
    stdout_capture = io.StringIO()
    exit_code = 0
    with (
        patch("sys.stdin", io.StringIO(json.dumps(payload))),
        patch("sys.stdout", stdout_capture),
        patch.object(hook, "_record_signal", lambda *a, **k: None),
    ):
        try:
            ret = hook.main()
            exit_code = ret if ret is not None else 0
        except SystemExit as exc:
            exit_code = exc.code if isinstance(exc.code, int) else 1

    out = stdout_capture.getvalue().strip()
    parsed = json.loads(out) if out else {}
    return exit_code, parsed, out


def _make_beads_project(tmp_path: Path) -> Path:
    (tmp_path / ".beads").mkdir()
    return tmp_path


def _make_git_beads_project(tmp_path: Path) -> Path:
    repo = _make_beads_project(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / ".gitignore").write_text(".worktrees/\n", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    return repo


# ---------------------------------------------------------------------------
# Negative control: git worktree add in a beads project is denied + redirected.
# ---------------------------------------------------------------------------

def test_worktree_add_in_beads_project_is_denied_and_redirected(tmp_path):
    proj = _make_beads_project(tmp_path)
    exit_code, parsed, raw = _run("git worktree add ../wt -b feature/x", proj)

    # Canonical deny mechanism: the JSON decision carries the block; exit 0.
    assert exit_code == 0, (
        "deny is signaled by the stdout JSON decision, not exit 2"
    )
    assert raw.count('"permissionDecision"') == 1, (
        f"deny must be emitted exactly once; stdout was: {raw!r}"
    )
    out = parsed["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny"

    reason = out["permissionDecisionReason"]
    # The escape path must be IN the denial (gate-design Rule 1): the concrete
    # correct command, not just prose telling the agent it did something wrong.
    assert "bd worktree create" in reason, (
        f"denial must redirect to `bd worktree create`; got: {reason!r}"
    )


def test_denial_injects_the_concrete_path_and_branch(tmp_path):
    """The redirect should be actionable: it carries the SAME path and branch
    the agent tried, so the agent can run the corrected command verbatim
    (serena_preference_gate-style param injection)."""
    proj = _make_beads_project(tmp_path)
    _, parsed, _ = _run("git worktree add ../my-wt -b reticle-xyz", proj)
    reason = parsed["hookSpecificOutput"]["permissionDecisionReason"]
    assert "../my-wt" in reason and "reticle-xyz" in reason, (
        f"denial should echo the attempted path/branch; got: {reason!r}"
    )


# ---------------------------------------------------------------------------
# Positive control: git worktree add with NO .beads/ passes through.
# ---------------------------------------------------------------------------

def test_worktree_add_in_non_beads_project_is_allowed(tmp_path):
    """The load-bearing control. A plain git repo (no .beads/) must NOT be
    blocked — otherwise the guard breaks worktree creation everywhere. Fails
    the fragile 'always deny git worktree add' implementation."""
    # tmp_path has no .beads/ directory.
    exit_code, parsed, raw = _run("git worktree add ../wt -b foo", tmp_path)
    assert exit_code == 0
    assert parsed == {}, f"non-beads worktree add must pass untouched; got: {raw!r}"


# ---------------------------------------------------------------------------
# Walk-up control: .beads/ in a parent, command run from a subdirectory.
# ---------------------------------------------------------------------------

def test_beads_detected_from_subdirectory(tmp_path):
    proj = _make_beads_project(tmp_path)
    subdir = proj / "recorder" / "src"
    subdir.mkdir(parents=True)
    exit_code, parsed, _ = _run("git worktree add ../wt -b foo", subdir)
    assert exit_code == 0
    assert parsed.get("hookSpecificOutput", {}).get("permissionDecision") == "deny", (
        "a beads project must be detected from a nested subdirectory, not only "
        "from the exact cwd"
    )


# ---------------------------------------------------------------------------
# Settings registration: the guard is wired on the scoped matcher.
# ---------------------------------------------------------------------------

def test_guard_is_registered_on_scoped_worktree_matcher():
    assert _SETTINGS_TEMPLATE.is_file(), (
        f"settings template not found at {_SETTINGS_TEMPLATE}"
    )
    settings = json.loads(_SETTINGS_TEMPLATE.read_text(encoding="utf-8"))
    matchers = set()
    for entry in settings.get("hooks", {}).get("PreToolUse", []):
        commands = [h.get("command", "") for h in entry.get("hooks", [])]
        if any("beads_worktree_guard.py" in c for c in commands):
            matchers.add(entry.get("matcher", ""))
    assert _EXPECTED_MATCHER in matchers, (
        f"beads_worktree_guard.py must be registered on matcher "
        f"{_EXPECTED_MATCHER!r}; found registrations on: {matchers}"
    )


# ---------------------------------------------------------------------------
# Defensive: malformed stdin fails OPEN (never wedge the tool pipeline).
# ---------------------------------------------------------------------------

def test_malformed_stdin_fails_open():
    stdout_capture = io.StringIO()
    exit_code = 0
    with (
        patch("sys.stdin", io.StringIO("not json{{{")),
        patch("sys.stdout", stdout_capture),
        patch.object(hook, "_record_signal", lambda *a, **k: None),
    ):
        try:
            ret = hook.main()
            exit_code = ret if ret is not None else 0
        except SystemExit as exc:
            exit_code = exc.code if isinstance(exc.code, int) else 1
    assert exit_code == 0
    assert stdout_capture.getvalue().strip() == ""


# ===========================================================================
# A1 — detection escapes: `worktree add` reached through intervening global
# flags or inside a compound command must still DENY in a beads project.
#
# The incident: an agent ran `git -C /private/tmp/main-tree ... worktree`-style
# commands that the prefix-anchored regex (`^\s*git\s+worktree\s+add`) and the
# prefix-scoped matcher both miss. These pin the closed form.
# ===========================================================================

# Forms that must be DENIED inside a beads project. Each escapes the current
# `^git worktree add` anchor.
A1_ESCAPING_CREATE_FORMS = [
    "git -C /tmp/main worktree add ../wt -b foo",
    "git --git-dir=/tmp/main/.git worktree add ../wt -b foo",
    "cd /tmp/main && git worktree add ../wt -b foo",
    "env GIT_PAGER=cat git worktree add ../wt -b foo",
    "  git    worktree   add   ../wt -b foo",  # extra whitespace, still first git
]


@pytest.mark.parametrize("command", A1_ESCAPING_CREATE_FORMS)
def test_escaping_worktree_add_forms_are_denied(command, tmp_path):
    proj = _make_beads_project(tmp_path)
    exit_code, parsed, raw = _run(command, proj)
    assert exit_code == 0
    decision = parsed.get("hookSpecificOutput", {}).get("permissionDecision")
    assert decision == "deny", (
        f"A1: `worktree add` via flags/compound must be denied in a beads "
        f"project: {command!r}; stdout was {raw!r}"
    )
    assert "bd worktree create" in raw, "A1 denial must still name the redirect"


# Innocent git commands must NOT be denied even after the matcher widens to
# Bash(git:*). These are the load-bearing negative controls for A1 over-reach.
A1_INNOCENT_GIT = [
    "git log --oneline -5",
    "git status",
    "git diff HEAD~1",
    "git branch --list",
    "git fetch origin",
]


@pytest.mark.parametrize("command", A1_INNOCENT_GIT)
def test_innocent_git_not_denied_in_beads_project(command, tmp_path):
    proj = _make_beads_project(tmp_path)
    exit_code, parsed, raw = _run(command, proj)
    assert exit_code == 0
    assert parsed == {}, (
        f"A1: innocent git command must pass untouched even in a beads project: "
        f"{command!r}; got {raw!r}"
    )


# ===========================================================================
# B1 — `worktree add` as STRING CONTENT (not a subcommand) must NOT deny.
#
# The wide `Bash(git:*)` matcher routes every git call through this hook, where
# `_WORKTREE_ADD_RE` (`\bgit\b[^\n|;&]*?\bworktree\s+add\b`) matches the literal
# token sequence "worktree" ... "add" ANYWHERE after `git` — including inside a
# quoted argument. Empirically confirmed denied (wrongly):
#   git log --grep="worktree add"
# A developer searching their own history for the phrase, or committing docs that
# mention it, gets a `bd worktree create` redirect that makes no sense in context.
#
# The fix direction (pinned by OUTCOME, not implementation): "worktree" then "add"
# must be POSITIONAL git subcommand tokens (shlex tokenization, skipping git global
# flags), never content inside a quoted / flag argument. A real `git worktree add`
# invocation still denies; the phrase as an argument value passes.
# ===========================================================================

# Innocents: `worktree add` appears only as ARGUMENT CONTENT, never as the git
# subcommand. Each MUST be allowed even inside a beads project.
B1_STRING_ARG_INNOCENTS = [
    'git log --grep="worktree add"',          # the empirically-confirmed FP
    'git log --grep "worktree add"',          # space form of the same flag
    'git commit -m "docs: worktree add guide"',  # phrase in a commit message
    'git grep "worktree add"',                # searching tree content for the phrase
    'git log -S "git worktree add"',          # pickaxe search for the phrase
]


@pytest.mark.parametrize("command", B1_STRING_ARG_INNOCENTS)
def test_worktree_add_as_string_argument_not_denied(command, tmp_path):
    """B1 NEGATIVE CONTROL: `worktree add` inside a quoted argument is not a real
    worktree-create invocation — it must PASS even in a beads project. This is the
    load-bearing control: it fails the current substring regex, which matches the
    phrase anywhere after `git`."""
    proj = _make_beads_project(tmp_path)
    exit_code, parsed, raw = _run(command, proj)
    assert exit_code == 0
    assert parsed == {}, (
        f"B1: `worktree add` as a quoted argument must pass untouched in a beads "
        f"project (it is not a real worktree-create): {command!r}; got {raw!r}"
    )


def test_echo_worktree_add_is_not_git_allowed(tmp_path):
    """B1 NEGATIVE CONTROL: `echo git worktree add` is not a git invocation at all
    (the leading word is `echo`). It must PASS — defeats a fix that keys on the
    bare tokens `worktree add` appearing anywhere rather than on `git` being the
    actual command."""
    proj = _make_beads_project(tmp_path)
    exit_code, parsed, raw = _run("echo git worktree add", proj)
    assert exit_code == 0
    assert parsed == {}, (
        f"B1: `echo git worktree add` is not a git command and must pass; got {raw!r}"
    )


# Positives: a REAL `git worktree add` where the two tokens ARE the positional
# git subcommand. Each MUST stay denied (the guard's whole reason to exist).
B1_REAL_CREATE_FORMS = [
    "git worktree add ../x",
    "git -C /repo worktree add ../x",
    "git --git-dir=/repo/.git worktree add ../x",
    "cd /repo && git worktree add ../x",
]


@pytest.mark.parametrize("command", B1_REAL_CREATE_FORMS)
def test_real_worktree_add_subcommand_still_denied(command, tmp_path):
    """B1 POSITIVE CONTROL: a genuine `git worktree add` (the tokens are the git
    SUBCOMMAND, possibly after global flags / a `cd &&`) must still DENY in a beads
    project. Guards against a B1 fix that over-corrects into letting real
    invocations through."""
    proj = _make_beads_project(tmp_path)
    exit_code, parsed, raw = _run(command, proj)
    assert exit_code == 0
    decision = parsed.get("hookSpecificOutput", {}).get("permissionDecision")
    assert decision == "deny", (
        f"B1: a real `git worktree add` subcommand must still deny in a beads "
        f"project: {command!r}; stdout was {raw!r}"
    )
    assert "bd worktree create" in raw, "B1: real-create denial must name the redirect"


def test_unparseable_command_line_does_not_deny(tmp_path):
    """B1 SAFE-DEFAULT: a command line shlex cannot tokenize (unbalanced quote)
    must NOT deny. Once the wide `Bash(git:*)` matcher routes every git call
    through this hook, a tokenization error must fail OPEN (allow) — this hook now
    fires on EVERY git call, so a crash-or-deny default on weird input would wedge
    ordinary git usage. The phrase is present inside the unbalanced quote precisely
    to pin that the shlex error, not the absence of the phrase, drives the allow:
    a tokenizing fix must treat an unparseable line as allow, never deny."""
    proj = _make_beads_project(tmp_path)
    # Unbalanced quote — shlex.split raises ValueError. The phrase is INSIDE the
    # broken quote, so a fix that tokenizes must hit the error path and fail open.
    exit_code, parsed, raw = _run('git log --grep="worktree add unterminated', proj)
    assert exit_code == 0
    assert parsed == {}, (
        f"B1: an unparseable git command line must fail open (allow), not deny; "
        f"got {raw!r}"
    )


def test_guard_registered_on_wide_git_matcher():
    """A1 STRUCTURAL FIX: the prefix matcher `Bash(git worktree add:*)` means the
    runtime never even invokes the hook for `git -C x worktree add`. Closing A1
    requires a SECOND matcher `Bash(git:*)` so those forms reach the hook. This
    pins that registration; without it, no in-hook regex can catch `git -C`.

    The existing narrow matcher must ALSO remain (test_guard_is_registered_on_
    scoped_worktree_matcher still asserts it) — this is additive."""
    assert _SETTINGS_TEMPLATE.is_file()
    settings = json.loads(_SETTINGS_TEMPLATE.read_text(encoding="utf-8"))
    matchers = set()
    for entry in settings.get("hooks", {}).get("PreToolUse", []):
        commands = [h.get("command", "") for h in entry.get("hooks", [])]
        if any("beads_worktree_guard.py" in c for c in commands):
            matchers.add(entry.get("matcher", ""))
    assert "Bash(git:*)" in matchers, (
        "A1: beads_worktree_guard.py must ALSO be registered on the wide "
        "`Bash(git:*)` matcher so `git -C x worktree add` reaches the hook; "
        f"found registrations on: {matchers}"
    )


def test_a1_documented_falsepositive_on_quoted_string(tmp_path):
    """DOCUMENTED LIMITATION (brief A1): a regex over the command string cannot
    distinguish a real `worktree add` from one inside a quoted echo without full
    shell parsing. The brief's position is to accept the cheap false-positive
    rather than risk a false-negative. We pin the DECIDED behavior: a `git
    worktree add` token appearing after a real `&&` separator DENIES (it is a real
    invocation). We deliberately do NOT assert that `echo "git worktree add"`
    passes — that would pin the fragile shell-parse the brief declines to build."""
    proj = _make_beads_project(tmp_path)
    # A real chained invocation (the thing we MUST catch) — not a quoted string.
    exit_code, parsed, _ = _run("true && git worktree add ../wt -b foo", proj)
    assert exit_code == 0
    assert parsed.get("hookSpecificOutput", {}).get("permissionDecision") == "deny", (
        "A1: a real `worktree add` after `&&` must be denied (false-negatives are "
        "the failure mode the brief refuses to risk)"
    )


# ===========================================================================
# A2 — linked-worktree finishing: Beads 1.0.5 resolves tracker state through
# Git's common directory, without requiring a `.beads/redirect` marker. The
# creation guard above still redirects new `git worktree add` commands, but an
# already-linked worktree must be able to commit, push, merge, or rebase.
# ===========================================================================

def _make_redirectless_beads_worktree(tmp_path: Path) -> tuple[Path, Path]:
    """Fabricate the minimal linked layout used by Beads 1.0.5 common-dir
    discovery: the primary checkout has `.beads/`; the worktree has no redirect
    or local Beads files."""
    main = tmp_path / "main"
    (main / ".beads").mkdir(parents=True)
    (main / ".git" / "worktrees" / "wt").mkdir(parents=True)
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {main}/.git/worktrees/wt\n", encoding="utf-8")
    return main, wt


def _make_actual_redirectless_beads_worktree(tmp_path: Path) -> tuple[Path, Path]:
    """Create a real Git linked worktree that inherits tracked Beads files."""
    main = tmp_path / "main"
    main.mkdir()
    (main / ".beads").mkdir()
    (main / ".beads" / "metadata.json").write_text(
        '{"project_id": "project-primary"}\n', encoding="utf-8"
    )
    (main / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=main, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=main, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=main, check=True)
    subprocess.run(["git", "add", "."], cwd=main, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=main, check=True)
    wt = tmp_path / "wt"
    subprocess.run(["git", "worktree", "add", "--detach", str(wt), "HEAD"], cwd=main, check=True)
    common_dir = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=wt,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert Path(common_dir) == main / ".git"
    assert not (wt / ".beads" / "redirect").exists()
    return main, wt


def _make_plain_git_worktree(tmp_path: Path) -> tuple[Path, Path]:
    """A linked worktree whose MAIN repo has NO .beads/ — a plain-git multi-
    worktree repo. Operating here must NOT be denied (over-block control)."""
    main = tmp_path / "main"
    (main / ".git" / "worktrees" / "wt").mkdir(parents=True)
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {main}/.git/worktrees/wt\n", encoding="utf-8")
    return main, wt


def _run_op(command: str, cwd: Path) -> tuple[int, dict, str]:
    """Drive the registered hook with a state-changing Git command."""
    return _run(command, cwd)


def test_state_changing_op_in_actual_redirectless_beads_worktree_is_allowed(tmp_path):
    """A real `git worktree add` layout inherits tracked Beads files and uses
    Git's common directory; the finishing command must pass unchanged."""
    main, wt = _make_actual_redirectless_beads_worktree(tmp_path)
    _, parsed, raw = _run_op(f"git -C {wt} commit -am docs", main)
    assert parsed == {}, f"linked Beads worktree must allow commit; got {raw!r}"


@pytest.mark.parametrize("command", [
    "git -C {wt} checkout -b feature/x",
    "git -C {wt} pull origin main",
    "git -C {wt} merge origin/main",
    "git -C {wt} rebase main",
    "git -C {wt} commit -am wip",
    "git -C {wt} push origin main",
])
def test_state_changing_op_in_redirectless_beads_worktree_is_allowed(command, tmp_path):
    """The hook must not block any supported state-changing Git workflow after
    a linked worktree already exists."""
    main, wt = _make_redirectless_beads_worktree(tmp_path)
    cmd = command.format(wt=wt)
    _, parsed, raw = _run_op(cmd, main)
    assert parsed == {}, (
        f"redirect-less Beads worktree must allow {cmd!r}; got {raw!r}"
    )


def test_plain_git_worktree_operation_allowed(tmp_path):
    """OVER-BLOCK NEGATIVE CONTROL: a worktree whose MAIN repo has NO .beads/ is a
    plain-git multi-worktree repo; operating there must PASS. Defeats 'worktree =
    .git-file -> deny' which ignores the main-repo .beads/ check."""
    main, wt = _make_plain_git_worktree(tmp_path)
    exit_code, parsed, raw = _run_op("git checkout -b feature/x", wt)
    assert parsed == {}, (
        f"state-changing git in a plain worktree must pass; got {raw!r}"
    )


# ===========================================================================
# B2 — `bd worktree create` target location guard.
#
# A bd-created worktree is beads-correct, but placing it inside the repo at a
# visible path makes code indexers scan it as source. The guard must steer to an
# ignored or outside-repo location without pretending one generated name is the
# only valid answer.
# ===========================================================================

def test_repo_ignores_worktrees_directory():
    root = Path(__file__).resolve().parents[3]
    text = (root / ".gitignore").read_text(encoding="utf-8")
    assert ".worktrees/" in text


def test_bd_worktree_create_inside_visible_repo_path_denied_with_policy_message(tmp_path):
    repo = _make_git_beads_project(tmp_path)

    exit_code, parsed, raw = _run(
        "bd worktree create reconcile-bookings-finance -b DWDEV-123",
        repo,
    )

    assert exit_code == 0
    out = parsed["hookSpecificOutput"]
    assert out["permissionDecision"] == "deny", raw
    reason = out["permissionDecisionReason"]
    assert "not ignored by git" in reason
    assert "For the same slug" in reason
    assert "bd worktree create .worktrees/reconcile-bookings-finance -b DWDEV-123" in reason
    assert "choosing another ignored or outside-repo path is also fine" in reason
    assert "Use `bd worktree create .worktrees/reconcile-bookings-finance" not in reason


def test_bd_worktree_create_under_ignored_worktrees_dir_allowed(tmp_path):
    repo = _make_git_beads_project(tmp_path)

    exit_code, parsed, raw = _run(
        "bd worktree create .worktrees/reconcile-bookings-finance -b DWDEV-123",
        repo,
    )

    assert exit_code == 0
    assert parsed == {}, raw


def test_bd_worktree_create_outside_repo_allowed(tmp_path):
    repo = _make_git_beads_project(tmp_path)

    exit_code, parsed, raw = _run(
        "bd worktree create ../reconcile-bookings-finance -b DWDEV-123",
        repo,
    )

    assert exit_code == 0
    assert parsed == {}, raw


def test_bd_worktree_location_placeholder_waiver_still_denies(tmp_path):
    repo = _make_git_beads_project(tmp_path)

    _, parsed, raw = _run(
        "bd worktree create reconcile-bookings-finance -b DWDEV-123 "
        "# beads-worktree-waiver: <reason>",
        repo,
    )

    assert parsed.get("hookSpecificOutput", {}).get("permissionDecision") == "deny", raw


def test_bd_worktree_location_substantive_waiver_allows(tmp_path):
    repo = _make_git_beads_project(tmp_path)

    exit_code, parsed, raw = _run(
        "bd worktree create reconcile-bookings-finance -b DWDEV-123 "
        "# beads-worktree-waiver: reproducing old bad layout for cleanup",
        repo,
    )

    assert exit_code == 0
    assert parsed == {}, raw
