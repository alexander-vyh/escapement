<!-- Spec: client-adapter-runtime -->

## Purpose

Keep Pi, Codex, and Claude integrations thin. Adapters decode native payloads, attach provenance, invoke the neutral runtime, and apply supported decisions; they do not define Escapement policy.

## ADDED Requirements

### Requirement: Adapters do not own neutral policy

A client adapter MUST translate native events and render runtime decisions without inventing authority, changing neutral state transitions, or maintaining a second policy implementation.

#### Scenario: Adapter handles an equivalent native event

- **WHEN** an adapter receives a native event representing a capability already defined by the neutral registry
- **THEN** it submits the normalized event to the runtime and applies the returned decision without adding client-specific policy

#### Scenario: Adapter contains a host-only policy branch

- **WHEN** adapter validation detects a decision path that bypasses the neutral runtime for a registered capability
- **THEN** validation fails and the adapter is not ready for that capability

### Requirement: Immediate decisions are applied inline

Adapters MUST apply hard or advisory immediate decisions in the native client callback when the installed client exposes the required point of effect. They MUST preserve the runtime correlation identity in the resulting status or event.

#### Scenario: Hard decision reaches the client point of effect

- **WHEN** a supported adapter receives a hard deny or ask decision during a native tool callback
- **THEN** the native client blocks or prompts at that callback and the result is correlated to the neutral decision

#### Scenario: Client cannot enforce the decision mechanically

- **WHEN** the runtime returns a decision but the adapter lacks the installed client primitive needed for hard enforcement
- **THEN** the adapter reports explicit advisory or unavailable realization and does not claim hard enforcement
