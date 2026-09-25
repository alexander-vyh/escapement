# ADR-004: Migrate to One Source Without Compatibility Aliases

## Status

Accepted

## Context

Escapement has no prior public release, but it has many internal and generated host paths. A staged dual-source migration would appear safer while preserving the exact authority ambiguity this change is intended to remove. Compatibility aliases would make it possible for a caller or installer to keep invoking the old policy owner indefinitely.

Rollback must remain possible without making both old and new implementations active at once.

## Decision

Perform a clean cutover after the walking skeleton proves the neutral contract. Migrate all affected callers and generated surfaces, remove obsolete host-owned policy paths and source-host fields, and use repository-level revert plus package refresh as rollback. Do not retain deprecated aliases, dual writes, or host-specific fallbacks that can make independent policy decisions.

## Consequences

- The first migration commit has a larger coordinated boundary.
- Import-resolution, renderer, install, and behavioral checks become mandatory before landing.
- Rollback is simple and unambiguous at the commit/deployment boundary.
- Local consumers of uncommitted host paths may need to update immediately; this is acceptable because no public release contract exists.
