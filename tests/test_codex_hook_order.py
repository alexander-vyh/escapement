"""A release that enables a new Codex hook must not move the ones already there.

Codex keys hook trust by ``<event>:<group index>:<hook index>`` and checks the
definition found at that index, so a new group rendered ahead of existing ones
silently untrusts every group it displaces (observed after #264: all five
SessionStart hooks stopped running). The rendered order is judged against the
committed file the user's grants were made for.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from render_agent_surfaces import _render_codex_plugin_hooks  # noqa: E402


def _hook(hook_id: str) -> dict:
    return {
        "id": hook_id,
        "source": f"claude/hooks/{hook_id}.py",
        "hosts": {"codex": {"status": "ready", "events": [
            {"event": "SessionStart", "matcher": "", "command": f"python3 -B claude/hooks/{hook_id}.py"},
        ]}},
    }


def _order(rendered: str) -> list[str]:
    groups = json.loads(rendered)["hooks"]["SessionStart"]
    return [group["hooks"][0]["command"].rsplit("/", 1)[1].rstrip('"') for group in groups]


def test_new_hook_is_appended_after_the_already_shipped_ones():
    shipped = json.loads(_render_codex_plugin_hooks({"hooks": [_hook("a"), _hook("b")]}))
    manifest = {"hooks": [_hook("new"), _hook("a"), _hook("b")]}

    assert _order(_render_codex_plugin_hooks(manifest, shipped)) == ["a.py", "b.py", "new.py"]


def test_first_release_follows_manifest_order():
    manifest = {"hooks": [_hook("new"), _hook("a")]}

    assert _order(_render_codex_plugin_hooks(manifest, None)) == ["new.py", "a.py"]


def test_removed_hook_closes_its_gap_without_reordering_the_rest():
    shipped = json.loads(_render_codex_plugin_hooks({"hooks": [_hook("a"), _hook("b"), _hook("c")]}))
    manifest = {"hooks": [_hook("c"), _hook("a")]}

    assert _order(_render_codex_plugin_hooks(manifest, shipped)) == ["a.py", "c.py"]


def _parted(hook_id: str, parts: int) -> dict:
    hook = _hook(hook_id)
    base = hook["hosts"]["codex"]["events"][0]
    hook["hosts"]["codex"]["events"] = [
        dict(base, command=f"{base['command']} --part {k} --of {parts}") for k in range(1, parts + 1)
    ]
    return hook


def _commands(rendered: str) -> list[str]:
    groups = json.loads(rendered)["hooks"]["SessionStart"]
    return [group["hooks"][0]["command"].split("claude/hooks/", 1)[1] for group in groups]


def test_new_hook_goes_after_every_part_of_a_parted_hook():
    """One script registered as several parts shares one identity; a later hook
    must still land after all of them, not in front of the parts."""
    shipped = json.loads(_render_codex_plugin_hooks({"hooks": [_hook("a"), _parted("rules", 3)]}))
    manifest = {"hooks": [_hook("new"), _hook("a"), _parted("rules", 3)]}

    assert _commands(_render_codex_plugin_hooks(manifest, shipped)) == [
        'a.py"',
        'rules.py" --part 1 --of 3',
        'rules.py" --part 2 --of 3',
        'rules.py" --part 3 --of 3',
        'new.py"',
    ]
