<!-- Spec: capability-registry -->

## Purpose

Describe neutral capabilities and the evidence-backed adapter realization available for each installed client. The registry is the source for generated capability claims, not a client-specific policy source.

## ADDED Requirements

### Requirement: Capabilities have neutral identity and evidence

Every registered capability MUST have a stable neutral identifier, required event inputs, decision vocabulary, and evidence requirements independent of client hook names. Generated surfaces MUST reference the neutral identifier.

#### Scenario: Generated claim resolves to a neutral capability

- **WHEN** a renderer emits Pi, Codex, or Claude capability metadata
- **THEN** the claim resolves to a registry capability and identifies the adapter evidence supporting it

#### Scenario: Host-derived source is presented as authority

- **WHEN** a registry entry attempts to designate Claude or Codex as the source of a neutral capability
- **THEN** registry validation fails rather than accepting a host-owned policy source

### Requirement: Adapter realization is explicit

Each client/capability pair MUST declare `hard`, `advisory`, or `unavailable` realization with installed-version provenance and fixture evidence. Missing or stale evidence MUST NOT be reported as hard enforcement.

#### Scenario: Installed fixture proves hard realization

- **WHEN** an independent fixture records the installed client version and observes the adapter applying the decision at its point of effect
- **THEN** the registry may mark that client/capability pair as hard

#### Scenario: Documentation claims an unproven hook

- **WHEN** a capability is documented but the installed client has no fixture-backed point-of-effect evidence
- **THEN** the registry reports advisory or unavailable status and generated claims expose that limitation
