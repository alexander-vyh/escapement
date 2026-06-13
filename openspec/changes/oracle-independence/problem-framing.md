# Problem Framing: oracle-independence

## Problem
Every quality signal in an agent workflow is *self-authored* by the implementing
agent — its own test, its own `verify` command, its own oracle. QA discipline
(independence, test-first, discriminating oracles) is therefore unenforceable, and
verification gaps reach `main`. Concretely: the "cake" incident merged 4 verbatim
seam-extraction refactor PRs whose self-authored characterization tests could not
have caught a transcription error in the moved code; the risk was caught by a human,
not the system.

## Why now
The cake incident just occurred, on a production compaction path, and was caught by
a human review rather than by any gate. It exposed that the workflow cannot enforce
its own stated QA discipline — the gates check artifact *presence* and *shape*, never
oracle *independence* or *order*.

## Decision authority
The user (solo owner of this workflow repo). Owns the *what* and *why*.

## Behavioral population
AI agents performing implementation work in repos that use this workflow — they are
the ones who must route work into a molecule at the start and submit it to a landing
check. Plus the user, acting as the human design-gate boundary that supplies
content-independence. (Aligned with the problem subject: the agents whose oracles are
self-authored are exactly the population that must change.)

## Riskiest Assumption
**Betting that the human design gate produces genuine independence** — it catches what
the agent's self-framing of a diff hides — *at least when handed an independent
reference* (the prior behavior / the spec), rather than rubber-stamping on the agent's
presentation. **Wrong when** a reviewer at the gate misses a planted refactor-
transcription error even with an independent reference available. **Knowable within
~2 weeks** via a blinded probe: slip a planted-bug refactor among real diffs at the
gate and measure catch-rate with vs. without an independent reference.

Why this outranks classifiability: if the human gate rubber-stamps, escape-(b) (the
out-of-session boundary) does not exist, and the entire "route to a human boundary"
half of the architecture collapses to escape-(a) (self-validating oracles) only —
leaving non-verbatim refactors and behavior-change-without-a-cheap-discriminating-test
as permanent human residue. Routing (Risk A) only decides auto-vs-manual; the human
gate decides whether the destination is real.

**Second-order assumption (tested only if the first survives):** work-type can be
classified from the opening description reliably enough to AUTO-route without the
false-positive death that killed the blocking-gate idea (measured this session from
`.beads/.gate-signal.jsonl`: tdd-gate fires `ask` ~74% — 461 `ask` / 164 `allow`;
`validate_no_shirking` is ~95% evaded — 766 `deny` / 39 `waiver`).

## Success criteria
1. A planted verbatim-refactor transcription error (copy-not-move / `>`→`>=` /
   wrong-arity) is blocked at landing, mechanically, before merge.
2. When work reaches the human design gate, an independent reference is present and the
   reviewer catches a planted error they would miss from the agent's framing alone.
3. Non-trivial work described at session start is routed into a molecule (reaching the
   gate) without the agent having to remember to.
4. Any new gate's interrupt / false-positive rate stays materially below the dismissal
   threshold the existing gates breach (tdd-gate ~74% `ask`).
5. No new self-attested "QA happened" green signal is introduced (no confidence-
   inflating records).
