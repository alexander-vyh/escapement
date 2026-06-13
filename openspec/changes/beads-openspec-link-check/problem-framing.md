# Problem Framing — beads-openspec-link-check

> Confirmed framing for the discovery Input Gate. Authored 2026-06-13 alongside the
> redraft that encodes the four-lens advisor roundtable verdict.

## Problem

During review and handoff of an OpenSpec change, there is no fast, honest answer to
whether the *links between the three authorities are correct*: does each Bead's
`spec_id` actually resolve to a live OpenSpec anchor, or does it merely look linked?
Beads can report task state and `bd list --spec` already answers "which Beads, what
state, what is blocked" — but Beads structurally cannot tell that a `spec_id` points
at a renamed or deleted anchor (it has no knowledge of OpenSpec anchors), nor that a
Bead is "linked" only because its description mentions a path. A link that lies
produces false-green coverage that is strictly worse than missing coverage, because
it masquerades as success. Today that defect is invisible until a human notices it.

## Why Now

Escapement's OpenSpec→Beads flow is mature enough that changes routinely carry
`spec_id`-linked Beads across multiple sessions and handoffs. As link volume grows,
the probability of a stale/renamed anchor surviving review grows with it, and the
cost of catching it manually (cross-referencing `bd` output against the live spec by
hand) grows too. The read-side integrity check is the missing surface; the forward
path (OpenSpec → `/work-breakdown` → Beads) is already built.

## Decision Authority

The user (repo owner) is the decision authority for what ships. The four-lens
advisor roundtable (2026-06-13) is advisory: it produced the verdict that the
original committed-artifact design was mock bureaucracy by construction and that the
load-bearing core is an ephemeral integrity check. The user directed this redraft
and a second review. No external mandate is involved.

## Behavioral Population

The actors whose behavior this must serve, in priority order:
1. **A human reviewer/handoff recipient** reading a change's status — must see
   integrity violations surfaced, not buried. This is the population whose
   *trust behavior* (will they read this instead of running `bd`?) is the riskiest
   bet (below).
2. **An agent or CI step** that may invoke the check at a phase boundary — must get
   a fail-closed exit code on integrity violations and a clean exit on
   work-not-yet-done.
3. **The plan's author**, who must be able to read *why* the surface was cut.

## Riskiest Assumption

That a generated status surface gets **read and trusted during review/handoff often
enough to be worth maintaining** — instead of the reviewer just running
`bd list --spec`. This is an adoption/usefulness bet, not a technical one. The
technical work (serializing Beads state, resolving anchors) is trivial; the project
dies if the surface is built and nobody reads it. The walking skeleton must test
*this* assumption cheaply (one small command on one live change), not front-load
schema/renderer machinery whose value is contingent on the bet paying off.

## Success Criteria

- Running the command on a change with a renamed/deleted `spec_id` anchor exits
  non-zero and names the offending Bead and unresolved anchor; fixing the link makes
  it exit zero. (The integrity oracle works.)
- A Bead that only *mentions* an OpenSpec path in its description is not counted as
  linked. (No grep-as-link.)
- Blocked work and missing coverage are reported but never change the exit code.
  (Fail-closed on lies, not on progress.)
- The command writes no committed artifact and mutates no OpenSpec or Beads state.
- Observed adoption: a reviewer uses the command unprompted on a real change at
  least twice. (The riskiest assumption is validated before any further surface is
  built.)
