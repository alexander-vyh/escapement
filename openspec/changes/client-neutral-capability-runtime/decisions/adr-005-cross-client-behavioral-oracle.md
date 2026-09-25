# ADR-005: Validate Capability Behavior Across All Selected Clients

## Status

Accepted

## Context

A normalized object test can pass while an adapter drops a field, applies the wrong native action, or claims support beyond the installed client version. Documentation and shared helper reuse do not prove equivalent user-visible behavior.

The first neutral capability must therefore be tested through Pi, Codex, and Claude using evidence independent of the implementation's own decision object.

## Decision

The walking skeleton uses controlled installed-client fixtures and an independent oracle. Each fixture records client/version provenance, native event/output evidence, expected state transition, and expected hard/advisory realization before the adapter result is accepted. The oracle inspects native behavior, neutral state, supervisor activity, and user-visible status.

A capability cannot be marked ready for an adapter solely because the adapter loads, a version field is self-reported, or the neutral runtime returns the expected object.

## Consequences

- The first proof is slower than a unit-only adapter test but falsifies the actual cross-client assumption.
- Fixture maintenance follows installed client versions and must be explicit in generated capability claims.
- The same oracle pattern can protect later capability migrations and prevent documentation-only parity claims.
