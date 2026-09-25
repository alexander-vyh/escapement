<!-- Spec: lifecycle-bridge-supervisor -->

## Purpose

Provide durable continuity for runtime-issued lifecycle actions without becoming a policy engine or launching a supervisor for every ordinary tool call.

## ADDED Requirements

### Requirement: Persist runtime-issued pending actions

The supervisor MUST persist a pending lifecycle action with request identity, state transition, client provenance, requested wakeup/resume operation, and correlation identity before attempting resumption.

#### Scenario: Runtime requests continuation

- **WHEN** the neutral runtime emits a continuation or wakeup action after a normalized lifecycle event
- **THEN** the supervisor persists one durable pending action that can be rehydrated after the original callback exits

#### Scenario: Ordinary tool decision does not require supervision

- **WHEN** the runtime returns an immediate Bash or file decision with no durable lifecycle action
- **THEN** the adapter applies it inline without starting a supervisor process for that event

### Requirement: Resume only through registered adapters

The supervisor MUST invoke the registered adapter resume mechanism for a pending action and MUST NOT re-evaluate policy, invent missing lifecycle evidence, or silently auto-allow the action.

#### Scenario: Adapter can resume natively

- **WHEN** a pending action reaches its requested wakeup and the registered client exposes a proven resume mechanism
- **THEN** the supervisor invokes that adapter mechanism and records the resulting native evidence against the request identity

#### Scenario: Adapter cannot resume mechanically

- **WHEN** a pending action reaches its wakeup but the client has no proven resume mechanism
- **THEN** the supervisor records explicit advisory or unavailable status and leaves the action visible for the next supported client event
