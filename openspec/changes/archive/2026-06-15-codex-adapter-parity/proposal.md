## Why

Escapement names Claude Code as one adapter, but its durable instruction,
installer, hook, and skill surfaces are still Claude-first. Codex currently gets
only a thin `bd prime` hook and a few copied OpenSpec skills, which means it can
miss the same workflow gates Claude Code receives.

## What Changes

- Add a host-neutral agent-surface manifest as the source of truth for shared
  onboarding, host notes, hook support status, and Codex skill surfaces.
- Render committed `AGENTS.md`, `CLAUDE.md`, and `.codex/hooks.json` from that
  manifest.
- Keep existing `claude/*` implementation paths in this increment while marking
  Claude-only hooks unsupported for Codex with explicit reasons.
- Add generated-surface checks and Codex-specific static guards so Codex surfaces
  cannot silently drift or copy user-local Claude paths.
- Preserve repo-owned `.agents/skills/*` as Codex skill surfaces and remove
  copied tool references that are not available in this repo workflow.

## Capabilities

### New Capabilities

- `agent-surface-parity`: Host-neutral generation and validation for Claude and
  Codex instruction, hook, and skill surfaces.

### Modified Capabilities

- None.

## Impact

- Adds `agent-surfaces/` and `tools/render_agent_surfaces.py`.
- Updates `AGENTS.md`, `CLAUDE.md`, `.codex/hooks.json`, and copied
  `.agents/skills/*` text.
- Adds `tests/test_agent_surfaces.py`.
- Does not add user-level `~/.codex` installer support in this increment.
