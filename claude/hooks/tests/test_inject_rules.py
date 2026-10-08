"""inject_rules.py injects the rules bundle that ships beside it, in every
host package layout, as ordered parts that each fit the host's inline limit,
and fails loud when the bundle is missing or cannot fit."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "inject_rules.py"
LIMIT = 9_000


def _install(root: Path, hooks_rel: str, rules_rel: str, rules: dict[str, str]) -> Path:
    hook = root / hooks_rel / HOOK.name
    hook.parent.mkdir(parents=True)
    shutil.copy2(HOOK, hook)
    if rules:
        rules_dir = root / rules_rel
        rules_dir.mkdir(parents=True)
        for name, text in rules.items():
            (rules_dir / name).write_text(text, encoding="utf-8")
    return hook


def _run(hook: Path, *args: str, event: str = "SessionStart") -> dict | None:
    completed = subprocess.run(
        [sys.executable, str(hook), *args],
        input=json.dumps({"hook_event_name": event, "session_id": "s"}),
        capture_output=True,
        text=True,
        timeout=10,
        check=True,
    )
    if not completed.stdout.strip():
        return None
    return json.loads(completed.stdout)["hookSpecificOutput"]


def _parts(hook: Path, of: int) -> list[str | None]:
    out = []
    for k in range(1, of + 1):
        result = _run(hook, "--part", str(k), "--of", str(of))
        out.append(result["additionalContext"] if result else None)
    return out


def _rule(title: str, size: int) -> str:
    text = f"# {title}\n\n"
    filler = f"{title} requirement sentence. "
    while len(text.encode()) + len(filler) < size:
        text += filler
    return text + "\n"


def test_codex_plugin_layout_injects_the_packages_own_rule_variants(tmp_path):
    hook = _install(
        tmp_path, "plugin/claude/hooks", "plugin/claude/rules",
        {"teams.md": "# Teams\n\nDispatch reviewers with spawn_agent.\n"},
    )
    output = _run(hook, "--part", "1", "--of", "4")

    assert output["hookEventName"] == "SessionStart"
    assert output["additionalContext"].endswith("\n\n# Teams\n\nDispatch reviewers with spawn_agent.\n")


def test_bad_part_arguments_are_rejected(tmp_path):
    hook = _install(tmp_path, "p/hooks", "p/rules", {"a.md": "# A\n\nRule A.\n"})
    for args in (["--part", "0", "--of", "3"], ["--part", "-1", "--of", "3"],
                 ["--part", "2"], ["--of", "3"], ["--part", "1", "--of", "0"]):
        completed = subprocess.run(
            [sys.executable, str(hook), *args], input="{}",
            capture_output=True, text=True, timeout=10,
        )
        assert completed.returncode != 0, args
        assert completed.stdout == "", args
        assert "--part" in completed.stderr or "--of" in completed.stderr, args


def test_rules_are_packed_whole_into_labelled_parts_under_the_limit(tmp_path):
    rules = {"a.md": _rule("Alpha", 4_000), "b.md": _rule("Bravo", 4_000), "c.md": _rule("Charlie", 4_000)}
    hook = _install(tmp_path, "plugin/hooks", "plugin/rules", rules)
    parts = _parts(hook, 4)

    assert parts[2] is None and parts[3] is None, "unused parts emit nothing"
    first, second = parts[0], parts[1]
    assert first.split("\n\n", 1)[1] == rules["a.md"] + rules["b.md"]
    assert second.split("\n\n", 1)[1] == rules["c.md"]
    for k, part in enumerate((first, second), 1):
        header = part.split("\n", 1)[0]
        assert f"part {k} of 4" in header and "OVERRIDE default behavior" in header
        assert len(part.encode()) <= LIMIT
    assert "a.md" in first.split("\n", 1)[0] and "c.md" in second.split("\n", 1)[0]


def test_budget_counts_utf8_bytes_as_codex_truncates(tmp_path):
    """Codex truncates by bytes: two 3,000-char rules of em-dashes are ~9 KB each."""
    dashes = "# Dash\n\n" + "—" * 2_900 + "\n"
    hook = _install(tmp_path, "plugin/hooks", "plugin/rules", {"a.md": dashes, "b.md": dashes})
    parts = [p for p in _parts(hook, 3) if p]

    assert len(parts) == 2
    assert all(len(p.encode()) <= LIMIT for p in parts)


def test_no_arguments_emits_every_rule_in_one_context_for_pi(tmp_path):
    rules = {"a.md": _rule("Alpha", 6_000), "b.md": _rule("Bravo", 6_000)}
    hook = _install(tmp_path, "plugin/claude/hooks", "plugin/claude/rules", rules)
    context = _run(hook)["additionalContext"]

    header, body = context.split("\n\n", 1)
    assert body == rules["a.md"] + rules["b.md"]
    assert "part 1 of 1" in header and "OVERRIDE default behavior" in header


def test_detail_region_is_held_back_with_a_pointer_and_neighbours_survive(tmp_path):
    body = (
        "# Bracketed\n\nImperative before.\n\n"
        "<!-- escapement:detail:start -->\n"
        "A long worked example that only matters once you are already doing it.\n"
        "<!-- escapement:detail:end -->\n\n"
        "Imperative after.\n"
    )
    hook = _install(tmp_path, "plugin/hooks", "plugin/rules", {"b.md": body})
    context = _run(hook, "--part", "1", "--of", "2")["additionalContext"]
    header = context.split("\n", 1)[0]

    assert "Imperative before." in context and "Imperative after." in context
    assert "only matters once you are already doing it" not in context
    assert "b.md" in header and str((tmp_path / "plugin/rules").resolve()) in header


def test_unclosed_marker_injects_the_rule_intact(tmp_path):
    body = "# Half\n\nAlways do this.\n\n<!-- escapement:detail:start -->\n\nNever closed.\n"
    hook = _install(tmp_path, "plugin/hooks", "plugin/rules", {"half.md": body})
    context = _run(hook, "--part", "1", "--of", "1")["additionalContext"]

    assert "Always do this." in context and "Never closed." in context


def test_rule_too_big_for_one_part_is_named_loudly(tmp_path):
    hook = _install(tmp_path, "plugin/hooks", "plugin/rules", {"huge.md": _rule("Huge", 12_000)})
    context = _run(hook, "--part", "1", "--of", "2")["additionalContext"]

    assert context.startswith("[escapement] WARNING")
    assert "huge.md" in context.split("\n", 1)[0]


def test_more_parts_than_registered_entries_warns_in_the_last_part(tmp_path):
    rules = {f"{c}.md": _rule(c, 6_000) for c in "abc"}
    hook = _install(tmp_path, "plugin/hooks", "plugin/rules", rules)
    parts = _parts(hook, 2)
    last_header = parts[1].split("\n", 1)[0]

    assert "WARNING" in last_header and "c.md" in last_header
    assert "not injected" in last_header


def test_missing_bundle_still_fails_loud(tmp_path):
    hook = _install(tmp_path, "plugin/hooks", "plugin/rules", {})
    parts = _parts(hook, 3)

    assert "WARNING" in parts[0] and "NOT injected" in parts[0]
    assert parts[1] is None and parts[2] is None
