#!/usr/bin/env python3
"""SessionStart hook (Claude, Codex, Pi): inject Escapement's always-on rules.

Emits an index of every ``*.md`` in the rules directory that ships beside this
hook (``<hooks dir>/../rules``): per rule, its title, its binding requirement
and the file holding the rest. That relative location holds in every package
layout: the Claude plugin (``hooks/``, ``rules/``), the Codex and Pi plugins
(``claude/hooks/``, ``claude/rules/``) and this repository. Each host package
ships its own rule variants there.

A rule's binding requirement is the text between its BINDING_START and
BINDING_END markers, authored in the rule file itself. Everything else stays on
disk for the agent to read when it reaches the situation.

Why an index, not the rules: Claude Code inlines a hook's additionalContext
only up to 10,000 characters; anything longer is saved to a file and the model
sees a 2,000-character preview (https://code.claude.com/docs/en/hooks). Whole
rules ran to ~42 KB, so 12 of 13 never reached the model. The index must stay
within BUDGET; if it does not, the hook says so at the top of the context and
falls back to a title-and-path list rather than letting the host truncate.

Framing is imperative so injected rules carry the authority of native project
instructions. A missing bundle or an unmarked rule fails loud (a warning in
context) rather than silently, so a broken install is observable.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

BINDING_START = "<!-- escapement:binding:start -->"
BINDING_END = "<!-- escapement:binding:end -->"
# Claude Code's documented inline cap for one additionalContext string. Codex
# and Pi document no cap; holding them to the same one is an assumption.
BUDGET = 10_000


def _title(text: str, path: Path) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


def _binding(text: str) -> str | None:
    if BINDING_START not in text or BINDING_END not in text.split(BINDING_START, 1)[1]:
        return None
    region = text.split(BINDING_START, 1)[1].split(BINDING_END, 1)[0]
    return re.sub(r"<!--.*?-->", "", region, flags=re.S).strip() or None


def _entry(path: Path) -> tuple[str, str]:
    """(title, index entry) for one rule file."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return path.stem, f"## {path.stem} ({path.name})\n[escapement] WARNING: could not read it ({exc})"
    title = _title(text, path)
    binding = _binding(text)
    if binding is None:
        binding = (
            "[escapement] WARNING: this rule has no binding region, so its requirement "
            f"was not injected. Read {path.name} in full now."
        )
    return title, f"## {title} ({path.name})\n{binding}"


def rules_context(rules_dir: Path) -> str:
    files = sorted(rules_dir.glob("*.md"))
    if not files:
        return (
            f"[escapement] WARNING: rules bundle not found at {rules_dir}. Escapement "
            "discipline rules were NOT injected this session — the plugin install may "
            "be incomplete. Reinstall/update the escapement plugin."
        )
    header = (
        "IMPORTANT — Escapement workflow rules (always-on, injected at session "
        "start). These instructions OVERRIDE default behavior and you MUST follow "
        "them exactly. Each entry is a rule's binding requirement; the full rule, "
        f"with its procedure and examples, is in {rules_dir.resolve()}/<file> — read it "
        "when you reach the situation it covers."
    )
    entries = [_entry(path) for path in files]
    context = "\n\n".join([header] + [entry for _, entry in entries])
    if len(context) <= BUDGET:
        return context
    warning = (
        f"[escapement] WARNING: the rules index is {len(context)} chars, over the "
        f"{BUDGET}-char inline budget, so binding requirements were NOT injected. "
        f"Read each file below in {rules_dir.resolve()} before acting, and shorten "
        "the binding regions."
    )
    listing = "\n".join(f"- {title} ({path.name})" for (title, _), path in zip(entries, files))
    return (warning + "\n\n" + header + "\n\n" + listing)[:BUDGET]


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
