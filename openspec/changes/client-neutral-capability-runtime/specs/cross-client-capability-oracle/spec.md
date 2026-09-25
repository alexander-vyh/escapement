<!-- Spec: cross-client-capability-oracle -->

## Purpose

Prove neutral capability behavior through independent Pi, Codex, and Claude evidence rather than trusting adapter-authored decisions or documentation.

## ADDED Requirements

### Requirement: Readiness requires independent installed-client evidence

A client/capability pair MUST NOT be marked ready solely because the adapter loads or the runtime returns the expected object. Readiness requires installed-version provenance, a controlled fixture, expected behavior frozen outside the adapter, and observed native or user-visible evidence.

#### Scenario: All selected clients prove the skeleton capability

- **WHEN** controlled Pi, Codex, and Claude fixtures exercise the same neutral continuation/oracle capability and independently observe the expected state and user-visible result
- **THEN** the oracle reports equivalent behavior with each client’s hard/advisory realization recorded

#### Scenario: Adapter self-report is the only evidence

- **WHEN** an adapter reports support but no independent native or user-visible point-of-effect evidence exists
- **THEN** the oracle rejects readiness and the registry cannot mark the capability hard

### Requirement: Negative controls reject false equivalence

The oracle MUST include a negative control where missing identity, unsupported resumption, or a consequential unresolved action cannot become an implicit allow or hard-enforced claim.

#### Scenario: Unsupported resumption is presented as hard

- **WHEN** a fixture omits a proven native resume mechanism but the adapter reports hard continuation
- **THEN** the oracle fails the adapter and requires advisory or unavailable status

#### Scenario: Consequential unresolved action is auto-allowed

- **WHEN** a controlled fixture leaves a consequential action unresolved
- **THEN** the oracle observes that the action remains unexecuted and fails any implementation that silently resumes it
