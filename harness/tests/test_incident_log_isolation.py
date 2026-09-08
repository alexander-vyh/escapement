"""The Stop hook must log incidents to the CURRENT harness root, not the one that
happened to be set when the module was first imported (escapement-jjz8).

Why this matters as an outcome, not a style point: `incidents.jsonl` is the only
record of what the Stop gate decided, and every claim about whether the gate works
is computed over it. Today 34% of its in-window rows are test fixtures with
non-UUID session ids (`x`, `session`, ``, `no-beads`, `empty`), because
`stop_hook.INCIDENTS_LOG` is a module-level constant resolved at import time
(`stop_hook.py:55-56`). A test that sets `HARNESS_ROOT` after some earlier test
already imported the module still appends to the operator's real
`~/.claude/harness/incidents.jsonl`. Measured before the fix: `pytest
harness/tests/test_gate.py` alone leaked 21 rows.

The oracle is the operator's log staying untouched while the redirected log
receives the row — a positive and a negative control on the same write, so a fix
that simply stopped logging altogether would fail the positive control.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import pathlib
import sys

import pytest


BIN = pathlib.Path(__file__).resolve().parents[1] / "bin"


def _import_stop_hook_with_root(root: pathlib.Path):
    """Import a FRESH stop_hook whose module-level constants resolve against `root`.

    Mirrors production: the hook process starts, reads the environment once, and
    binds its paths. Returns the module object.
    """
    sys.path.insert(0, str(BIN))
    for name in ("stop_hook", "would_block_stop", "thread_identity"):
        sys.modules.pop(name, None)
    spec = importlib.util.spec_from_file_location("stop_hook", BIN / "stop_hook.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["stop_hook"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def two_roots(tmp_path, monkeypatch):
    """An `operator` root (bound at import) and a `redirected` root (set after)."""
    operator = tmp_path / "operator-home"
    redirected = tmp_path / "redirected-home"
    operator.mkdir()
    redirected.mkdir()
    monkeypatch.setenv("HARNESS_ROOT", str(operator))
    module = _import_stop_hook_with_root(operator)
    monkeypatch.setenv("HARNESS_ROOT", str(redirected))
    return module, operator, redirected


def _rows(root: pathlib.Path) -> list[dict]:
    log = root / "incidents.jsonl"
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text().splitlines() if line.strip()]


def test_incident_lands_in_the_current_root_not_the_import_time_root(two_roots):
    """The whole defect, as one assertion pair.

    NEGATIVE control: the operator's log — bound at import — must not grow.
    POSITIVE control: the redirected log must actually receive the record, so a
    fix that disabled logging entirely does not pass.
    """
    module, operator, redirected = two_roots

    module._log_incident(
        {
            "timestamp": "2026-09-08T00:00:00Z",
            "session_id": "x",
            "decision": "allow",
            "reason": "conversational",
            "was_correct": None,
            "notes": "",
        }
    )

    assert _rows(operator) == [], (
        "the operator's production incidents.jsonl was written to by a test — "
        "this is the contamination that makes every metric over the log unsound"
    )

    written = _rows(redirected)
    assert len(written) == 1, "the redirected root must still receive the incident"
    assert written[0]["session_id"] == "x"
    assert written[0]["reason"] == "conversational"


def test_root_switch_is_honored_repeatedly(two_roots, tmp_path):
    """Resolution happens per call, not once and cached on first use.

    Guards the near-miss fix of resolving lazily but memoizing the first result,
    which would still strand every later write in the wrong root.
    """
    module, operator, redirected = two_roots
    module._log_incident({"timestamp": "t", "session_id": "a", "decision": "allow", "reason": "r"})

    third = tmp_path / "third-home"
    third.mkdir()
    import os

    os.environ["HARNESS_ROOT"] = str(third)
    module._log_incident({"timestamp": "t", "session_id": "b", "decision": "allow", "reason": "r"})

    assert [r["session_id"] for r in _rows(redirected)] == ["a"]
    assert [r["session_id"] for r in _rows(third)] == ["b"]
    assert _rows(operator) == []
