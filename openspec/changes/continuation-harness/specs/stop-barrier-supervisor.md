<!-- Spec: stop-barrier-supervisor -->

## Purpose

[DEFERRED: pending skeleton validation] — a background level-triggered reconciler that observes session state and acts on stalls beyond what the in-CLI Stop hook can see. Examples: subagent stall detection (parent waiting hours on silent subagents), team-level multi-agent coverage, durable wakeup firing.

The supervisor's existence is deliberately deferred to keep the walking skeleton focused on the riskiest-assumption test. The Stop-hook-only architecture is sufficient for skeleton scope; the supervisor is the natural next layer if shadow data validates the gate logic.

## Requirements

### Requirement: Live supervisor process [DEFERRED: pending skeleton validation]

A launchd-managed Python daemon that periodically (every N seconds) reads thread state across all active threads, identifies stalls that the in-turn Stop hook cannot detect, and triggers corrective action — nudge, respawn, or human escalation. Tick interval, action ladder, crash budget, and inter-tick state are specified post-skeleton based on what shadow data reveals.

#### Scenario: Reserved for post-skeleton scope

- **WHEN** the skeleton's one-week shadow run completes and the riskiest assumption is validated by the proof-of-delivery criteria
- **THEN** this requirement is promoted from DEFERRED to ACTIVE; supervisor tick semantics, action ladder, and integration with `would_block_stop` are fully specified in a follow-on increment

### Requirement: Out-of-band stall detection [DEFERRED: pending skeleton validation]

Some stall classes (parent sits for hours on silent subagents; multi-agent team where one member crashed without reporting) cannot be detected by a Stop hook because Stop only fires when the agent itself attempts to terminate. Detecting these requires a separate observer.

#### Scenario: Reserved for post-skeleton scope

- **WHEN** the shadow phase surfaces a stall class that `would_block_stop` cannot catch at Stop time
- **THEN** that stall class becomes a candidate input for this requirement's first active scenario
