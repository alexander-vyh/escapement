"""Every module a deployed hook imports must exist beside it.

Business outcome
----------------
A gate that is installed but cannot import its own helper does not crash — it
fails open, silently, exactly where it was needed. The user sees a hook that is
"deployed" and a file that grows past the limit anyway.

This has now happened twice in this repo. `git_change_scope.py` carries a
comment in the renderer saying so ("Omitting this sibling makes installed hooks
fail open"), and `_codex_patch.py` would have repeated it: the source tree
imports resolve because every hook sits in `claude/hooks/`, so nothing local
fails. The rendered plugin roots are flat copies of a hand-maintained subset,
and a missing name only shows up in a live session.

Independent source of truth
---------------------------
The rendered plugin directories themselves, read the way Python would resolve
`from X import Y` at hook runtime — not the renderer's SHARED_HOOK_SUPPORT set,
which is the thing that gets forgotten.

Rejects
-------
- A helper added to claude/hooks/ and imported, but never registered for
  vendoring -> the import in the deployed copy resolves to nothing.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE_HOOKS = ROOT / "claude" / "hooks"
SOURCE_BIN = ROOT / "bin"

# (source dir, rendered dir) pairs. `bin/` was added after this check caught the same
# failure a third time: #247 split `escapement_worktree_root_health.py` out of
# `escapement_worktree_root.py` and `escapement_worktree_git.py` imports it at module
# scope, but the renderer's vendor list was never updated — so running the renderer
# PRUNED the module from all three plugin trees and every installed worktree guard
# raised ModuleNotFoundError. `--check` stayed green throughout, because it validates
# the targets the renderer knows about, not the ones it forgot.
DEPLOYED_DIRS = [
    (SOURCE_HOOKS, ROOT / "plugins" / "escapement-claude" / "hooks"),
    (SOURCE_HOOKS, ROOT / "plugins" / "escapement" / "claude" / "hooks"),
    (SOURCE_HOOKS, ROOT / "plugins" / "escapement-pi" / "claude" / "hooks"),
    (SOURCE_BIN, ROOT / "plugins" / "escapement-claude" / "bin"),
    (SOURCE_BIN, ROOT / "plugins" / "escapement" / "bin"),
    (SOURCE_BIN, ROOT / "plugins" / "escapement-pi" / "bin"),
]


def sibling_module_names(source_dir: Path = SOURCE_HOOKS) -> set[str]:
    """Modules that live beside the deployed file and can only resolve as siblings."""
    return {p.stem for p in source_dir.glob("*.py")}


def imported_siblings(path: Path, siblings: set[str]) -> set[str]:
    """Sibling modules this file imports, including inside functions.

    Hooks import helpers lazily (inside try/except, after a sys.path insert) so
    a missing helper degrades instead of crashing. ast.walk sees those too — a
    lazy import is exactly the one that fails silently in production.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:  # pragma: no cover - a syntax error is another test's job
        return set()
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            head = node.module.split(".")[0]
            if head in siblings:
                found.add(head)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                head = alias.name.split(".")[0]
                if head in siblings:
                    found.add(head)
    return found


@pytest.mark.parametrize(
    "source_dir,deployed_dir",
    DEPLOYED_DIRS,
    ids=lambda p: "/".join(p.parts[-3:]) if isinstance(p, Path) else str(p),
)
def test_every_deployed_module_can_import_its_helpers(source_dir: Path, deployed_dir: Path):
    if not deployed_dir.is_dir():
        pytest.skip(f"{deployed_dir} is not rendered in this plugin")

    siblings = sibling_module_names(source_dir)
    present = {p.stem for p in deployed_dir.glob("*.py")}
    missing: list[str] = []

    for deployed in sorted(deployed_dir.glob("*.py")):
        for needed in sorted(imported_siblings(deployed, siblings)):
            if needed not in present:
                missing.append(f"{deployed.name} imports {needed}, not vendored here")

    assert not missing, (
        "deployed modules would fail on a missing sibling:\n  "
        + "\n  ".join(missing)
        + "\n\nAdd the module to SHARED_HOOK_SUPPORT or SHARED_RUNTIME_SUPPORT in "
        + "tools/render_agent_surfaces.py."
    )


def test_the_check_would_catch_a_missing_helper(tmp_path):
    """Negative control: prove the detector fires, not just that today is clean."""
    fake = tmp_path / "hooks"
    fake.mkdir()
    (fake / "some_gate.py").write_text(
        "def go():\n    from _gate_signal import record\n    return record\n"
    )
    siblings = sibling_module_names()
    assert "_gate_signal" in imported_siblings(fake / "some_gate.py", siblings)
    assert "_gate_signal" not in {p.stem for p in fake.glob("*.py")}
