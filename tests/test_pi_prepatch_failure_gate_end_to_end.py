"""prepatch_failure_gate on Pi, driven through the rendered extension.

The gate loads its verifier by path from the package's own harness/bin. The
repositories here carry no harness and PREPATCH_VERIFY_DIR is unset, so a
block can only come from the verifier the Pi package vendors. Without that
file the gate fails open, and the last case shows that happening.

On Pi the gate's `ask` becomes a block (Pi has no confirm prompt), so a
vacuous landing counts as caught only if the block names the repair path.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from pi_extension_harness import Session, pi_env, rendered_plugin, run

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_prepatch_failure_gate import DETECTING_TEST, VACUOUS_TEST, _make_repo  # noqa: E402

LANDING = "git push origin feature"


@pytest.fixture(scope="module")
def plugin(tmp_path_factory):
    return rendered_plugin(tmp_path_factory)


def _land(plugin: Path, tmp_path: Path, test_body: str) -> dict:
    repo = _make_repo(tmp_path, test_body)
    assert not (repo / "harness").exists()
    env = pi_env(tmp_path)
    env.pop("PREPATCH_VERIFY_DIR", None)
    [outcome] = run(plugin, [Session(repo).tool_call("bash", {"command": LANDING})], env)
    return outcome


def test_pi_vacuous_landing_is_blocked_by_the_vendored_verifier(plugin, tmp_path):
    outcome = _land(plugin, tmp_path, VACUOUS_TEST)

    result = outcome["result"]
    assert result and result["block"] is True, outcome
    assert "still PASSES" in result["reason"]
    assert ".prepatch-waiver" in result["reason"], "Pi has no confirm prompt: the waiver is the way through"
    assert "prepatch_verify.py --commit HEAD" in result["reason"], "must say how to reproduce the verdict"


def test_pi_landing_with_a_detecting_test_runs(plugin, tmp_path):
    outcome = _land(plugin, tmp_path, DETECTING_TEST)

    assert outcome["result"] is None, outcome


def test_pi_package_without_the_verifier_fails_open(tmp_path_factory, tmp_path):
    stripped = rendered_plugin(tmp_path_factory)
    (stripped / "harness" / "bin" / "prepatch_verify.py").unlink()

    outcome = _land(stripped, tmp_path, VACUOUS_TEST)

    assert outcome["result"] is None, "the block above must come from the vendored verifier"
