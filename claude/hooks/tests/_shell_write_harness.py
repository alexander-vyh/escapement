"""Shared harness for the shell_write_gate tests: a scratch repo, an isolated
environment, and a Shell that runs the hook's halves around a real command."""


from __future__ import annotations

import json
import os
import subprocess
import sys
import time
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
    (state / ".beads").mkdir()
    # No live session identity and no live signal store: a test run inside an
    # agent session must not write gate signals into the checkout under test.
    clean = {k: v for k, v in os.environ.items()
             if not k.startswith(("ESCAPEMENT_", "BEADS_", "CLAUDE_", "CODEX_"))}
    clean.update(HARNESS_ROOT=str(state), GATE_SIGNAL_FALLBACK_DIR=str(state),
                 BEADS_DIR=str(state / ".beads"))
    return clean


def signals(env: dict) -> list[dict]:
    """Gate signals the hook recorded in this test's own store."""
    path = Path(env["BEADS_DIR"]) / ".gate-signal.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


class Shell:
    """One session: the hook before a real shell command, the command, the hook after.

    `pre=False` is a host that delivers only the PostToolUse half.
    """

    def __init__(self, repo: Path, env: dict, *, pre: bool = True, call_id=None) -> None:
        self.repo, self.env, self.session, self.pre = repo, env, f"s-{uuid.uuid4()}", pre
        # The host's tool-call id; Claude's shape unless a test names another.
        self.call_id = call_id or (lambda: f"toolu_{uuid.uuid4().hex}")
        self.duration_ms: int | None = None

    def _hook(self, event: str, command: str) -> dict | None:
        payload = {
            "session_id": self.session,
            "tool_use_id": self.call,
            "cwd": str(self.repo),
            "hook_event_name": event,
            "tool_name": "Bash",
            "tool_input": {"command": command},
        }
        if event == "PostToolUse":
            payload["tool_response"] = {"stdout": "", "stderr": "", "interrupted": False}
        elif event == "PostToolUseFailure":
            payload["error"] = "Exit code 1"
        if event != "PreToolUse" and self.duration_ms is not None:
            payload["duration_ms"] = self.duration_ms  # Claude 2.1.293 sends the command's run time
        proc = subprocess.run([sys.executable, "-B", str(HOOK)], input=json.dumps(payload),
                              capture_output=True, text=True, env=self.env, timeout=60)
        assert proc.returncode == 0, proc.stderr
        return json.loads(proc.stdout) if proc.stdout.strip() else None

    def bash(self, command: str, *, while_prompting=None) -> dict | None:
        """`while_prompting` runs after PreToolUse and before the command: the
        permission prompt's wait, which the command's duration_ms leaves out."""
        self.call = self.call_id()
        if self.pre:
            assert self._hook("PreToolUse", command) is None, "the snapshot never blocks"
        if while_prompting is not None:
            while_prompting()
        started = time.monotonic()
        # Claude sends a command that exits non-zero to PostToolUseFailure.
        failed = subprocess.run(["bash", "-c", command], cwd=self.repo).returncode != 0
        self.duration_ms = int((time.monotonic() - started) * 1000)
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
