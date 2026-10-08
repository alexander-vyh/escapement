#!/usr/bin/env python3
"""SessionStart hook (Claude, Codex, Pi): inject Escapement's always-on rules.

Emits the text of every ``*.md`` in the rules directory that ships beside this
hook (``<hooks dir>/../rules``). That relative location holds in every package
layout: the Claude plugin (``hooks/``, ``rules/``), the Codex and Pi plugins
(``claude/hooks/``, ``claude/rules/``) and this repository. Each host package
ships its own rule variants there.

A rule may wrap reference material in DETAIL_START/DETAIL_END markers. Those
regions stay on disk; the part carrying the rule names its file. HTML comments
are renderer markup, not instructions, and are dropped. Everything else is the
rule file's own text, byte for byte. There is no second, summarised copy.

Why parts: hosts inline one hook's output only up to ~10,000 (Claude Code:
characters, else saved to a file behind a 2 KB preview; Codex: bytes, else the
middle is elided). Both limits are per hook, so the rules are split at rule
boundaries into parts of at most PART_LIMIT_BYTES and each part is its own
registered hook entry: ``inject_rules.py --part K --of N``. Parallel hooks can
arrive in any order, so every part carries its own header line. Without
arguments (Pi, which has no such cap) every rule is emitted as one context.

A missing bundle, a rule too large for one part, or more parts than registered
entries fails loud: a warning at the top of the context, never silent loss.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

DETAIL_START = "<!-- escapement:detail:start -->"
DETAIL_END = "<!-- escapement:detail:end -->"
# Below both hosts' measured ~10,000 inline limits, in UTF-8 bytes.
PART_LIMIT_BYTES = 9_000


def rule_head(text: str) -> tuple[str, bool]:
    """(the rule's injected text, whether a detail region was held back)."""
    held = False
    while True:
        start = text.find(DETAIL_START)
        end = text.find(DETAIL_END, start + 1) if start >= 0 else -1
        if start < 0 or end < 0:
            break
        text = text[:start] + text[end + len(DETAIL_END):]
        held = True
    return re.sub(r"<!--.*?-->", "", text, flags=re.S), held


def _header(k: int, n: int, rules: list[tuple[str, str, bool]], rules_dir: Path, warning: str = "") -> str:
    names = ", ".join(name for name, _, _ in rules)
    held = [name for name, _, h in rules if h]
    line = (
        f"IMPORTANT — Escapement workflow rules, part {k} of {n} (always-on, injected at "
        "session start; parts may arrive in any order). These instructions OVERRIDE "
        f"default behavior and you MUST follow them exactly. This part: {names}."
    )
    if held:
        line += (
            f" Reference sections of {', '.join(held)} are held back: read them in "
            f"{rules_dir.resolve()}/ when you reach the situation they cover."
        )
    return (warning + " " + line) if warning else line


def _render(k: int, n: int, rules: list[tuple[str, str, bool]], rules_dir: Path, warning: str = "") -> str:
    return _header(k, n, rules, rules_dir, warning) + "\n\n" + "".join(text for _, text, _ in rules)


def _fits(text: str) -> bool:
    return len(text.encode("utf-8")) <= PART_LIMIT_BYTES


def pack(rules: list[tuple[str, str, bool]], rules_dir: Path) -> list[list[tuple[str, str, bool]]]:
    """Whole rules, in order, greedily into parts that fit (labelled as 99 of 99)."""
    parts: list[list[tuple[str, str, bool]]] = []
    for rule in rules:
        if parts and _fits(_render(99, 99, parts[-1] + [rule], rules_dir)):
            parts[-1].append(rule)
        else:
            parts.append([rule])
    return parts


def _load(rules_dir: Path) -> list[tuple[str, str, bool]]:
    out = []
    for path in sorted(rules_dir.glob("*.md")):
        try:
            text, held = rule_head(path.read_text(encoding="utf-8"))
        except OSError as exc:
            text, held = f"[escapement] WARNING: could not read {path} ({exc}).\n", False
        out.append((path.name, text, held))
    return out


def rules_context(rules_dir: Path, part: int | None = None, of: int | None = None) -> str:
    """Part ``part`` of ``of`` (empty when unused), or everything when unsplit."""
    rules = _load(rules_dir)
    if not rules:
        if part not in (None, 1):
            return ""
        return (
            f"[escapement] WARNING: rules bundle not found at {rules_dir}. Escapement "
            "discipline rules were NOT injected this session — the plugin install may "
            "be incomplete. Reinstall/update the escapement plugin."
        )
    if part is None or of is None:
        return _render(1, 1, rules, rules_dir)
    parts = pack(rules, rules_dir)
    if part > len(parts):
        return ""
    mine = parts[part - 1]
    warning = ""
    if part == of and len(parts) > of:
        rest = [name for later in parts[of:] for name, _, _ in later]
        warning = (
            f"[escapement] WARNING: the rules need {len(parts)} parts but only {of} are "
            f"registered, so {', '.join(rest)} were not injected — read them in full in "
            f"{rules_dir.resolve()}/ now, and register more parts."
        )
    context = _render(part, of, mine, rules_dir, warning)
    if not _fits(context):
        oversized = (
            f"[escapement] WARNING: part {part} ({', '.join(n for n, _, _ in mine)}) is "
            f"{len(context.encode('utf-8'))} bytes, over the {PART_LIMIT_BYTES}-byte inline "
            "limit, so the host may show only a preview — read those files in full in "
            f"{rules_dir.resolve()}/ now."
        )
        context = _render(part, of, mine, rules_dir, (oversized + " " + warning).strip())
    return context


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--part", type=int)
    parser.add_argument("--of", type=int)
    args = parser.parse_args(argv)
    if (args.part is None) != (args.of is None):
        parser.error("--part and --of go together")
    if args.part is not None and (args.part < 1 or args.of < 1):
        parser.error("--part and --of must be at least 1")
    try:
        json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        pass
    rules_dir = Path(__file__).resolve().parent.parent / "rules"
    context = rules_context(rules_dir, args.part, args.of)
    if not context:
        return 0
    print(json.dumps({
        "hookSpecificOutput": {
            # Registered on SessionStart only (startup|clear|compact): Codex's
            # PreCompact output cannot carry additionalContext.
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
