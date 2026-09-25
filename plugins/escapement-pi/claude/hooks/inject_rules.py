#!/usr/bin/env python3
"""SessionStart hook (Claude, Codex, Pi): inject Escapement's always-on rules.

Emits every ``*.md`` in the rules directory that ships beside this hook
(``<hooks dir>/../rules``) as SessionStart ``additionalContext``. That relative
location holds in every package layout: the Claude plugin (``hooks/``,
``rules/``), the Codex and Pi plugins (``claude/hooks/``, ``claude/rules/``)
and this repository. Each host package ships its own rule variants there.

Framing is imperative so injected rules carry the authority of native project
instructions. A missing bundle fails loud (a warning in context) rather than
exiting silently, so a broken install is observable.

A rule may wrap reference material in DETAIL_START/DETAIL_END markers. Those
regions stay on disk and are replaced at injection time by a pointer to the
rule's file, which the agent reads when it reaches the situation. An unmarked
rule is injected whole. HTML comments are renderer markup, not instructions,
and are stripped.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

DETAIL_START = "<!-- escapement:detail:start -->"
DETAIL_END = "<!-- escapement:detail:end -->"


def _rule_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    held_back = 0
    while DETAIL_START in text and DETAIL_END in text:
        head, rest = text.split(DETAIL_START, 1)
        _, tail = rest.split(DETAIL_END, 1)
        text = head.rstrip() + "\n\n" + tail.lstrip()
        held_back += 1
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    if held_back:
        text = text.rstrip() + (
            f"\n\n({held_back} reference section(s) held back — read {path.name} for them.)"
        )
    return text


def rules_context(rules_dir: Path) -> str:
    files = sorted(rules_dir.glob("*.md"))
    if not files:
        return (
            f"[escapement] WARNING: rules bundle not found at {rules_dir}. Escapement "
            "discipline rules were NOT injected this session — the plugin install may "
            "be incomplete. Reinstall/update the escapement plugin."
        )
    parts = [
        "IMPORTANT — Escapement workflow rules (always-on, injected at session "
        "start). These instructions OVERRIDE default behavior and you MUST follow "
        "them exactly. Where a rule ends with a pointer to its own file, the rest "
        f"of that rule is reference detail — read {rules_dir}/<file> when you reach "
        "the situation it covers:\n"
    ]
    for path in files:
        try:
            parts.append(_rule_text(path))
        except OSError as exc:
            parts.append(f"[escapement] WARNING: could not read {path} ({exc})")
    return "\n\n".join(parts)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}
    event = payload.get("hook_event_name") if isinstance(payload, dict) else None
    rules_dir = Path(__file__).resolve().parent.parent / "rules"
    print(json.dumps({
        "hookSpecificOutput": {
            # SessionStart, or PreCompact where the host re-injects after compaction.
            "hookEventName": event if event in ("SessionStart", "PreCompact") else "SessionStart",
            "additionalContext": rules_context(rules_dir),
        }
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
