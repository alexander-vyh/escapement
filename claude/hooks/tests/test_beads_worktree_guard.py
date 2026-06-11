"""Behavioral tests for claude/hooks/beads_worktree_guard.py.

This hook protects one business outcome: in a beads-managed project, a worktree
is never created with bare ``git worktree add`` — which produces a broken
worktree (empty ``.beads/`` with no Dolt database, ``bd`` commands failing).
The agent is mechanically redirected to ``bd worktree create``, which wires up
the ``.beads/redirect`` so the worktree shares the main repo's database.

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
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

_hooks_dir = Path(__file__).resolve().parent.parent
if str(_hooks_dir) not in sys.path:
    sys.path.insert(0, str(_hooks_dir))

import beads_worktree_guard as hook  # noqa: E402


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
# A2 — foreign-worktree-operation guard: a state-changing git command targeting
# a linked worktree whose MAIN repo has .beads/ but which lacks .beads/redirect
# must DENY. Read-only git must pass. Plain-git worktrees (main has no .beads/)
# must pass.
#
# Integration point (same hook vs sibling hook) is the developer's choice; these
# tests pin the OBSERVABLE contract by driving the registered worktree guard's
# main() with a fabricated worktree layout. They are gated behind a tripwire so
# they go RED until the behavior lands rather than silently skip.
# ===========================================================================

def _make_foreign_beads_worktree(tmp_path: Path, *, with_redirect: bool) -> tuple[Path, Path]:
    """Fabricate a linked-worktree layout WITHOUT real git.

    Returns (main_repo, worktree). The worktree's `.git` is a FILE containing
    `gitdir: <main>/.git/worktrees/wt` (the real git worktree marker). The main
    repo has a `.beads/` dir. `with_redirect` controls whether the worktree has
    `.beads/redirect` (a bd-created worktree) — when False it is the broken
    foreign worktree the guard must catch."""
    main = tmp_path / "main"
    (main / ".beads").mkdir(parents=True)
    (main / ".git" / "worktrees" / "wt").mkdir(parents=True)
    wt = tmp_path / "wt"
    wt.mkdir()
    (wt / ".git").write_text(f"gitdir: {main}/.git/worktrees/wt\n", encoding="utf-8")
    if with_redirect:
        (wt / ".beads").mkdir()
        (wt / ".beads" / "redirect").write_text(str(main / ".beads"), encoding="utf-8")
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


# Tripwire: the foreign-worktree-operation guard is new behavior. We detect it via
# a sentinel attribute the developer exposes (a module-level callable named
# `evaluate_worktree_operation` on the hook, OR a sibling module). Until it exists,
# this single test stays RED so A2 can't be silently skipped; the detailed A2
# cases skip cleanly until then.
_A2_HOOK = hook  # same-hook integration is the default expectation
_have_a2 = hasattr(_A2_HOOK, "evaluate_worktree_operation") or hasattr(
    _A2_HOOK, "_is_foreign_beads_worktree"
)
requires_a2 = pytest.mark.skipif(
    not _have_a2,
    reason="foreign-worktree-operation guard (A2) not yet implemented",
)


def test_a2_foreign_worktree_guard_exists():
    """TRIPWIRE: unconditional RED until A2 lands, so the skip-gated A2 cases
    cannot pass silently as a green suite. The developer turns this green by
    exposing the foreign-worktree-operation check on the guard (or a sibling)."""
    assert _have_a2, (
        "A2 not implemented: expose evaluate_worktree_operation(command, cwd) (or "
        "_is_foreign_beads_worktree) so a state-changing git command in a foreign "
        "beads worktree is denied"
    )


def _run_op(command: str, cwd: Path) -> tuple[int, dict, str]:
    """Drive the worktree-operation guard. Reuses the PreToolUse payload shape;
    the same hook main() is expected to also evaluate operation commands once A2
    lands. (If the developer ships a sibling hook, point this at it — the asserted
    OUTCOME is unchanged.)"""
    return _run(command, cwd)


@requires_a2
def test_state_changing_op_in_foreign_beads_worktree_denied(tmp_path):
    """POSITIVE CONTROL / the incident: `git checkout -b` inside a foreign beads
    worktree (.git file -> main .beads/, no redirect) must DENY and name the
    recovery path."""
    main, wt = _make_foreign_beads_worktree(tmp_path, with_redirect=False)
    exit_code, parsed, raw = _run_op("git checkout -b feature/x", wt)
    assert exit_code == 0
    decision = parsed.get("hookSpecificOutput", {}).get("permissionDecision")
    assert decision == "deny", (
        f"A2: state-changing git in a foreign beads worktree must deny; got {raw!r}"
    )
    assert "bd worktree create" in raw, "A2 denial must name the recovery path"
    assert "bd init" in raw.lower(), "A2 denial must warn against bd init in a worktree"


@requires_a2
@pytest.mark.parametrize("command", [
    "git -C {wt} checkout -b feature/x",
    "git -C {wt} pull origin main",
    "git -C {wt} merge origin/main",
    "git -C {wt} rebase main",
    "git -C {wt} commit -am wip",
])
def test_state_changing_op_via_dash_C_denied(command, tmp_path):
    """A2 via `-C <foreign-wt>` from outside the worktree — the exact incident
    invocation shape."""
    main, wt = _make_foreign_beads_worktree(tmp_path, with_redirect=False)
    cmd = command.format(wt=wt)
    exit_code, parsed, raw = _run_op(cmd, main)
    assert parsed.get("hookSpecificOutput", {}).get("permissionDecision") == "deny", (
        f"A2: `-C` into a foreign beads worktree must deny: {cmd!r}; got {raw!r}"
    )


@requires_a2
@pytest.mark.parametrize("command", [
    "git -C {wt} log --oneline",
    "git -C {wt} status",
    "git -C {wt} diff",
    "git -C {wt} show HEAD",
])
def test_readonly_git_in_foreign_worktree_allowed(command, tmp_path):
    """OVER-BLOCK NEGATIVE CONTROL: read-only git in a foreign beads worktree must
    PASS. Defeats 'deny everything in the foreign worktree'."""
    main, wt = _make_foreign_beads_worktree(tmp_path, with_redirect=False)
    cmd = command.format(wt=wt)
    exit_code, parsed, raw = _run_op(cmd, main)
    assert parsed == {}, (
        f"A2: read-only git in a foreign worktree must pass: {cmd!r}; got {raw!r}"
    )


@requires_a2
def test_plain_git_worktree_operation_allowed(tmp_path):
    """OVER-BLOCK NEGATIVE CONTROL: a worktree whose MAIN repo has NO .beads/ is a
    plain-git multi-worktree repo; operating there must PASS. Defeats 'worktree =
    .git-file -> deny' which ignores the main-repo .beads/ check."""
    main, wt = _make_plain_git_worktree(tmp_path)
    exit_code, parsed, raw = _run_op("git checkout -b feature/x", wt)
    assert parsed == {}, (
        f"A2: state-changing git in a PLAIN-git worktree must pass; got {raw!r}"
    )


@requires_a2
def test_bd_created_worktree_operation_allowed(tmp_path):
    """NEGATIVE CONTROL: a properly bd-created worktree (has .beads/redirect) is
    NOT broken; operating there must PASS. The guard fires only on the BROKEN
    layout (no redirect)."""
    main, wt = _make_foreign_beads_worktree(tmp_path, with_redirect=True)
    exit_code, parsed, raw = _run_op("git checkout -b feature/x", wt)
    assert parsed == {}, (
        f"A2: a bd-created worktree (with redirect) must not be denied; got {raw!r}"
    )
