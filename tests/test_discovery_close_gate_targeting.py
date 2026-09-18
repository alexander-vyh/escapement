"""Behavioral controls for which design the close gate interrogates.

The independent oracle is the gate's own PreToolUse contract — the JSON it
prints on stdout — driven through `main()` with a real repository tree on disk
and a real `bd` executable on PATH. Nothing about design selection is mocked,
because the defect these tests exist for was in the selection itself: the gate
asked about the newest-mtime change dir, which bears no relation to the bead
being closed, so every close in a repo with several in-flight changes was
interrogated about someone else's work.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import stat
import sys
from pathlib import Path
from unittest.mock import patch

import pytest


HOOKS = Path(__file__).resolve().parents[1] / "claude" / "hooks"
sys.path.insert(0, str(HOOKS))

spec = importlib.util.spec_from_file_location(
    "discovery_close_gate_targeting", HOOKS / "discovery-close-gate.py"
)
gate = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules[spec.name] = gate
spec.loader.exec_module(gate)


PROOF_AND_METRICS = """# Design

## Proof of Delivery

A Cali Leads operator can compare the workbook to the generated parity view.

## Anti-Metrics

- Workbook parity failure without explanation blocks MVP.
"""


def _design(repo: Path, change: str, body: str = PROOF_AND_METRICS) -> Path:
    path = repo / "openspec" / "changes" / change / "design.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _fake_bd(repo: Path, records: dict[str, dict], *, exit_code: int = 0) -> None:
    """Install a `bd` on PATH that answers `show <id> --json` from `records`."""
    bin_dir = repo / "fakebin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(records)
    script = bin_dir / "bd"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        f"RECORDS = json.loads({payload!r})\n"
        f"sys.exit({exit_code}) if {exit_code} else None\n"
        "args = sys.argv[1:]\n"
        "if len(args) >= 2 and args[0] == 'show':\n"
        "    record = RECORDS.get(args[1])\n"
        "    if record is None:\n"
        "        sys.exit(1)\n"
        "    print(json.dumps([record]))\n"
        "    sys.exit(0)\n"
        "sys.exit(2)\n",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"


def _run(command: str, repo: Path, session_id: str = "session-under-test") -> dict | None:
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "cwd": str(repo),
        "session_id": session_id,
    }
    out = io.StringIO()
    with patch.object(sys, "stdin", io.StringIO(json.dumps(payload))), patch.object(
        sys, "stdout", out
    ):
        assert gate.main() == 0
    text = out.getvalue().strip()
    return json.loads(text) if text else None


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("PATH", os.environ["PATH"])
    # Real signal store, pointed at the test's own beads dir: Rule 2 says the
    # decision has to persist, so the tests read the corpus rather than trust a
    # stub that cannot fail.
    beads = tmp_path / ".beads"
    beads.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("BEADS_DIR", str(beads))
    monkeypatch.setattr(gate, "_dedup_state_file", lambda sid: tmp_path / f"dedup-{sid}.json")
    return tmp_path


def _signals(repo: Path, filename: str = ".gate-signal.jsonl") -> list[dict]:
    path = repo / ".beads" / filename
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def test_an_unrelated_bead_is_not_interrogated_about_the_newest_design(repo: Path) -> None:
    """A bead that links no design gets no questions, however fresh other designs are."""
    _design(repo, "someone-elses-pipeline")
    _fake_bd(repo, {"cake-sjeb": {"id": "cake-sjeb", "title": "ruff pins diverge",
                                  "description": "re-enable AIR3xx", "notes": ""}})

    assert _run("bd close cake-sjeb --reason 'pins agree now'", repo) is None
    # Rule 2: a silent allow is still a decision, and it is still counted.
    signals = _signals(repo)
    assert [s["decision"] for s in signals] == ["allow"]
    assert "no design doc is linked" in signals[0]["reason"]
    assert signals[0]["extras"]["beads"] == "cake-sjeb"


def test_the_design_asked_about_is_the_one_the_closing_bead_links(repo: Path) -> None:
    """With two designs present, the questions come from the bead's own link."""
    _design(repo, "someone-elses-pipeline")
    linked = _design(
        repo,
        "device-confidence-layer",
        PROOF_AND_METRICS.replace("Cali Leads operator", "custody reviewer"),
    )
    _fake_bd(repo, {"cake-dev1": {
        "id": "cake-dev1",
        "title": "device confidence",
        "description": "Implements openspec/changes/device-confidence-layer/design.md",
        "notes": "",
    }})

    result = _run("bd close cake-dev1 --reason 'shipped'", repo)

    assert result is not None
    reason = result["hookSpecificOutput"]["permissionDecisionReason"]
    assert "device-confidence-layer" in reason
    assert "custody reviewer" in reason
    assert "someone-elses-pipeline" not in reason
    assert "Cali Leads operator" not in reason
    assert str(linked.relative_to(repo)) in reason
    assert "cake-dev1" in reason


def test_prose_that_merely_mentions_closing_a_bead_does_not_fire(repo: Path) -> None:
    """The phrase inside a quoted note, a grep pattern, or `--help` is not a close."""
    _design(repo, "device-confidence-layer")
    _fake_bd(repo, {"cake-dev1": {
        "id": "cake-dev1",
        "description": "openspec/changes/device-confidence-layer/design.md",
        "notes": "",
    }})

    quoted_note = (
        "bd note cake-dev1 \"verified; left open because bd close cake-dev1 "
        "is gated in this session\""
    )
    assert _run(quoted_note, repo) is None
    assert _run("grep -rn 'bd close' claude/hooks/", repo) is None
    assert _run("bd close --help", repo) is None
    assert _run("echo 'run bd close cake-dev1 later'", repo) is None


def test_the_same_design_is_not_re_asked_within_one_session(repo: Path) -> None:
    """Consecutive closes against one design ask once; habituation is the failure."""
    _design(repo, "device-confidence-layer")
    _fake_bd(repo, {
        "cake-dev1": {"id": "cake-dev1",
                      "description": "openspec/changes/device-confidence-layer/design.md",
                      "notes": ""},
        "cake-dev2": {"id": "cake-dev2",
                      "description": "openspec/changes/device-confidence-layer/design.md",
                      "notes": ""},
    })

    assert _run("bd close cake-dev1", repo, session_id="s1") is not None
    assert _run("bd close cake-dev2", repo, session_id="s1") is None
    # A different session is a different reader, and asks again.
    assert _run("bd close cake-dev2", repo, session_id="s2") is not None


def test_a_substantive_waiver_closes_without_answering_and_a_hollow_one_does_not(
    repo: Path,
) -> None:
    """Rule 1 escape, with Rule 3 validation: the reason must say something."""
    _design(repo, "device-confidence-layer")
    _fake_bd(repo, {"cake-dev1": {
        "id": "cake-dev1",
        "description": "openspec/changes/device-confidence-layer/design.md",
        "notes": "",
    }})

    substantive = (
        "# close-gate-waiver: superseded by the rollback recorded in the incident "
        "review; nothing shipped to verify\nbd close cake-dev1"
    )
    assert _run(substantive, repo, session_id="w1") is None

    # One reason per rejection category: too short, long enough but pure
    # placeholder, and long enough but only echoing what it waives.
    hollow_reasons = {
        "too-short": "tbd",
        "placeholder": "tbd todo n/a wip fixme none tbd todo",
        "circular": "cake-dev1 device-confidence-layer design.md cake-dev1",
    }
    for category, hollow in hollow_reasons.items():
        command = f"# close-gate-waiver: {hollow}\nbd close cake-dev1"
        assert _run(command, repo, session_id=f"w-{category}") is not None, category

    # Rule 2: both halves of the escape land in the dedicated waiver corpus,
    # which is what the half-life review reads to revise the gate.
    waivers = _signals(repo, ".gate-waivers.jsonl")
    accepted = [w for w in waivers if w["decision"] == "waiver-accepted"]
    rejected = [w for w in waivers if w["decision"] == "waiver-rejected"]
    assert len(accepted) == 1
    assert "superseded by the rollback" in accepted[0]["reason"]
    assert {w["extras"]["rejection"] for w in rejected} == set(hollow_reasons)


def test_an_unreadable_bead_allows_instead_of_guessing_a_design(repo: Path) -> None:
    """A failed lookup must not fall back to an unrelated design."""
    _design(repo, "someone-elses-pipeline")
    _fake_bd(repo, {})  # every `bd show` exits non-zero

    assert _run("bd close cake-ghost", repo) is None


def test_a_missing_bd_executable_allows(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No tracker on PATH is not evidence of an unverified outcome."""
    _design(repo, "someone-elses-pipeline")
    monkeypatch.setenv("PATH", str(repo / "empty-bin"))

    assert _run("bd close cake-dev1", repo) is None


def test_the_ask_names_its_escape_path(repo: Path) -> None:
    """Rule 1: the way forward is written into the message, not the source."""
    _design(repo, "device-confidence-layer")
    _fake_bd(repo, {"cake-dev1": {
        "id": "cake-dev1",
        "description": "openspec/changes/device-confidence-layer/design.md",
        "notes": "",
    }})

    result = _run("bd close cake-dev1", repo, session_id="escape")

    assert result is not None
    reason = result["hookSpecificOutput"]["permissionDecisionReason"]
    assert "close-gate-waiver" in reason
    assert "mis-linked" in reason
