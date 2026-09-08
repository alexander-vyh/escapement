"""A drained task queue must not stop a session whose contract never verified
(escapement-b81u).

Business outcome
----------------
"Done" for a work session means its declared outcome was verified — not that its
bead queue happens to be empty. Today a scoped task-mode session returns at
`stop_hook.py:1116` the moment `check_task_scope` says `queue_drained`, and the
contract gate at line 1126 is never consulted. So a session can declare an
outcome, never verify it, close its beads, and stop clean. `queue_drained` is
292 real-session decisions in the 2026-08-01..09-07 window, and real sessions
have logged **zero** `verification_passed` since 2026-07-11.

The code already believes this fall-through exists: `_task_mode_in_effect`'s
docstring says a scopeless record "falls through to the normal contract gate,
which still blocks a red contract — teeth kept." That is true for a *scopeless*
record and false for a scoped one, which is the defect.

Independent source of truth
---------------------------
`stop_hook.main()` driven end to end over real stdin with a real fake `bd` on
PATH — the public entrypoint, not the gate function.

Invalid solution classes rejected here
--------------------------------------
- blocking every task-mode session: the no-contract case must still ALLOW, so the
  fix cannot become a new tax on sessions that never declared an outcome
- blocking on contract presence rather than contract RESULT: the verified case
  must ALLOW
"""

from __future__ import annotations

import datetime as dt
import io
import json
import os
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
BIN = REPO / "harness" / "bin"
sys.path.insert(0, str(BIN))

import stop_hook  # noqa: E402

SESSION = "reachability-session"
TASK_BEAD = "escapement-b81u"
REAL_ORACLE = "python3 -m pytest harness/tests/test_contract_gate_reachability.py -q"


def _fake_bd(tmp_path: pathlib.Path) -> pathlib.Path:
    """A `bd` whose queue is DRAINED: claimed bead closed, nothing ready/blocked."""
    fakebin = tmp_path / "bin"
    fakebin.mkdir()
    script = fakebin / "bd"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "args = tuple(a for a in sys.argv[1:] if a != '--json')\n"
        "if args[:1] == ('show',):\n"
        f"    print(json.dumps([{{'id': {TASK_BEAD!r}, 'status': 'closed'}}]))\n"
        "elif args[:1] in (('ready',), ('blocked',)):\n"
        "    print('[]')\n"
        "else:\n"
        "    raise SystemExit(1)\n",
        encoding="utf-8",
    )
    script.chmod(0o755)
    return fakebin


def _run_stop(monkeypatch, capsys, tmp_path, contract: dict | None) -> str:
    root = tmp_path / "harness"
    thread_dir = root / "threads" / SESSION
    thread_dir.mkdir(parents=True)

    mode = {
        "mode": "task",
        "session_id": SESSION,
        "task_id": TASK_BEAD,
        "parent_id": None,
        "repo_cwd": str(tmp_path),
    }
    mode_path = thread_dir / "session_mode.json"
    mode_path.write_text(json.dumps(mode), encoding="utf-8")
    mode_path.chmod(0o600)
    (thread_dir / "scheduled.json").write_text("[]", encoding="utf-8")
    if contract is not None:
        (thread_dir / "contract.json").write_text(json.dumps(contract), encoding="utf-8")

    fakebin = _fake_bd(tmp_path)
    # Run from a NON-git cwd. Otherwise the suite's own working tree supplies
    # `verification_passed_git_work_remains`, and the verified-contract control
    # would go red for a reason that has nothing to do with reachability.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", f"{fakebin}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("HARNESS_ROOT", str(root))
    monkeypatch.setattr(stop_hook, "HARNESS_ROOT", root)
    monkeypatch.setattr(stop_hook.session_isolation, "write_checkout", lambda *a: None)
    monkeypatch.setattr(
        stop_hook.sys,
        "stdin",
        io.StringIO(json.dumps({"session_id": SESSION, "transcript_path": ""})),
    )
    assert stop_hook.main() == 0
    return capsys.readouterr().out


def _contract(*, verified: bool) -> dict:
    last_run = None
    if verified:
        last_run = {
            "exit_code": 0,
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
    return {
        "goal": "the reachability gap is closed",
        "verification_command": REAL_ORACLE,
        "expected_exit": 0,
        "source": "agent-declared",
        "thread_id": SESSION,
        "created_at": "2026-09-08T00:00:00+00:00",
        "last_run": last_run,
    }


def test_drained_queue_does_not_release_an_unverified_contract(
    monkeypatch, capsys, tmp_path
):
    """THE DEFECT. Queue empty, contract declared, never verified -> must BLOCK.

    Fragile implementation this rejects: returning on `queue_drained` without
    consulting the contract, which lets task state stand in for the outcome.
    """
    out = _run_stop(monkeypatch, capsys, tmp_path, _contract(verified=False))
    assert out.strip(), "the hook must emit a decision, not stop silently"
    payload = json.loads(out.strip().splitlines()[-1])
    assert payload["decision"] == "block", (
        "a drained bead queue released a session whose declared outcome was never "
        f"verified; got {payload!r}"
    )


def test_drained_queue_still_releases_a_session_with_no_contract(
    monkeypatch, capsys, tmp_path
):
    """CONTROL: the fix must not become a new tax on undeclared sessions."""
    out = _run_stop(monkeypatch, capsys, tmp_path, None).strip()
    if out:
        payload = json.loads(out.splitlines()[-1])
        assert payload["decision"] != "block", (
            "a session that never declared a contract was blocked — that is the "
            f"conversational population, which labels 5,528 correct; got {payload!r}"
        )


def test_drained_queue_releases_a_verified_contract(monkeypatch, capsys, tmp_path):
    """CONTROL: a genuinely verified outcome still stops. Guards against a fix
    that blocks on contract PRESENCE rather than on its RESULT."""
    out = _run_stop(monkeypatch, capsys, tmp_path, _contract(verified=True)).strip()
    if out:
        payload = json.loads(out.splitlines()[-1])
        assert payload["decision"] != "block", (
            f"a fresh green contract was blocked; got {payload!r}"
        )
