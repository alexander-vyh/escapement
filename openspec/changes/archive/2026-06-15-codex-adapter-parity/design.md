## Context

The repository already states that Escapement should be system-neutral, but the
source files still make Claude Code the de facto canonical host. Claude Code has
the richest adapter today: `claude/settings.template.json`, Claude skills,
Claude hooks, and continuation-harness Stop wiring. Codex has repo-owned
surfaces available through `AGENTS.md`, `.agents/skills`, and `.codex/hooks.json`,
but only a minimal `bd prime` hook existed before this change.

The first increment should make host support explicit and testable without
renaming the existing implementation tree. A broad `claude/*` to neutral-path
move would create a large mechanical diff and hide the actual parity question.

## Goals / Non-Goals

**Goals:**

- Make one manifest the source of truth for generated Claude/Codex surfaces.
- Commit generated outputs and fail CI/local checks when they drift.
- Mark Codex hooks blocking only when the hook has Codex fixture coverage.
- Prevent Claude-only user paths or team semantics from leaking into Codex
  generated surfaces.

**Non-Goals:**

- No `~/.codex` installer support yet.
- No broad rename of `claude/*` implementation paths.
- No attempt to port Claude Stop/ScheduleWakeup/TeamCreate semantics to Codex
  without a dedicated adapter.
- No landing of unrelated residue such as `cache_write_guard`.

## Decisions

1. **Commit generated surfaces.** Generated files are part of the repo contract,
   and the check command proves they match the manifest.

2. **Keep `claude/*` paths for this increment.** The manifest records host
   status while avoiding a large path migration.

3. **Start Codex with fixture-backed blocking hooks only.** The first behavioral
   Codex hook is `test_oracle_brief_gate.py`, which already has Codex Bash
   fixture coverage for finishing commands.

4. **Use dependency-free tooling.** The renderer/checker uses Python stdlib so it
   can run in a fresh checkout without package setup.

## Risks / Trade-offs

- **Partial hook parity can look complete** -> every listed hook has per-host
  status and unsupported reasons; Codex ready hooks require fixtures.
- **Generated files can be hand-edited** -> `tools/render_agent_surfaces.py
  --check` fails on drift.
- **Copied skills can carry host-specific tool names** -> static checks reject
  copied Codex skill references to unavailable task-tracking tools.
- **Existing Claude path names still look canonical** -> the manifest is the
  source of truth now; a later mechanical migration can move paths without
  changing behavior.
