# Problem Framing — openspec-beads-staleness

## Problem
Specs in `openspec/changes/` become stale silently. Bug fixes, chores, and
day-to-day work change the code specs describe, but nothing detects drift or
prompts a spec update. Currently 4 of 50 open beads issues in cake have
`spec_id`, 0 of 7 bugs do. The `discovery-gate.py` hook also checks the wrong
directory (`docs/plans/` instead of `openspec/changes/`), further degrading the
existing forward-flow gate.

## Why Now
This repo IS the workflow tooling. The openspec/beads integration gap means every
project using this setup accumulates invisible spec debt — agents reading stale
specs make wrong assumptions, and there is no feedback loop to catch it. The
problem was concretely diagnosed in the cake repo in the session preceding this
discovery (2026-05-26).

## Decision Authority
Alexander Vyhmeister — personal workflow tooling.

## Behavioral Population
Claude Code agents working in repos that use both openspec and beads. They are the
actors that create bugs, close tasks, and maintain (or fail to maintain) spec
linkage.

## Riskiest Assumption
That we can reliably detect whether a beads issue touches a spec'd code area
deterministically — without requiring agents to self-declare linkage. If
spec-area detection is too noisy (false positives block unrelated work, false
negatives miss real drift), gates become friction without signal.

We will know this is true when: a test suite covering real cake issues correctly
classifies ≥ 90% of bugs as "in spec'd area" or "not in spec'd area" using only
the beads issue data and openspec directory contents — without reading source code
at gate time.

If false, we will: fall back to nudge-only (ask, not deny) for the reverse flow,
and focus the deterministic gate on the forward flow only.

## Success Criteria
The forward flow (discovery → spec → beads tasks with `spec_id`) and reverse flow
(close/create → spec linkage verified or explicit waiver) are both mechanically
enforced. A `bd close` on a bug with no `spec_id` in a known spec'd area either
produces an exit-2 block or requires an explicit exemption — not just a nudge.
Spec drift is detectable on demand via a `bd doctor`-style command.
