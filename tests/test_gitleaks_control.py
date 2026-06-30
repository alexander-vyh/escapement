"""Oracle for the gitleaks secret-scanning control.

This is the "Observe" rung, not the "parse" rung: a config that merely loads
proves nothing. These tests PLANT a real-shaped secret and assert the repo's
own .gitleaks.toml causes gitleaks to flag it (negative control), and that a
clean tree passes (positive control). The whole-repo scan is a regression guard
so a future committed secret turns this suite red.

The fake key is assembled at runtime ("AKIA" + body) so THIS source file never
contains a contiguous detectable secret — otherwise the gate would flag its own
test fixture.
"""
import shutil
import subprocess
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
CONFIG = REPO_ROOT / ".gitleaks.toml"

requires_gitleaks = pytest.mark.skipif(
    shutil.which("gitleaks") is None, reason="gitleaks not installed"
)


def _scan(source: pathlib.Path) -> int:
    """Run gitleaks against a directory tree (no git history) with our config.

    Returns the gitleaks exit code: 0 = clean, nonzero = leak(s) found.
    """
    proc = subprocess.run(
        [
            "gitleaks", "detect",
            "--no-git",
            "--no-banner",
            "--redact",
            "--source", str(source),
            "--config", str(CONFIG),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return proc.returncode


def test_config_exists():
    # The control's config must actually be present — the exact "cited in prose
    # but absent in the repo" failure this work closes.
    assert CONFIG.is_file(), f"{CONFIG} missing — the gitleaks control is not installed"


@requires_gitleaks
def test_detects_planted_github_token(tmp_path):
    # Negative control: a planted secret MUST be caught. A GitHub PAT
    # (ghp_ + 36 mixed-case alnum) is matched by the default `github-pat` rule.
    # Assembled at runtime so this source file holds no contiguous token.
    fake_token = "ghp_" + "A1b2C3d4E5f6G7h8I9j0KlMnOpQrStUvWxYz"
    (tmp_path / "leak.txt").write_text(f"github_token = {fake_token}\n")
    assert _scan(tmp_path) != 0, "gitleaks did not flag a planted GitHub token — control is inert"


@requires_gitleaks
def test_clean_tree_passes(tmp_path):
    # Positive control: ordinary, secret-free content must NOT be flagged.
    (tmp_path / "ok.txt").write_text("just some harmless prose, no credentials here\n")
    assert _scan(tmp_path) == 0, "gitleaks flagged a clean tree — control over-fires"


@requires_gitleaks
def test_repo_history_is_clean():
    # Regression guard: scanning the real repo (full git history) must be clean.
    # If this turns red, a real secret was committed — that is the gate working.
    proc = subprocess.run(
        ["gitleaks", "detect", "--no-banner", "--redact", "--config", str(CONFIG)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, (
        "gitleaks found a secret in the repo history:\n"
        f"{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
    )
