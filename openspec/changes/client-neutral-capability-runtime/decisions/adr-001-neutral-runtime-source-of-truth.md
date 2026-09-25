# ADR-001: Neutral Runtime Owns Capability Semantics

## Status

Accepted

## Context

Escapement currently shares policy code across host surfaces, but Codex and Claude-oriented paths still act as practical sources of truth. Pi derives part of its behavior from that host-specific inventory. This makes source ownership, lifecycle assumptions, and enforcement claims drift even when helper code is reused.

The repository has no prior public release, so preserving host-owned paths would create compatibility obligations without protecting an external contract. The chosen clients are Pi, Codex, and Claude; each exposes different lifecycle events and action APIs.

## Decision

Move capability semantics, neutral event/action types, state transitions, and outcome/oracle behavior into a host-neutral runtime under the existing Escapement harness boundary. Client integrations may decode native events, attach provenance, and apply native decisions, but they MUST NOT define neutral authority or policy.

Generated instructions, package metadata, hook launchers, and capability inventories project from the neutral source. No client is the source host for a neutral capability.

## Consequences

- Capability changes have one policy owner and can be tested independently of client hook names.
- Pi, Codex, and Claude adapters become smaller and replaceable.
- The migration must move existing imports and remove host-owned aliases rather than preserving a dual-source period.
- Some current host files will become wrappers or move, increasing short-term migration work.
- A client may still have hard, advisory, or unavailable realization; that status is part of the adapter contract rather than a semantic fork.
