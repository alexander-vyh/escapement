"""shell_write_gate: a file changed through the shell owes what an Edit owes.

In a 25-run replay, 3 of 5 Escapement runs wrote every change through Bash
heredocs and met zero gates, because tdd-gate and the oracle-brief gate match
only Write/Edit/apply_patch. This hook reads the working tree after each Bash
call instead of the command, so how the file was written does not matter.

Every case really runs a shell command in a scratch repo, then feeds the hook
the Claude PostToolUse payload for it. Wrong implementations each case rejects:

  - a regex on `cat >`: the writes here are a python heredoc, `sed -i`, and a
    script whose command line never names the file;
  - firing on every Bash call: a later unrelated `ls` must be silent;
  - ignoring untracked files: a brand-new module must be reported;
  - treating tests/ as behaviour code: a test-only change owes no TDD nudge;
  - firing on anything dirty: a docs change is the positive control;
  - blaming the checkout instead of the session: many sessions share one
    checkout, so dirt that was there before this session's command, or that
    another session wrote between its commands, is not this session's write.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / "shell_write_gate.py"

BRIEF = """\
## Business invariant
The user must receive the discounted total for an eligible order.
## Independent source of truth
The published price list is the source of truth for the expected value.
## Solution constraints
The pricing API must remain backward compatible and stay pure.
## Invalid solution classes
Hardcoding the expected total is invalid and must be rejected.
## Fragile implementation to reject
A shortcut that only handles the single fixture order is fragile.
## Negative control
An ineligible order must be rejected without any discount applied.
## Positive control
An eligible order with a valid code passes with the discount present.
## Missing/unresolved handling
A missing price list must fail loudly and block the total.
## Final outcome verification
Run the pricing test command and inspect the computed totals it prints.
"""


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A committed Python project with tests, nothing dirty."""
    root = tmp_path / "project"
    for name, text in {
        "pyproject.toml": "[project]\nname = 'demo'\n",
        "src/app.py": "VALUE = 1\n",
        "tests/test_app.py": "def test_value():\n    assert True\n",
        "docs/README.md": "demo\n",
    }.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "-c", "user.email=t@t", "-c", "user.name=t", "add", "-A")
    _git(root, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")
    return root


@pytest.fixture
def env(tmp_path: Path) -> dict:
    state = tmp_path / "state"
    state.mkdir()
    clean = {k: v for k, v in os.environ.items() if not k.startswith(("ESCAPEMENT_", "BEADS_"))}
    clean.update(HARNESS_ROOT=str(state), GATE_SIGNAL_FALLBACK_DIR=str(state))
    return clean


class Shell:
    """One session: the hook before a real shell command, the command, the hook after.

    `pre=False` is a host that delivers only the PostToolUse half.
    """

    def __init__(self, repo: Path, env: dict, *, pre: bool = True) -> None:
        self.repo, self.env, self.session, self.pre = repo, env, f"s-{uuid.uuid4()}", pre

    def _hook(self, event: str, command: str) -> dict | None:
        payload = {
            "session_id": self.session,
            "cwd": str(self.repo),
            "hook_event_name": event,
            "tool_name": "Bash",
            "tool_input": {"command": command},
        }
        if event == "PostToolUse":
            payload["tool_response"] = {"stdout": "", "stderr": "", "interrupted": False}
        elif event == "PostToolUseFailure":
            payload["error"] = "Exit code 1"
        proc = subprocess.run([sys.executable, "-B", str(HOOK)], input=json.dumps(payload),
                              capture_output=True, text=True, env=self.env, timeout=60)
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout) if proc.stdout.strip() else None

    def bash(self, command: str) -> dict | None:
        if self.pre:
            assert self._hook("PreToolUse", command) is None, "the snapshot never blocks"
        # Claude sends a command that exits non-zero to PostToolUseFailure.
        failed = subprocess.run(["bash", "-c", command], cwd=self.repo).returncode != 0
        return self._hook("PostToolUseFailure" if failed else "PostToolUse", command)


def _feedback(output: dict | None) -> str:
    """What Claude feeds back to the model after the Bash call, else fail."""
    assert output is not None, "expected the shell write to be reported"
    hook = output.get("hookSpecificOutput") or {}
    if hook.get("hookEventName") == "PostToolUseFailure":
        assert hook.get("additionalContext"), output
        return hook["additionalContext"]
    assert output.get("decision") == "block", output
    return output["reason"]


HEREDOC = "python3 - <<'PY'\nimport pathlib\np = pathlib.Path('src/app.py')\np.write_text(p.read_text().replace('1', '2'))\nPY"


def test_python_heredoc_write_owes_a_test_and_a_brief(repo, env):
    reason = _feedback(Shell(repo, env).bash(HEREDOC))
    assert "TDD" in reason and "src/app.py" in reason
    assert "test-oracle-brief.md" in reason


def test_sed_in_place_write_is_seen(repo, env):
    reason = _feedback(Shell(repo, env).bash("sed -i.bak 's/1/3/' src/app.py && rm src/app.py.bak"))
    assert "src/app.py" in reason


def test_a_script_that_never_names_the_file_is_seen(repo, env, tmp_path):
    script = tmp_path / "gen.py"
    script.write_text("import pathlib\npathlib.Path('src/app.py').write_text('VALUE = 9\\n')\n")
    reason = _feedback(Shell(repo, env).bash(f"python3 {script}"))
    assert "src/app.py" in reason


def test_an_untracked_new_module_is_seen(repo, env):
    reason = _feedback(Shell(repo, env).bash("cat > src/pricing.py <<'EOF'\nRATE = 2\nEOF"))
    assert "src/pricing.py" in reason


def test_reported_once_not_on_every_later_bash_call(repo, env):
    shell = Shell(repo, env)
    _feedback(shell.bash(HEREDOC))
    assert shell.bash("ls") is None, "an unchanged debt must not repeat on every call"
    assert shell.bash(HEREDOC) is None, "rewriting the same file is the same transition"


def test_a_second_file_is_a_new_transition(repo, env):
    shell = Shell(repo, env)
    _feedback(shell.bash(HEREDOC))
    reason = _feedback(shell.bash("echo 'RATE = 2' > src/pricing.py"))
    assert "src/pricing.py" in reason


def test_docs_write_is_silent(repo, env):
    """Positive control: an exempt file owes nothing."""
    assert Shell(repo, env).bash("echo more >> docs/README.md") is None


def test_test_only_write_owes_no_tdd_nudge(repo, env):
    """A test file is the evidence, not the debt: TDD has nothing to say."""
    (repo / ".agent" / "runtime").mkdir(parents=True)
    (repo / ".agent" / "runtime" / "test-oracle-brief.md").write_text(BRIEF)
    assert Shell(repo, env).bash("echo 'def test_more(): pass' >> tests/test_app.py") is None


def test_impl_with_tests_and_valid_brief_is_silent(repo, env):
    """Positive control: the evidence the edit path asks for is present."""
    (repo / ".agent" / "runtime").mkdir(parents=True)
    (repo / ".agent" / "runtime" / "test-oracle-brief.md").write_text(BRIEF)
    shell = Shell(repo, env)
    assert shell.bash("echo 'def test_two(): pass' >> tests/test_app.py") is None
    assert shell.bash(HEREDOC) is None


def test_with_tests_but_no_brief_only_the_brief_is_owed(repo, env):
    shell = Shell(repo, env)
    shell.bash("echo 'def test_two(): pass' >> tests/test_app.py")
    reason = _feedback(shell.bash(HEREDOC))
    assert "test-oracle-brief.md" in reason
    assert "TDD" not in reason


def test_debt_reopens_after_it_was_paid(repo, env):
    """Once tests resolve the TDD debt the memory goes, so a later relapse speaks."""
    shell = Shell(repo, env)
    (repo / ".agent" / "runtime").mkdir(parents=True)
    (repo / ".agent" / "runtime" / "test-oracle-brief.md").write_text(BRIEF)
    assert "TDD" in _feedback(shell.bash(HEREDOC))
    assert shell.bash("echo 'def test_two(): pass' >> tests/test_app.py") is None
    _git(repo, "checkout", "--", "tests/test_app.py")
    assert "TDD" in _feedback(shell.bash("echo 'X = 1' >> src/app.py"))


def test_outside_a_repo_is_silent(env, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert Shell(plain, env).bash("echo 'X = 1' > app.py") is None


def test_without_tdd_gate_the_brief_is_still_owed(repo, env, tmp_path, monkeypatch):
    """Open PR #250 retires tdd-gate and _advisory_dedupe: the brief check must not die with them."""
    import shutil
    hooks = tmp_path / "hooks"
    shutil.copytree(HOOK.parent, hooks,
                    ignore=shutil.ignore_patterns("tdd-gate.py", "_advisory_dedupe.py", "tests"))
    monkeypatch.setattr(sys.modules[__name__], "HOOK", hooks / HOOK.name)
    reason = _feedback(Shell(repo, env).bash(HEREDOC))
    assert "test-oracle-brief.md" in reason and "src/app.py" in reason
    assert "TDD" not in reason


# --- Whose write is it? Many sessions share one checkout. -------------------

def test_dirt_from_before_the_session_is_not_blamed(repo, env):
    """Negative control: src/app.py was already dirty when this session started."""
    (repo / "src" / "app.py").write_text("VALUE = 7\n")
    (repo / "src" / "legacy.py").write_text("OLD = 1\n")
    shell = Shell(repo, env)
    assert shell.bash("ls") is None
    assert shell.bash("echo more >> docs/README.md") is None


def test_another_sessions_writes_are_not_blamed(repo, env):
    """Session B writes between session A's commands; A's next command is innocent."""
    a, b = Shell(repo, env), Shell(repo, env)
    assert a.bash("ls") is None
    assert "src/app.py" in _feedback(b.bash(HEREDOC)), "B wrote it, so B is told"
    assert a.bash("ls") is None, "A must not be blamed for B's shell write"
    (repo / "src" / "other.py").write_text("B = 1\n")  # B again, through its Edit tool
    assert a.bash("git status --short") is None, "nor for B's edit-tool write"


def test_this_sessions_heredoc_is_held_amid_foreign_dirt(repo, env):
    """Positive control: foreign dirt exists, and this session's own write still reports."""
    (repo / "src" / "legacy.py").write_text("OLD = 1\n")
    reason = _feedback(Shell(repo, env).bash("cat > src/pricing.py <<'EOF'\nRATE = 2\nEOF"))
    assert "src/pricing.py" in reason
    assert "legacy.py" not in reason, "only this session's write is named"


def test_dirty_before_then_changed_by_this_session_is_held(repo, env):
    (repo / "src" / "app.py").write_text("VALUE = 7\n")
    shell = Shell(repo, env)
    assert shell.bash("ls") is None
    reason = _feedback(shell.bash("echo 'VALUE = 8' > src/app.py"))
    assert "src/app.py" in reason


def test_without_a_pre_snapshot_the_first_observation_is_the_baseline(repo, env):
    """A host that sends only PostToolUse: what is dirty at the first look is not
    blamed, and every later shell write in that session still is."""
    (repo / "src" / "legacy.py").write_text("OLD = 1\n")
    shell = Shell(repo, env, pre=False)
    assert shell.bash("ls") is None
    reason = _feedback(shell.bash(HEREDOC))
    assert "src/app.py" in reason and "legacy.py" not in reason
    assert _feedback(shell.bash("echo 'OLD = 2' > src/legacy.py")), "pre-dirty, then changed here"


def test_corrupt_session_state_fails_open(repo, env):
    shell = Shell(repo, env)
    assert shell.bash("ls") is None
    for path in Path(env["HARNESS_ROOT"]).rglob("*"):
        if path.is_file() and shell.session in str(path):
            path.write_text("{not json")
    shell.bash(HEREDOC)  # must not crash; the hook asserts exit 0
    assert shell.bash("ls") is None


# --- Re-review of 1487b10 ----------------------------------------------------

def test_a_write_followed_by_a_failing_command_is_held(repo, env):
    """`cat > x.py ... && pytest` going red is the bypass itself: Claude reports a
    non-zero exit as PostToolUseFailure, and the plugin must be listening there."""
    hooks = json.loads((HOOK.parents[2] / "plugins" / "escapement-claude" / "hooks"
                        / "hooks.json").read_text())["hooks"]
    assert any(item["matcher"] == "Bash" and HOOK.name in hook["command"]
               for item in hooks.get("PostToolUseFailure", []) for hook in item["hooks"])
    shell = Shell(repo, env)
    assert "src/impl.py" in _feedback(shell.bash("echo 'IMPL = 1' > src/impl.py; false"))
    assert shell.bash("ls") is None


def _git_failing_status(tmp_path: Path, env: dict) -> Path:
    """A `git` on PATH whose `status` fails while the returned marker exists."""
    real = subprocess.run(["which", "git"], capture_output=True, text=True, check=True).stdout.strip()
    bin_dir, marker = tmp_path / "fakebin", tmp_path / "git-status-fails"
    bin_dir.mkdir()
    (bin_dir / "git").write_text(
        f'#!/bin/sh\nif [ "$1" = status ] && [ -e "{marker}" ]; then exit 128; fi\n'
        f'exec "{real}" "$@"\n')
    (bin_dir / "git").chmod(0o755)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    return marker


def test_a_failed_snapshot_is_unknown_not_clean(repo, env, tmp_path):
    """git status failing before the call must not turn all existing dirt into
    this call's writes: the call is skipped and the tree re-baselined."""
    (repo / "src" / "legacy.py").write_text("OLD = 1\n")
    marker = _git_failing_status(tmp_path, env)
    marker.touch()
    shell = Shell(repo, env)
    assert shell.bash(f"rm {marker}") is None, "legacy.py is not this session's write"
    reason = _feedback(shell.bash("echo 'RATE = 2' > src/pricing.py"))
    assert "src/pricing.py" in reason and "legacy.py" not in reason


def test_write_and_commit_in_one_call_is_held(repo, env):
    reason = _feedback(Shell(repo, env).bash(
        "echo 'RATE = 2' > src/pricing.py && git add src/pricing.py && "
        "git -c user.email=t@t -c user.name=t commit -qm pricing"))
    assert "src/pricing.py" in reason


def test_a_reset_does_not_blame_the_history_it_undoes(repo, env):
    """Someone else's commit, un-done by this session's reset, is not this session's write."""
    (repo / "src" / "app.py").write_text("VALUE = 5\n")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qam", "theirs")
    shell = Shell(repo, env)
    assert shell.bash("git reset -q --soft HEAD~1") is None
    assert shell.bash("ls") is None


def test_a_huge_dirty_tree_is_skipped_not_hashed(repo, env):
    """Past 2,000 dirty paths the hook stays silent rather than hash them all."""
    junk = repo / "junk"
    junk.mkdir()
    for index in range(2001):
        (junk / f"f{index}.txt").write_text("x")
    shell = Shell(repo, env)
    assert shell.bash("ls") is None
    assert shell.bash(HEREDOC) is None


def test_a_long_tdd_list_is_capped(repo, env):
    command = " && ".join(f"echo 'X = {i}' > src/m{i:02d}.py" for i in range(12))
    reason = _feedback(Shell(repo, env).bash(command))
    tdd_part = reason.split("\n\n")[0]
    assert "src/m00.py" in tdd_part and "src/m11.py" not in tdd_part
    assert "4 more" in tdd_part


def test_a_fast_forward_pull_is_not_this_sessions_write(repo, env):
    """Commits that arrive during the call (a pull) were made before it: not named."""
    _git(repo, "checkout", "-q", "-b", "upstream")
    (repo / "src" / "app.py").write_text("VALUE = 6\n")
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qam", "up"],
                   cwd=repo, check=True, capture_output=True,
                   env={**os.environ, "GIT_COMMITTER_DATE": "2020-01-01T00:00:00"})
    _git(repo, "checkout", "-q", "main")
    assert Shell(repo, env).bash("git merge -q --ff-only upstream") is None
