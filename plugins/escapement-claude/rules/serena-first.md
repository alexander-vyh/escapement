# Serena-First Code Navigation — Global Rule

Serena (MCP) is an LSP-backed semantic code tool. When it is available in a
session (`mcp__serena__*` tools present), it is the preferred path for code
navigation and editing. Grep + Read are fallbacks, not defaults.

## On Session Start (any repo with code)

1. Run `mcp__serena__check_onboarding_performed`. If onboarding has not been
   performed, run `mcp__serena__onboarding` before doing substantive work.
2. Run `mcp__serena__list_memories`. Serena maintains its own per-project
   memory store separate from `~/.claude/.../memory/`. Read what is relevant
   to the task — architecture maps, conventions, gotchas may already be
   captured.

## Retrieval Hierarchy (top-down — try the highest matching row first)

| Need | Tool |
|------|------|
| "What's in this file?" | `mcp__serena__get_symbols_overview` (NOT Read) |
| "Find class / method / function X" | `mcp__serena__find_symbol` with name_path |
| "Who calls X? Where is X used?" | `mcp__serena__find_referencing_symbols` |
| "Find a string literal / error message / config key" | `mcp__serena__search_for_pattern` or Grep |
| "Find files by name or glob" | `mcp__serena__find_file` or Glob |
| Full-file Read | Only when the file is < ~200 lines OR you genuinely need top-to-bottom flow |

Never Read a large source file (Campaign-sized, 500+ lines) just to find a
method. That wastes context. Always start with `get_symbols_overview` and
narrow with `find_symbol`.

## Editing Hierarchy

| Change | Tool |
|--------|------|
| Replace a method / class / function body | `mcp__serena__replace_symbol_body` |
| Add a method to a class (or sibling at end) | `mcp__serena__insert_after_symbol` |
| Add an import / new top-level symbol at start | `mcp__serena__insert_before_symbol` |
| Rename a symbol across the codebase | `mcp__serena__rename_symbol` |
| Anything non-symbolic (config, markdown, prose, JSON, YAML) | Edit |

Surgical symbol-level edits avoid the Read+Edit round-trip and reduce the
chance of clobbering nearby code with a bad `old_string` match.

## Per-Project Memory — Write It

When you discover non-obvious project facts during work (architecture
decisions, gotchas, conventions not in CLAUDE.md, tricky integration points),
call `mcp__serena__write_memory` so the next session in this repo benefits.

Memory naming: topical and hierarchical, e.g. `auth/jwt-flow`,
`db/migration-conventions`, `api/versioning-rules`. Keep memories focused —
one topic per file.

This is distinct from your `~/.claude/.../memory/` auto-memory (which is
user-scoped and cross-project). Serena's memory is project-scoped and
cross-session.

## Subagent Dispatch — Brief Them

Subagents do NOT inherit your retrieval discipline. Without instructions they
will grep + read full files. When dispatching agents that will touch code,
include in the prompt:

> This project has Serena (MCP). Use `mcp__serena__find_symbol`,
> `mcp__serena__get_symbols_overview`, and
> `mcp__serena__find_referencing_symbols` instead of Grep + Read for code
> navigation. Use `mcp__serena__replace_symbol_body` and
> `mcp__serena__insert_after_symbol` for code edits. Reserve Grep for string
> literals, error messages, and config keys. Reserve full Read for files
> under ~200 lines.

## When NOT To Use Serena

- Files that are not source code (markdown, YAML, JSON, dotfiles) — use Read / Edit / Grep
- Searching for literal strings (error messages, log lines, regex patterns) — Grep is faster and more precise
- Files Serena's LSP cannot parse (rare; if you see "no symbols found" on a code file, fall back to Read)
- One-off shell-style exploration ("ls this directory") — use Bash or Glob

## Anti-Patterns

- Reading a 900-line model file to find one method — should have been `find_symbol`
- Grepping for a method definition by name — should have been `find_symbol`
- Editing a method by Read + Edit with a fragile `old_string` — should have been `replace_symbol_body`
- Skipping `list_memories` at session start — losing free context the project already has
- Dispatching subagents without telling them Serena exists — they will grep blindly
