# Codex Adapter Notes

Codex reads repository instructions from `AGENTS.md`, repo skills from
`.agents/skills`, and project hooks from `.codex/hooks.json`.

Codex hooks in this repo must use repository-relative commands and must not call
through user-local Claude paths. A Codex hook is marked blocking only when a
fixture proves the current Codex payload shape exercises the intended behavior.
Unsupported Claude-only behavior stays explicit rather than being copied into a
Codex surface as prose.
