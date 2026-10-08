#!/usr/bin/env python3
"""The Stop block states the contract's REAL last verify result (escapement-l9lo F3).

Outcome (user-observable)
-------------------------
When the Stop hook blocks because session-fresh bd work remains, its message tells
the agent what its contract's verify actually did. It used to say "your contract
verify passed" unconditionally — reproduced live with a contract whose verify exits
1 ("NOT MERGED ...") plus a registered ScheduleWakeup: the wakeup path reaches the
same bd-queue block as the green path and reused the green-path wording.

Oracle
------
The real entrypoints as subprocesses (init_contract.py, the `verify` script,
stop_hook.py) against an isolated harness root and a fake `bd` whose queue holds
one in-progress bead this session claimed. The verdict is the Stop hook's block text.

Wrong implementations rejected
------------------------------
- "hard-coded passed": any block text that says "passed" after a non-zero verify
  (test_queue_block_reports_red_verify_as_red).
- "status without evidence": a red label with no exit code or output tail.
- "never says passed" (overcorrection): a fresh green verify must still be
  reported as passed (test_queue_block_after_green_says_passed).
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import textwrap

import pytest

BIN = pathlib.Path(__file__).resolve().parents[1] / "bin"
SESSION = "verify-status-session"

FAKE_BD = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import json, sys
    if sys.argv[1:2] in (["ready"], ["list"]):
        print(json.dumps([{"id": "bd-open", "status": "in_progress", "title": "fresh"}]))
    else:
        print("[]")
    """
)


class Session:
    def __init__(self, tmp: pathlib.Path) -> None:
        self.work = tmp / "work"
        self.work.mkdir()
        self.thread = tmp / "thread"
        self.thread.mkdir()
        # The queue block holds only on beads this session claimed (escapement-xcbn).
        (self.thread / "claimed_beads.json").write_text(json.dumps({"ids": ["bd-open"]}))
        fakebin = tmp / "fakebin"
        fakebin.mkdir()
        (fakebin / "bd").write_text(FAKE_BD)
        (fakebin / "bd").chmod(0o755)
        self.env = {
            **os.environ,
            "PATH": f"{fakebin}{os.pathsep}{os.environ.get('PATH', '')}",
            "HARNESS_THREAD_DIR": str(self.thread),
            "HARNESS_ROOT": str(tmp / "harness"),
            "CONTINUATION_HARNESS_HOME": str(tmp / "harness"),
            "CLAUDE_CODE_SESSION_ID": SESSION,
        }
        self.env.pop("CLAUDE_AGENT_ID", None)

    def _run(self, argv: list[str], stdin: str = "") -> subprocess.CompletedProcess:
        return subprocess.run(argv, input=stdin, capture_output=True, text=True,
                              cwd=self.work, env=self.env, timeout=60)

    def declare(self, command: str) -> None:
        r = self._run([sys.executable, str(BIN / "init_contract.py"),
                       "--goal", "ship it", "--verify", command])
        assert r.returncode == 0, r.stderr

    def verify(self) -> int:
        return self._run(["bash", str(BIN / "verify")]).returncode

    def stop(self) -> dict | None:
        r = self._run([sys.executable, str(BIN / "stop_hook.py")], json.dumps({
            "session_id": SESSION, "transcript_path": "", "stop_hook_active": False,
        }))
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout) if r.stdout.strip() else None


@pytest.fixture
def s(tmp_path: pathlib.Path) -> Session:
    return Session(tmp_path)


def test_queue_block_reports_red_verify_as_red(s: Session) -> None:
    """Red contract + registered wakeup + fresh bd work: the block reports the
    failure with its exit code and output tail, never as passed."""
    s.declare("echo 'NOT MERGED: feature-x'; exit 1")
    assert s.verify() == 1
    (s.thread / "scheduled.json").write_text(json.dumps([{
        "wake_at": "2999-01-01T00:00:00+00:00", "prompt": "check CI", "thread_id": SESSION,
    }]))

    verdict = s.stop()
    assert verdict and verdict.get("decision") == "block", verdict
    reason = verdict["reason"]
    assert "passed" not in reason.lower(), reason
    assert "exited 1" in reason, reason
    assert "NOT MERGED: feature-x" in reason, reason


def test_queue_block_after_green_says_passed(s: Session) -> None:
    """Positive control: a fresh green verify is still reported as passed."""
    s.declare("test -d .")
    assert s.verify() == 0

    verdict = s.stop()
    assert verdict and verdict.get("decision") == "block", verdict
    assert "verify passed" in verdict["reason"].lower(), verdict["reason"]
