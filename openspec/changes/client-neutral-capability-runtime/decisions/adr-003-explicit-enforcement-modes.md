# ADR-003: Enforcement Realization Is Explicit

## Status

Accepted

## Context

Pi, Codex, and Claude do not expose identical interception and lifecycle primitives. Treating a shared decision as hard enforcement on every host would create false safety claims; treating every difference as a semantic fork would destroy client neutrality.

The repository already distinguishes documented capability from fixture-backed behavior. The neutral runtime needs the same distinction at the point where an adapter applies a decision.

## Decision

Every adapter capability declares and records one realization mode: `hard`, `advisory`, or `unavailable`. The neutral runtime continues to own the semantic decision. The adapter owns only whether and how that decision is enforced through the installed client.

An advisory result MUST be visible to the user and persisted with client/version provenance. Missing, ambiguous, or stale capability declarations MUST NOT be interpreted as hard enforcement.

## Consequences

- Capability claims become honest and version-specific.
- A weaker host can still participate in the neutral contract without silently pretending to have stronger control.
- User-facing surfaces and tests must carry enforcement mode through the event/action path.
- Some workflows will need explicit user acknowledgment or later native support before they can be considered hard-enforced.
