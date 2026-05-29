#!/usr/bin/env python3
"""fxh.10 — derive a harness contract from a bead with ZERO additional hand-authoring.

Source / oracle brief: bead claude-workflow-setup-fxh.10 (epic ...-fxh).

Business invariant
------------------
A unit of work is currently authored three times: an openspec change, a beads
task graph, and a harness contract (`init_contract.py --goal --verify`). The
contract authoring is pure redundancy — its goal and oracle are already stated on
the bead. This module DERIVES the contract from the bead so the oracle is authored
ONCE (on the bead, where acceptance criteria already live) and the contract falls
out mechanically. The derived contract's `verification_command` must equal the
oracle the bead declares.

Convention
----------
A bead declares its machine oracle as a fenced ```verify block inside its
`acceptance_criteria`:

    ... prose acceptance criteria ...

    ```verify
    python3 -m pytest path/to/test.py
    ```

Derivation extracts that command verbatim. `goal` is taken from the bead title.

Fail-closed contract (never-suppress + gate-design Rule 3)
----------------------------------------------------------
The dangerous failure here is silently emitting `--verify true` for a bead with no
declared oracle — that would unlock the Stop gate with zero proof of outcome. So:
- A bead with NO ```verify block -> derivation REFUSES (raises / main returns 2,
  writes no contract). It must NEVER invent a passing oracle.
- A bead whose ```verify block is itself trivial (`true` / `:` / `echo x`) -> the
  SAME `is_trivial_oracle` guard that screens hand-authored contracts rejects it.
  One definition of "real oracle", two authoring paths.

Fragile implementations these tests REJECT
-------------------------------------------
- a derive() that returns a hardcoded / echoed string (defeated by the negative
  control: no-block beads must fail closed, not return a constant).
- a derive() that falls back to `true` / parses prose as a command (defeated by the
  trivial-oracle control and the no-block control).
- a derive() that copies prose acceptance text as the oracle (defeated by asserting
  equality with the *extracted block command*, not the whole acceptance string).

Run: python3 -m pytest harness/tests/test_contract_derivation.py -q
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

HARNESS_BIN = pathlib.Path(__file__).resolve().parents[1] / "bin"
sys.path.insert(0, str(HARNESS_BIN))

from derive_contract import (  # noqa: E402
    OracleNotDeclared,
    derive_contract,
    extract_verify_oracle,
    main,
)


# --- A realistic bead record, shaped exactly like `bd show <id> --json`[0] ------
ORACLE_CMD = "python3 -m pytest harness/tests/test_contract_derivation.py -q"


def _bead(acceptance: str, title: str = "Derive harness contract from a bead") -> dict:
    return {
        "id": "claude-workflow-setup-fxh.10",
        "title": title,
        "description": "Collapse triplicate authoring.",
        "acceptance_criteria": acceptance,
        "status": "open",
        "priority": 1,
        "issue_type": "task",
    }


ACCEPTANCE_WITH_BLOCK = (
    "Creating a tracked task produces a valid harness contract with ZERO "
    "additional hand-authoring.\n\n"
    "```verify\n"
    f"{ORACLE_CMD}\n"
    "```\n"
)


# --- extraction layer ----------------------------------------------------------
def test_extract_pulls_command_from_verify_block() -> None:
    assert extract_verify_oracle(ACCEPTANCE_WITH_BLOCK) == ORACLE_CMD


def test_extract_returns_none_without_block() -> None:
    # Prose-only acceptance (the real q90 / fxh.10 beads look like this).
    prose = "The derived contract's --verify matches the bead's acceptance criterion."
    assert extract_verify_oracle(prose) is None


def test_extract_ignores_non_verify_fences() -> None:
    # A plain ``` block (e.g. an example) is NOT an oracle declaration.
    other = "Example:\n\n```\nsome illustrative code\n```\n"
    assert extract_verify_oracle(other) is None


# --- derivation layer (positive control) ---------------------------------------
def test_derive_matches_bead_oracle() -> None:
    contract = derive_contract(_bead(ACCEPTANCE_WITH_BLOCK), session_id="sess-1")
    # The core acceptance criterion of fxh.10: --verify matches the bead's oracle.
    assert contract["verification_command"] == ORACLE_CMD
    assert contract["source"] == "bead-derived"
    # Goal is carried from the bead, not re-authored.
    assert "Derive harness contract from a bead" in contract["goal"]
    # Shape parity with hand-authored contracts.
    assert contract["expected_exit"] == 0
    assert contract["created_at"]


# --- fail-closed (negative controls) -------------------------------------------
def test_derive_fails_closed_without_oracle() -> None:
    with pytest.raises(OracleNotDeclared):
        derive_contract(_bead("prose only, no verify block"), session_id="sess-1")


def test_derive_fails_closed_on_trivial_oracle() -> None:
    # Reuses init_contract.is_trivial_oracle — a `true` block is not an oracle.
    trivial = "do the thing\n\n```verify\ntrue\n```\n"
    with pytest.raises(OracleNotDeclared):
        derive_contract(_bead(trivial), session_id="sess-1")


# --- CLI layer: writes the same contract.json the Stop gate / verify read -------
def test_main_writes_derived_contract(tmp_path, monkeypatch) -> None:  # positive
    monkeypatch.setenv("HARNESS_THREAD_DIR", str(tmp_path))
    rc = main(["--bead", "x"], _fetch=lambda _id: _bead(ACCEPTANCE_WITH_BLOCK))
    assert rc == 0
    data = json.loads((tmp_path / "contract.json").read_text())
    assert data["verification_command"] == ORACLE_CMD
    assert data["source"] == "bead-derived"


def test_main_refuses_when_no_oracle(tmp_path, monkeypatch) -> None:  # negative
    monkeypatch.setenv("HARNESS_THREAD_DIR", str(tmp_path))
    rc = main(["--bead", "x"], _fetch=lambda _id: _bead("prose only"))
    assert rc != 0, "main() must fail closed for a bead with no declared oracle"
    assert not (tmp_path / "contract.json").exists(), (
        "no contract.json may be written when the bead declares no oracle"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
