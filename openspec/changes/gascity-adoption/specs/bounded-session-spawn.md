<!-- Spec: bounded-session-spawn -->

## Purpose

Spawn guardrails that keep session count — and therefore token spend — bounded under real load, so
adoption never becomes the "swarm" the user cannot afford. This is the capability the cost
anti-metric depends on.

## Requirements

### Requirement: Zero sessions at rest

With no work slung, the city MUST run zero agent sessions. Sessions are spawned by demand, never
kept warm by default.

#### Scenario: Freshly started city, no work

- **WHEN** the city is running and no work has been slung
- **THEN** `gc status` reports 0 running agents (`min_active_sessions = 0`)

### Requirement: Concurrency cap enforced

The city/rig MUST enforce an explicit maximum number of concurrent sessions. Slinging work beyond
the cap queues the excess rather than spawning unboundedly.

#### Scenario: Sling beyond the cap

- **WHEN** more work is slung than the configured max-sessions cap allows
- **THEN** the supervisor spawns up to the cap and the remaining work waits in queue (it is not all
  spawned at once)

### Requirement: Bounded-spawn config is present at adoption

The bounded-spawn settings (min_active_sessions=0, an idle timeout, an explicit max-sessions cap)
MUST be configured as part of standing up the city — not left to defaults and not deferred.

#### Scenario: Inspect the city config after setup

- **WHEN** the city has been stood up per the skeleton
- **THEN** its config explicitly sets `min_active_sessions = 0`, a finite idle timeout, and a finite
  max-sessions cap
