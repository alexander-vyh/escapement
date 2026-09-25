"""Codex oracle for prepatch_failure_gate.

The gate's own oracle (test_prepatch_failure_gate.py) proves the verdict. What
this adds is the Codex path. The command is the Bash dispatcher the generated
plugin registers, run from the vendored plugin copy with no PREPATCH_VERIFY_DIR
override, so the verifier has to resolve from the plugin's own harness/bin as
it does in an installed plugin. The payload is a captured Codex 0.156.1 Bash
payload.

The gate asks. Captured on Codex 0.156.1: a PreToolUse `ask` runs the call and
the model sees nothing. So the vacuous landing only counts as caught if the
dispatcher hands Codex a deny that still carries the repair path.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "claude" / "hooks" / "tests"))

from _codex_host import denial, is_allowed, isolated_env, payload, run  # noqa: E402
from test_prepatch_failure_gate import DETECTING_TEST, VACUOUS_TEST, _make_repo  # noqa: E402


def _landing(repo: Path) -> dict:
    return payload("pre_tool_use_bash_with_workdir",
                   tool_input={"command": "git push origin feature"}, cwd=str(repo))


def test_codex_vacuous_landing_is_blocked_with_its_repair_path(tmp_path):
    repo = _make_repo(tmp_path, VACUOUS_TEST)
    output = run("PreToolUse", "prepatch_failure_gate.py", _landing(repo),
                 isolated_env(tmp_path), timeout=300)
    reason = denial(output)
    assert "still PASSES" in reason
    assert ".prepatch-waiver" in reason, "Codex has no confirm prompt: the waiver is the way through"
    assert "prepatch_verify.py --commit HEAD" in reason, "must say how to reproduce the verdict"


def test_codex_landing_with_a_detecting_test_is_allowed(tmp_path):
    repo = _make_repo(tmp_path, DETECTING_TEST)
    output = run("PreToolUse", "prepatch_failure_gate.py", _landing(repo),
                 isolated_env(tmp_path), timeout=300)
    assert is_allowed(output), output
