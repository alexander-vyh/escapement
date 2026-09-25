<!-- Spec: neutral-event-action-contract -->

## Purpose

Provide one host-neutral vocabulary for lifecycle inputs and capability decisions. The contract preserves identity, provenance, state transitions, and enforcement realization without depending on Pi, Codex, or Claude hook names.

## ADDED Requirements

### Requirement: Normalize lifecycle identity and provenance

A normalized event MUST contain a capability/event kind, session identity, actor identity, repository/worktree identity when available, client identity, installed client version, and a correlation identity. Missing required identity MUST be represented as incomplete input rather than inferred.

#### Scenario: Complete client event is normalized

- **WHEN** a Pi, Codex, or Claude adapter receives a controlled lifecycle event with required identity and version evidence
- **THEN** the neutral runtime receives one normalized event preserving that identity and client provenance

#### Scenario: Required identity is missing

- **WHEN** an adapter cannot determine the session or actor identity required for a capability decision
- **THEN** the runtime rejects the event as incomplete and does not produce an implicit allow

### Requirement: Return structured capability decisions

The runtime MUST return a structured decision containing the capability identity, action, enforcement level, resulting state transition, explanation, and correlation identity. Client hook names MUST NOT be required to interpret the decision.

#### Scenario: Equivalent events receive equivalent semantics

- **WHEN** Pi, Codex, and Claude fixtures represent the same semantic capability event
- **THEN** the runtime returns the same capability action and state transition while preserving each client’s provenance

#### Scenario: Ambiguous lifecycle input is not authorized

- **WHEN** a normalized event contains an ambiguous action or dependency that affects authority
- **THEN** the runtime returns an incomplete or advisory result and does not issue an implicit hard allow
