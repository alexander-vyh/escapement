<!-- Spec: identity-layer -->

## Purpose

Naming convention `(team_id, agent_name)` for thread directories. Single-agent work uses team-of-one (`solo`). Ensures multi-agent runs have per-agent state without collisions and that the identity shape transfers cleanly to other adapters (Codex, pi.dev) or future managed-agent platforms.

## Requirements

### Requirement: Thread directory naming

Per-thread state MUST be stored at `~/GitHub/escapement/harness/threads/{team_id}/{agent_name}/` where:

- `team_id` is a kebab-case identifier (e.g., `harness-review`, `solo-2026-05-18-073142`)
- `agent_name` is the named agent identifier from `TeamCreate` (e.g., `session-miner`), OR `"solo"` for single-agent sessions with no team context

#### Scenario: Single-agent session

- **WHEN** a Claude Code session starts with no `TeamCreate` having been invoked
- **THEN** state is written to `harness/threads/solo-{timestamp}/solo/`

#### Scenario: Multi-agent team

- **WHEN** a Claude Code session uses `TeamCreate(team_name="harness-review")` and spawns agents named `session-miner`, `rules-auditor`, `best-practices-scout`, `alternatives-scout`
- **THEN** each agent's state is at `harness/threads/harness-review/{agent_name}/`; the parent session's state is at `harness/threads/harness-review/team-lead/` (or equivalent role name)

### Requirement: Identity stability across session resumes

A thread directory MUST be addressable by the same `(team_id, agent_name)` tuple across session restarts triggered by durable wakeups or manual restarts.

#### Scenario: Wakeup-triggered respawn

- **WHEN** a scheduled wakeup fires and respawns a thread for `team-id=harness-review, agent_name=session-miner`
- **THEN** the resumed session writes to the same directory as the original; the contract, journal, and scheduled.json files are continuous
