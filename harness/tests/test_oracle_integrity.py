"""An oracle that lives in /tmp is evidence that evaporates (escapement-v3mj).

Business outcome
----------------
A contract's `verification_command` is the only durable statement of what "done"
meant for a piece of work. Anyone auditing later — a reviewer, the next session,
the operator asking "was this actually checked?" — must be able to re-run it.

Field audit of the 190 live contracts: 32 delegate their oracle to a shell script
under /tmp or /private/tmp, and **30 of those scripts no longer exist**. Those
contracts are unfalsifiable now: they record a green exit code against a command
nobody can reproduce. `is_trivial_oracle` does not catch them, because
`bash /tmp/verify.sh` is not a no-op — it is a real command pointing at a file
with a lifetime shorter than the claim it supports.

Independent source of truth
---------------------------
`init_contract.main` — the write path itself, checked by whether a contract file
appears on disk. Screening happens BEFORE any filesystem work, so a rejected
oracle leaves nothing behind that could later unlock the Stop gate.

Invalid solution classes rejected here
--------------------------------------
- Rejecting every absolute path: an oracle may legitimately name an absolute
  in-repo path, or a tool like /usr/bin/env. Only the ephemeral temp roots count.
- Rejecting the word "tmp" anywhere: a repo file called `tmp_loader_test.py` is a
  perfectly good oracle target and must still be accepted.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
BIN = REPO / "harness" / "bin"
sys.path.insert(0, str(BIN))

import init_contract  # noqa: E402


@pytest.mark.parametrize(
    "command",
    [
        "bash /tmp/verify_review_gate.sh",
        "bash /private/tmp/reticle-verify-4f9c2a/oracle.sh",
        "sh /tmp/x.sh && python3 -m pytest tests/ -q",
        "python3 /private/tmp/probe.py",
    ],
)
def test_oracles_that_live_in_tmp_are_rejected(command):
    """THE DEFECT. 30 of 32 such scripts are already gone from disk."""
    reason = init_contract.is_evaporating_oracle(command)
    assert reason is not None, f"accepted an evaporating oracle: {command!r}"
    assert "/tmp" in reason or "temporary" in reason.lower()


@pytest.mark.parametrize(
    "command",
    [
        "python3 -m pytest harness/tests/test_gate.py -q",
        "cd src/dashboards/frontend && npx vitest run outcome/outcome-1940.test.jsx",
        "bash scripts/verify_deploy.sh",
        "gh pr view 230 --json state -q '.state==\"MERGED\"'",
        "python3 -m pytest tests/test_tmp_loader.py -q",
        "/usr/bin/env python3 -m pytest tests/ -q",
    ],
)
def test_durable_oracles_are_accepted(command):
    """CONTROL: an in-repo path, a repo script, a public state check, and a
    filename that merely contains 'tmp' must all still be allowed. A screen that
    rejects these is worse than no screen — it pushes agents toward `true`."""
    assert init_contract.is_evaporating_oracle(command) is None, (
        f"rejected a durable oracle: {command!r}"
    )


def test_the_screen_runs_before_anything_is_written(tmp_path, monkeypatch, capsys):
    """A rejected oracle must leave NO contract behind — otherwise the Stop gate
    could later be unlocked by a file the screen meant to prevent."""
    thread_dir = tmp_path / "thread"
    monkeypatch.setenv("HARNESS_THREAD_DIR", str(thread_dir))
    rc = init_contract.main(
        ["--goal", "ship the thing", "--verify", "bash /tmp/oracle.sh"]
    )
    assert rc == 2
    assert not (thread_dir / "contract.json").exists(), (
        "a contract was written despite an evaporating oracle"
    )
    err = capsys.readouterr().err
    assert "refusing to write contract" in err


def test_a_durable_oracle_still_writes_a_contract(tmp_path, monkeypatch):
    """CONTROL: the screen must not break the normal path."""
    thread_dir = tmp_path / "thread"
    monkeypatch.setenv("HARNESS_THREAD_DIR", str(thread_dir))
    rc = init_contract.main(
        ["--goal", "ship the thing", "--verify", "python3 -m pytest tests/ -q"]
    )
    assert rc == 0
    written = json.loads((thread_dir / "contract.json").read_text())
    assert written["verification_command"] == "python3 -m pytest tests/ -q"
