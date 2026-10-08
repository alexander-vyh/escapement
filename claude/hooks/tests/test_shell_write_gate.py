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
from pathlib import Path

import _shell_write_harness as harness
from _shell_write_harness import BRIEF, HEREDOC, HOOK, Shell, _feedback, _git, env, repo, signals  # noqa: F401


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
    monkeypatch.setattr(harness, "HOOK", hooks / HOOK.name)
    reason = _feedback(Shell(repo, env).bash(HEREDOC))
    assert "test-oracle-brief.md" in reason and "src/app.py" in reason
    assert "TDD" not in reason


def test_a_long_tdd_list_is_capped(repo, env):
    command = " && ".join(f"echo 'X = {i}' > src/m{i:02d}.py" for i in range(12))
    reason = _feedback(Shell(repo, env).bash(command))
    tdd_part = reason.split("\n\n")[0]
    assert "src/m00.py" in tdd_part and "src/m11.py" not in tdd_part
    assert "4 more" in tdd_part
