# ADR-002: Supervisor Bridges Durable Lifecycle Actions

## Status

Accepted

## Context

Immediate tool decisions can run inline through native client hooks, but continuation, wakeups, and other durable lifecycle actions may outlive one client callback. Requiring every client to expose identical lifecycle primitives makes the capability model host-dependent. Making an always-on orchestrator own all agent execution would expand Escapement beyond its workflow-control boundary.

The supervisor must not become a second policy engine or infer events that a client never emitted.

## Decision

Use a shared lifecycle-bridge supervisor for neutral runtime-issued durable actions only. Native adapters submit normalized events and apply immediate decisions inline. When the runtime emits a pending action, the supervisor persists its request identity, state transition, provenance, and requested wakeup/resume operation, then invokes the registered adapter resume mechanism.

If an adapter cannot perform the requested operation mechanically, it MUST report an explicit advisory or unavailable result on the next supported client event. The supervisor MUST NOT re-evaluate policy, invent lifecycle evidence, or silently auto-allow a pending action.

## Consequences

- Ordinary Bash and file decisions do not pay a supervisor process cost.
- Continuation and wakeup semantics have one durable owner across clients.
- The supervisor needs a stable adapter registration and state-record contract.
- Clients without a resume primitive can expose advisory continuity rather than falsely claiming hard resumption.
- An always-on orchestrator remains out of scope, limiting automation but keeping the runtime boundary narrow.
