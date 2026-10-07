#!/usr/bin/env python3
"""escapement-l9lo — a claimed bead's acceptance oracle is the continuation contract.

Outcome (user-observable)
-------------------------
When a session claims a bead, the bead's ```verify acceptance block — written
before the code — becomes the contract that `verify` runs and the Stop gate
accepts, frozen at claim time. An agent can no longer end its turn on a contract
it wrote for itself, for earlier work, or from acceptance text rewritten after
the claim. A session with no claimed bead keeps declaring its own contract.

Oracle
------
The REAL entrypoints, run as subprocesses against an isolated harness root and a
fake `bd` that serves bead records from disk: the claim hook
(task_mode_entry.py), `init_contract.py`, `derive_contract.py`, the `verify`
shell entrypoint, and the Stop hook. The observable verdict is the Stop hook's
block/allow output and verify's exit code — not any helper's return value.

Wrong implementations these tests reject
----------------------------------------
- "claim ignored": the claim does not derive the bead's oracle, so the session
  keeps whatever contract it had (test_claim_freezes_bead_oracle_as_contract).
- "always prefer the agent contract": init_contract.py silently replaces a bead
  oracle, or a hand-written contract.json passes verify/Stop
  (test_agent_contract_cannot_replace_bead_oracle).
- "hash computed but never compared": the acceptance text is hashed at claim
  but a rewritten oracle still verifies green
  (test_acceptance_rewritten_after_claim_is_reported).
- "re-derive silently uses the new text": derive_contract.py re-freezes a
  rewritten acceptance without an explicit --refreeze
  (test_acceptance_rewritten_after_claim_is_reported).
- "bead switch ignored": a contract that went green for bead A still lets the
  session stop after it claims bead B — the l9lo defect
  (test_bead_switch_invalidates_previous_contract).
- "ad hoc sessions regress": with no bead bound, an agent-declared contract must
  still verify and release Stop (test_unbound_session_keeps_agent_contract).
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
SESSION = "l9lo-session"

FAKE_BD = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import json, os, pathlib, sys
    store = pathlib.Path(os.environ["FAKE_BD_STORE"])
    args = sys.argv[1:]
    if args[:1] == ["show"] and len(args) >= 2:
        path = store / (args[1] + ".json")
        if not path.exists():
            print("[]")
            sys.exit(1)
        print(json.dumps([json.loads(path.read_text())]))
        sys.exit(0)
    if args[:1] in (["ready"], ["list"]):
        print("[]")
        sys.exit(0)
    sys.exit(0)
    """
)


def _acceptance(command: str | None) -> str:
    prose = "The outcome is observable."
    if command is None:
        return prose
    return f"{prose}\n\n```verify\n{command}\n```\n"


class Session:
    """One isolated harness session driven through the real entrypoints."""

    def __init__(self, tmp: pathlib.Path) -> None:
        self.work = tmp / "work"
        self.work.mkdir()
        self.thread = tmp / "thread"
        self.thread.mkdir()
        self.store = tmp / "beads"
        self.store.mkdir()
        fakebin = tmp / "fakebin"
        fakebin.mkdir()
        bd = fakebin / "bd"
        bd.write_text(FAKE_BD)
        bd.chmod(0o755)
        self.env = {
            **os.environ,
            "PATH": f"{fakebin}{os.pathsep}{os.environ.get('PATH', '')}",
            "FAKE_BD_STORE": str(self.store),
            "HARNESS_THREAD_DIR": str(self.thread),
            "HARNESS_ROOT": str(tmp / "harness"),
            "CONTINUATION_HARNESS_HOME": str(tmp / "harness"),
            "CLAUDE_CODE_SESSION_ID": SESSION,
        }
        self.env.pop("CLAUDE_AGENT_ID", None)

    def bead(self, bead_id: str, command: str | None) -> None:
        (self.store / f"{bead_id}.json").write_text(json.dumps({
            "id": bead_id,
            "title": f"Outcome of {bead_id}",
            "status": "in_progress",
            "acceptance_criteria": _acceptance(command),
        }))

    def close(self, bead_id: str) -> None:
        path = self.store / f"{bead_id}.json"
        path.write_text(json.dumps(dict(json.loads(path.read_text()), status="closed")))

    def _run(self, argv: list[str], stdin: str = "") -> subprocess.CompletedProcess:
        return subprocess.run(
            argv, input=stdin, capture_output=True, text=True,
            cwd=self.work, env=self.env, timeout=60,
        )

    def claim(self, bead_id: str) -> None:
        r = self._run([sys.executable, str(BIN / "task_mode_entry.py")], json.dumps({
            "session_id": SESSION,
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": f"bd update {bead_id} --claim"},
            "tool_response": {"interrupted": False, "stdout": "", "stderr": ""},
        }))
        assert r.returncode == 0, r.stderr

    def declare(self, command: str) -> subprocess.CompletedProcess:
        return self._run([
            sys.executable, str(BIN / "init_contract.py"),
            "--goal", "agent goal", "--verify", command,
        ])

    def derive(self, bead_id: str, *extra: str) -> subprocess.CompletedProcess:
        return self._run([sys.executable, str(BIN / "derive_contract.py"), "--bead", bead_id, *extra])

    def verify(self) -> subprocess.CompletedProcess:
        return self._run(["bash", str(BIN / "verify")])

    def stop(self) -> dict | None:
        r = self._run([sys.executable, str(BIN / "stop_hook.py")], json.dumps({
            "session_id": SESSION, "transcript_path": "", "stop_hook_active": False,
        }))
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout) if r.stdout.strip() else None

    def contract(self) -> dict:
        return json.loads((self.thread / "contract.json").read_text())


@pytest.fixture
def s(tmp_path: pathlib.Path) -> Session:
    return Session(tmp_path)


def _blocked(verdict: dict | None) -> bool:
    return isinstance(verdict, dict) and verdict.get("decision") == "block"


def test_claim_freezes_bead_oracle_as_contract(s: Session) -> None:
    """Claiming a bead makes its ```verify block the contract — no hand-authoring."""
    s.declare("test -d .")  # earlier ad hoc contract, would pass
    s.bead("bd-a", "test -f done-a")
    s.claim("bd-a")

    assert s.contract()["verification_command"] == "test -f done-a"
    assert s.verify().returncode != 0, "the bead oracle is red until the outcome exists"
    assert _blocked(s.stop())

    (s.work / "done-a").write_text("x")
    s.close("bd-a")
    assert s.verify().returncode == 0
    assert s.stop() is None, "a green bead oracle releases Stop"


def test_agent_contract_cannot_replace_bead_oracle(s: Session) -> None:
    """With a bead oracle bound, the agent may not swap in an easier exam."""
    s.bead("bd-a", "test -f done-a")
    s.claim("bd-a")

    r = s.declare("test -d .")
    assert r.returncode != 0, "init_contract.py must refuse to replace a bead oracle"
    assert "bd-a" in r.stderr
    assert s.contract()["verification_command"] == "test -f done-a"

    # Bypass the CLI: hand-write an agent contract straight into contract.json.
    forged = dict(s.contract(), verification_command="test -d .", source="agent-declared")
    forged.pop("bead_id", None)
    (s.thread / "contract.json").write_text(json.dumps(forged))
    v = s.verify()
    assert v.returncode != 0, "a hand-written contract must not verify while a bead oracle is bound"
    assert "bd-a" in (v.stdout + v.stderr)
    assert _blocked(s.stop())


def test_acceptance_rewritten_after_claim_is_reported(s: Session) -> None:
    """Rewriting the bead's oracle mid-work is surfaced, never silently adopted."""
    s.bead("bd-a", "test -f done-a")
    s.claim("bd-a")

    s.bead("bd-a", "test -d .")  # oracle rewritten to something already true
    v = s.verify()
    assert v.returncode != 0
    assert "changed" in (v.stdout + v.stderr).lower()
    assert _blocked(s.stop())

    # Re-deriving does not quietly adopt the new text...
    r = s.derive("bd-a")
    assert r.returncode != 0 and "--refreeze" in r.stderr
    assert s.verify().returncode != 0
    # ...a contract re-derived from the new text by hand is still caught...
    (s.thread / "contract.json").write_text(json.dumps(
        dict(s.contract(), verification_command="test -d .", acceptance_sha256="0" * 64)))
    assert s.verify().returncode != 0
    assert _blocked(s.stop())

    # ...and an explicit, recorded re-freeze is the escape (positive control).
    s.close("bd-a")
    r = s.derive("bd-a", "--refreeze")
    assert r.returncode == 0, r.stderr
    assert s.contract().get("refrozen_from")
    assert s.verify().returncode == 0
    assert s.stop() is None


def test_bead_switch_invalidates_previous_contract(s: Session) -> None:
    """The l9lo defect: A's green contract must not stand in for bead B's work."""
    s.bead("bd-a", "test -f done-a")
    s.claim("bd-a")
    (s.work / "done-a").write_text("x")
    s.close("bd-a")
    assert s.verify().returncode == 0
    assert s.stop() is None  # positive control: A really was done

    s.bead("bd-b", None)  # B declares no machine oracle
    s.claim("bd-b")
    assert _blocked(s.stop()), "A's fresh green run must not release Stop for B"
    v = s.verify()
    assert v.returncode != 0, "verify must not re-run A's oracle as proof for B"
    assert "bd-b" in (v.stdout + v.stderr)

    # Re-declaring for B (which has no bead oracle) is the escape.
    assert s.declare("test -f done-b").returncode == 0
    (s.work / "done-b").write_text("x")
    assert s.verify().returncode == 0
    assert s.stop() is None

    # A third bead WITH an oracle replaces B's contract with its own.
    s.bead("bd-c", "test -f done-c")
    s.claim("bd-c")
    assert s.contract()["verification_command"] == "test -f done-c"
    assert _blocked(s.stop())


def test_unbound_session_keeps_agent_contract(s: Session) -> None:
    """No bead claimed: the agent-declared path is unchanged."""
    assert s.declare("test -f done").returncode == 0
    assert s.verify().returncode != 0
    assert _blocked(s.stop())
    (s.work / "done").write_text("x")
    assert s.verify().returncode == 0
    assert s.stop() is None
