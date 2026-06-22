"""Regression: INSTALL.sh's run() must execute commands as argv, never via eval.

Bug (CISO MEDIUM-A, 2026-06-21 roundtable): run() used `eval "$*"` over command
strings assembled from `$HOME`-derived path variables (CLAUDE_DIR="$HOME/.claude").
Call sites wrapped vars in single quotes (`run "mkdir -p '$CLAUDE_DIR'/..."`), so
SPACES were handled — but a path containing a single quote or shell metacharacter
breaks out of that quoting and eval executes it. A CLAUDE_DIR like
`/Users/o'brien/...` corrupts the command; a crafted HOME is arbitrary code
execution.

Business invariant: run() must pass its arguments to the target program as a
literal argv vector, so path metacharacters are inert data, never executed shell.

Independent oracle: a path argument carrying an injection payload
(`x'; touch SENTINEL; '`) must NOT cause SENTINEL to be created.

Fragile implementation this rejects: `run() { eval "$*"; }` with single-quote-
wrapped call sites. The mutation guard below proves the payload genuinely injects
under that form, so a clean result on the real run() is not vacuous.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

INSTALL_SH = Path(__file__).resolve().parent.parent / "INSTALL.sh"


def _extract_run_def() -> str:
    """Return the REAL run() function block from INSTALL.sh (not a copy)."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    m = re.search(r"^run\(\) \{.*?^\}", text, re.DOTALL | re.MULTILINE)
    assert m, "could not locate run() definition in INSTALL.sh"
    return m.group(0)


def test_install_sh_has_no_eval_star():
    """Static guard: the eval-over-$* construct must not return."""
    text = INSTALL_SH.read_text(encoding="utf-8")
    assert 'eval "$*"' not in text, "INSTALL.sh reintroduced `eval \"$*\"`"


def test_real_run_does_not_execute_injected_metacharacters(tmp_path: Path):
    """Behavioral oracle on the ACTUAL run() bytes: argv path is inert."""
    run_def = _extract_run_def()
    sentinel = tmp_path / "SENTINEL_INJECTED"
    # A directory path whose name carries an injection payload.
    payload_dir = tmp_path / f"x'; touch {sentinel}; '"
    script = f"""
set -uo pipefail
DRY_RUN=false
{run_def}
# New-style call site: real argv, var passed as a single literal argument.
run mkdir -p "{payload_dir}"
"""
    subprocess.run(["bash", "-c", script], check=False,
                   capture_output=True, text=True)
    assert not sentinel.exists(), (
        "run() executed an injected command — eval-style behavior regressed"
    )
    assert payload_dir.is_dir(), (
        "run() did not create the literal directory; argv semantics broken"
    )


def test_mutation_guard_eval_form_DOES_inject(tmp_path: Path):
    """Validity check: the payload genuinely injects under the OLD eval form.

    If this did not inject, the test above would be vacuous. This is the negative
    control proving the oracle discriminates the fragile implementation.
    """
    sentinel = tmp_path / "SENTINEL_INJECTED"
    payload_dir = tmp_path / f"x'; touch {sentinel}; '"
    script = f"""
set -uo pipefail
DRY_RUN=false
run() {{ eval "$*"; }}          # the OLD, fragile implementation
# Old-style call site: single-quote-wrapped variable inside one string arg.
run "mkdir -p '{payload_dir}'"
"""
    subprocess.run(["bash", "-c", script], check=False,
                   capture_output=True, text=True)
    assert sentinel.exists(), (
        "payload failed to inject under eval form — test would be vacuous; "
        "strengthen the payload"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
