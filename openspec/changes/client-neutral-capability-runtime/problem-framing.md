# Problem Framing

## Problem

Escapement's policy and lifecycle authority is still distributed across Claude- and Codex-oriented surfaces. Shared helpers do not provide a client-neutral contract, and Pi, Codex, and Claude can therefore drift in semantics, lifecycle behavior, and enforcement claims.

## Why now

Escapement is before its first public release. Continuing with host-centric ownership now would freeze the wrong architecture and create compatibility obligations around internal paths that are not yet a public contract.

## Decision authority

The repository owner and maintainers decide the neutral capability contract, migration boundary, and release scope.

## Behavioral population

Maintainers implement and verify the neutral runtime and its adapters. Users of Pi, Codex, and Claude should receive the same capability semantics, with client-specific enforcement strength reported explicitly.

## Riskiest assumption and liveness

The hardest lifecycle outcome, including continuation or wakeup, can be represented as neutral events, durable state, and decisions, then realized through thin Pi, Codex, and Claude adapters or the lifecycle bridge. The assumption must be falsifiable within roughly two weeks by a walking skeleton exercised across all three clients.

## Success criteria

Behavioral equivalence is the primary oracle: controlled Pi, Codex, and Claude fixtures produce the same neutral outcome and equivalent user-visible result for the walking-skeleton capability. Structure is also mandatory: neutral runtime sources own semantics, adapters are thin, and every client/capability pair declares hard, advisory, or unavailable enforcement rather than silently overstating support.
