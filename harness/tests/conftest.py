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

import json
import os
import re

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


_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)


@pytest.fixture(autouse=True)
def _fail_if_operator_log_gets_fixture_rows():
    """Independent guard: no FIXTURE-shaped row may reach the operator's real log.

    Deliberately does not trust the redirection above — it reads the operator's
    actual file, so a change that reintroduces a hardcoded path or adds a new
    unredirected subprocess fails loudly here instead of polluting the log for
    months (which is exactly what happened: 34% of its rows).

    It attributes rows rather than comparing sizes. Other live agent sessions on
    this machine write real decisions to the same log while the suite runs, so a
    byte-delta check reports those as leaks — a false positive that would train
    everyone to ignore this guard. A row whose session_id is a UUID came from a
    real session and is none of our business; a non-UUID one (``x``, ``session``,
    ``""``) came from a test.

    Known limit, named rather than hidden: a test that leaks while passing a
    UUID-shaped session id is invisible here. Nothing in the suite does that today.
    """
    real = os.path.expanduser("~/.claude/harness/incidents.jsonl")

    def line_count() -> int:
        try:
            with open(real, "rb") as handle:
                return sum(1 for _ in handle)
        except OSError:
            return 0

    before = line_count()
    yield
    try:
        with open(real, encoding="utf-8", errors="replace") as handle:
            appended = handle.readlines()[before:]
    except OSError:
        return

    leaked = []
    for line in appended:
        try:
            row = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if not _UUID_RE.match(str(row.get("session_id") or "")):
            leaked.append(row)

    assert not leaked, (
        f"this test wrote {len(leaked)} fixture-shaped row(s) into the operator's real "
        f"incidents log ({real}): {leaked[:3]}. Redirect HARNESS_ROOT for whatever "
        "spawns the hook — production metrics are computed over that file."
    )
