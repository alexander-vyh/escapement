<!-- Spec: gascity-supervised-rig -->

## Purpose

One real project registered as a gascity rig, whose agent sessions are spawned, routed, and slept
by the gascity supervisor on demand — replacing the user's hand-launching and hand-tracking of
sessions for that project.

## Requirements

### Requirement: Adoption preserves existing beads

Registering a project that already has a beads database MUST use `gc rig add --adopt` and MUST NOT
lose, duplicate, or rewrite existing issues. The rig's beads become prefix-isolated within the city
store; their content is unchanged.

#### Scenario: Adopt a project with existing beads

- **WHEN** the chosen project (which already has an initialized `.beads/`) is registered via
  `gc rig add --adopt`
- **THEN** the open/closed bead counts and IDs queryable via `bd` from that project are identical
  before and after registration (no loss, no duplication)

#### Scenario: Prefix collision is surfaced, not silently merged

- **WHEN** the rig's derived `issue_prefix` collides with the HQ prefix or another rig's prefix
- **THEN** `gc rig add` errors and names the collision (resolved by an explicit `--prefix`), rather
  than merging the two namespaces

### Requirement: Work routes to a demand-spawned session

Slinging work to the rig MUST cause the supervisor to spawn a session (when none is live) and route
the work to it — the user does not launch the session by hand.

#### Scenario: Sling with no live session

- **WHEN** the user runs `gc sling` for the rig while it has zero live sessions
- **THEN** the supervisor spawns a session, the work bead is routed to it, and the session executes
  the work (observable via the bead's status transition and the produced output)

### Requirement: Idle sessions sleep

A session with no pending work MUST sleep after the configured idle timeout, so coordination is
demand-driven rather than a standing pool of live sessions.

#### Scenario: Session goes idle

- **WHEN** a spawned session completes its work and no further work is routed to it within the idle
  timeout
- **THEN** the session sleeps (no longer counts as a running agent in `gc status`)
