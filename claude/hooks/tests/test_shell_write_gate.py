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
  - firing on anything dirty: a docs change is the positive control.
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
    """One session: run a real shell command, then the hook on its payload."""

    def __init__(self, repo: Path, env: dict) -> None:
        self.repo, self.env, self.session = repo, env, f"s-{uuid.uuid4()}"

    def bash(self, command: str) -> dict | None:
        subprocess.run(["bash", "-c", command], cwd=self.repo, check=True)
        payload = {
            "session_id": self.session,
            "cwd": str(self.repo),
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": command},
            "tool_response": {"stdout": "", "stderr": "", "interrupted": False},
        }
        proc = subprocess.run([sys.executable, "-B", str(HOOK)], input=json.dumps(payload),
                              capture_output=True, text=True, env=self.env, timeout=60)
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout) if proc.stdout.strip() else None


def _feedback(output: dict | None) -> str:
    """What Claude feeds back to the model after the Bash call, else fail."""
    assert output is not None, "expected the shell write to be reported"
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
    """Open PR #250 retires tdd-gate: the brief check must not die with it."""
    import shutil
    hooks = tmp_path / "hooks"
    shutil.copytree(HOOK.parent, hooks, ignore=shutil.ignore_patterns("tdd-gate.py", "tests"))
    monkeypatch.setattr(sys.modules[__name__], "HOOK", hooks / HOOK.name)
    reason = _feedback(Shell(repo, env).bash(HEREDOC))
    assert "test-oracle-brief.md" in reason and "src/app.py" in reason
    assert "TDD" not in reason
