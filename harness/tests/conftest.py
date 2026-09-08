"""Keep the harness test suite out of the operator's real state dir (escapement-jjz8).

The Stop hook resolves its state root from `HARNESS_ROOT` / `CONTINUATION_HARNESS_HOME`,
defaulting to `~/.claude/harness`. Tests that exercise the hook — especially the ones
that spawn it as a SUBPROCESS passing only `HARNESS_THREAD_DIR` (test_gate.py:365) —
inherited the real default and appended their decisions to the operator's live
`incidents.jsonl`. That is how 34% of that log's rows became fixtures with non-UUID
session ids (`x`, `session`, ``, `no-beads`, `empty`), which makes every metric
computed over the log unsound, including the ones used to argue about the gate's
own effectiveness.

Fixing the call sites one at a time would work until the next test forgot. This is the
mechanism instead: every test gets its own harness root by default. A test that wants
a specific root still overrides it with `monkeypatch.setenv`, which runs after this
fixture and therefore wins.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _isolated_harness_root(tmp_path_factory, monkeypatch):
    """Point HARNESS_ROOT at a per-test tmp dir before any test body runs.

    Autouse and function-scoped so subprocess children (which inherit os.environ)
    are covered too — that is the leak path a module-level constant fix cannot reach.
    """
    root = tmp_path_factory.mktemp("harness-root")
    monkeypatch.setenv("HARNESS_ROOT", str(root))
    # The hook reads CONTINUATION_HARNESS_HOME when computing its default; pin it to
    # the same tmp root so neither name can resolve back to the operator's home.
    monkeypatch.setenv("CONTINUATION_HARNESS_HOME", str(root))
    yield root


@pytest.fixture(autouse=True)
def _fail_if_operator_log_written():
    """Independent guard: assert the real incidents log did not grow during the test.

    Deliberately does NOT trust the redirection above — it measures the operator's
    actual file, so a future change that reintroduces a hardcoded path or a new
    unredirected subprocess fails here loudly instead of silently polluting the log
    for months. This is the negative control the previous instrument never had.
    """
    real = os.path.expanduser("~/.claude/harness/incidents.jsonl")

    def size() -> int:
        try:
            return os.path.getsize(real)
        except OSError:
            return -1

    before = size()
    yield
    after = size()
    assert after == before, (
        f"this test wrote to the operator's real incidents log ({real}): "
        f"{before} -> {after} bytes. Redirect HARNESS_ROOT for whatever spawns the "
        "hook; production metrics are computed over that file."
    )
