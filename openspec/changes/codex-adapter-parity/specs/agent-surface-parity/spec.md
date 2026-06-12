## ADDED Requirements

### Requirement: Neutral manifest renders host instruction surfaces

The system SHALL render committed Claude and Codex instruction surfaces from a
host-neutral manifest and shared onboarding fragments.

#### Scenario: Generated instruction files are current

- **WHEN** `python3 tools/render_agent_surfaces.py --check` is run from the repo root
- **THEN** the command succeeds only if `AGENTS.md`, `CLAUDE.md`, and `.codex/hooks.json` match the manifest-rendered output

#### Scenario: Hand-edited generated file drifts

- **WHEN** a generated target differs from the manifest-rendered output
- **THEN** the check command fails and names the drifting target

### Requirement: Codex ready hooks require fixture-backed commands

The system SHALL mark Codex hooks as blocking only when the hook has explicit
fixture coverage and repository-relative commands.

#### Scenario: Ready Codex hook lacks fixture

- **WHEN** a manifest hook marks `codex.status` as `ready` without fixtures
- **THEN** the check command fails

#### Scenario: Codex hook copies Claude user path

- **WHEN** a Codex hook command contains a user-local Claude path
- **THEN** the check command fails

### Requirement: Codex surfaces exclude Claude-only semantics

Generated Codex instruction and hook surfaces SHALL NOT contain Claude-only
session identifiers, user-local Claude paths, ScheduleWakeup assumptions, or
TeamCreate requirements unless explicitly documented as unsupported outside the
generated Codex surface.

#### Scenario: Codex surface contains Claude-only token

- **WHEN** a generated Codex target contains a forbidden Claude-only token
- **THEN** the check command fails

### Requirement: Codex skills follow repo task tracking

Repo-owned Codex skills SHALL use beads for work tracking and SHALL NOT instruct
agents to use unavailable task-list tools.

#### Scenario: Codex skill references unavailable task tool

- **WHEN** a committed `.agents/skills/*/SKILL.md` file references the unavailable task-list tool
- **THEN** the surface tests fail
