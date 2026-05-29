#!/usr/bin/env python3
"""fxh.3 — init_contract.py must REJECT trivial (always-0) --verify oracles at
write time.

Source / oracle brief: docs/assessments/2026-05-28-critical-assessment.md (B3),
bead claude-workflow-setup-fxh.3.

Business invariant
------------------
A contract's --verify command is the oracle whose exit code unlocks the
continuation-harness Stop gate. If the oracle is `true` / `:` / `echo ...` /
`exit 0`, the gate unlocks with ZERO proof of outcome — gate-design Rule 3
(validate the value, not its presence) is violated. The fix screens the oracle at
contract-creation time and refuses to write a contract backed by a no-op.

Fragile implementations these tests REJECT
-------------------------------------------
- presence-only acceptance (any non-empty string) — the bug itself.
- rejecting only the literal "true" while letting ":" / "echo x" / "exit 0" pass.
- rejecting REAL oracles (false positives) — e.g. a command that is trivial in one
  segment but does real work in another (`true && pytest`) must be ALLOWED.

Run: python3 -m pytest harness/tests/test_init_contract_oracle.py -q
"""

from __future__ import annotations

import json
import pathlib
import sys

HARNESS_BIN = pathlib.Path(__file__).resolve().parents[1] / "bin"
sys.path.insert(0, str(HARNESS_BIN))

from init_contract import is_trivial_oracle, main  # noqa: E402

# Always exit 0 regardless of system state -> not an oracle.
TRIVIAL = [
    "true", ":", "exit 0", "exit", "echo done", "printf hi",
    "", "   ", "true && :", "true ; echo hi", " : || true ", "cd .", "pwd",
    "TRUE", "Echo done",  # case-insensitive
]

# Exit code depends on real state / runs a real check -> a legitimate oracle.
REAL = [
    "pytest tests/", "python3 -m pytest harness/tests/x.py",
    "bd close abc-1", "true && pytest tests/", "[ -f out.txt ]",
    "exit 1", "test 3 -eq 3 && ./run_real_check.sh",
    "gh pr view 5 --json state -q '.state == \"OPEN\"'",
]


def test_trivial_oracles_rejected() -> None:
    for cmd in TRIVIAL:
        assert is_trivial_oracle(cmd) is not None, f"should reject trivial oracle {cmd!r}"


def test_real_oracles_allowed() -> None:
    for cmd in REAL:
        assert is_trivial_oracle(cmd) is None, f"should allow real oracle {cmd!r}"


def test_main_refuses_to_write_trivial_contract(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HARNESS_THREAD_DIR", str(tmp_path))
    rc = main(["--goal", "g", "--verify", "true"])
    assert rc != 0, "main() must return non-zero for a trivial oracle"
    assert not (tmp_path / "contract.json").exists(), (
        "no contract.json should be written when the oracle is trivial"
    )


def test_main_writes_real_contract(tmp_path, monkeypatch) -> None:  # positive control
    monkeypatch.setenv("HARNESS_THREAD_DIR", str(tmp_path))
    rc = main(["--goal", "g", "--verify", "pytest tests/"])
    assert rc == 0, "a real oracle must still write the contract"
    data = json.loads((tmp_path / "contract.json").read_text())
    assert data["verification_command"] == "pytest tests/"


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
