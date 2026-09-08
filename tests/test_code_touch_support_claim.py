"""Executed point-of-effect control for the `code-touch-detection=partial` claim.

The repo does not let a support claim be asserted in prose alone —
`test_support_claims_match_executed_point_of_effect_controls` requires each claim
to be backed by a control that actually runs the mechanism and demonstrates the
stated limitation. This is that control, in a sibling module because
`tests/test_mission_capability_contract.py` sits at the file-complexity ceiling.

The claim says the Bash-write layer is "high-recall but not exhaustive". A control
for it has to bite in BOTH directions, because either half alone is a lie:

- if nothing were detected, the honest status is `unsupported`, not `partial`
- if everything were detected, the honest status is full enforcement, and calling
  it `partial` would be false modesty that quietly lowers what readers expect of
  the gate

So this test pins a write the detector DOES catch and a write it genuinely MISSES.
The miss is not a bug to be fixed silently: if someone later extends detection to
cover it, this control fails and forces the claim's wording to be revisited.
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness" / "bin"))

import code_touch  # noqa: E402


def _repo(tmp_path: pathlib.Path) -> pathlib.Path:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    return repo


def _transcript(tmp_path: pathlib.Path, command: str) -> str:
    path = tmp_path / "transcript.jsonl"
    row = {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "name": "Bash", "input": {"command": command}}
            ],
        },
    }
    path.write_text(json.dumps(row), encoding="utf-8")
    return str(path)


def test_claim_is_not_unsupported_a_recognised_bash_write_is_detected(tmp_path):
    """Lower bound: the mechanism really does enforce, so `unsupported` would be wrong."""
    repo = _repo(tmp_path)
    target = repo / "src" / "app.py"
    transcript = _transcript(tmp_path, f"sed -i '' 's/x/y/' {target}")
    assert code_touch.touched_code(transcript, cwd=str(repo)) is True


def test_claim_is_not_full_enforcement_an_indirect_write_evades_detection(tmp_path):
    """Upper bound: a write with no redirect and no recognised verb is MISSED.

    This is the exact gap the `partial` status exists to disclose. Python writing
    the file through its own open() is a real thing agents do, and no amount of
    shell-text pattern matching sees it — recognising it would require executing
    the command, which the Stop gate must never do.
    """
    repo = _repo(tmp_path)
    target = repo / "src" / "app.py"
    transcript = _transcript(
        tmp_path, f"""python3 -c "open('{target}','w').write('y = 2')" """
    )
    assert code_touch.touched_code(transcript, cwd=str(repo)) is False, (
        "detection now covers indirect writes — good, but the "
        "code-touch-detection support claim still says 'not exhaustive'. Update the "
        "claim's wording and reason in agent-surfaces/manifest.json, "
        "tools/agent_surface_identity.py and tests/test_mission_capability_contract.py "
        "before relaxing this control."
    )


def test_claim_fails_open_on_missing_evidence(tmp_path):
    """The declared failure direction: absent evidence never manufactures a block."""
    repo = _repo(tmp_path)
    assert code_touch.touched_code("", cwd=str(repo)) is False
    assert code_touch.touched_code(str(tmp_path / "absent.jsonl"), cwd=str(repo)) is False
    # No cwd = no repo to judge against.
    assert code_touch.touched_code(_transcript(tmp_path, "sed -i '' s/x/y/ a.py"), cwd="") is False


def test_codex_claim_the_gate_is_inert_when_no_transcript_is_supplied(tmp_path):
    """Point-of-effect control for `codex-code-touch-detection=unsupported`.

    The Codex Stop adapter calls `load_thread_state(thread_dir, recent_user_message=...)`
    with no transcript path and no cwd (harness/bin/codex_stop_hook.py), because Codex
    transcripts are not parsed. This reproduces that exact call and asserts the
    consequence the claim states: touched_code is false, so a Codex session that
    changed code still stops as conversational.

    If someone later teaches the Codex adapter to supply a transcript, this control
    fails and forces the claim to be re-stated rather than quietly going stale.
    """
    sys.path.insert(0, str(ROOT / "harness" / "bin"))
    from would_block_stop import load_thread_state, would_block_stop  # noqa: E402

    thread_dir = tmp_path / "thread"
    thread_dir.mkdir()
    state = load_thread_state(thread_dir, recent_user_message=None)

    assert state["touched_code"] is False
    assert would_block_stop(state) == ("allow", "conversational")


def test_codex_stop_adapter_still_passes_no_transcript():
    """The claim's premise, asserted against the adapter itself rather than prose."""
    source = (ROOT / "harness" / "bin" / "codex_stop_hook.py").read_text(encoding="utf-8")
    call = source.split("load_thread_state(", 1)[1].split(")", 1)[0]
    assert "transcript_path" not in call, (
        "the Codex adapter now supplies a transcript — code-touch detection may work "
        "there, so codex-code-touch-detection=unsupported must be revisited"
    )
