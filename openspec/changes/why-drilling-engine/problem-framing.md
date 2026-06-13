# Problem Framing — why-drilling-engine

## Problem
Thin or authority-justified "whys" pass through the system unchallenged. The triggering case: in a live demo, the discovery gate's "what's the cost of not doing this?" was answered "it's a C-suite ask" and accepted. Separately, three *different* why-asking mechanisms already exist, scattered and duplicated, with no shared engine:
- an absent **premise-check** (no default-on "is the stated why real?" move),
- `mol-rapid` **diagnose** ("root cause, don't stop at the symptom") — a bounded drill,
- `/brainstorm` **Section 5** — a relentless branch-walking convergent interview, trapped inside that one skill.

## Why now
Surfaced by (a) the C-suite demo anecdote (authority accepted as a reason), and (b) this session's own false-premise failures that a probe would have caught (the "one CSV good, one bad" claim; the "mol-rapid is symmetric with mol-feature" assumption). The duplication was independently flagged by the `brainstorm-consolidation` review (`docs/analysis/brainstorm-consolidation-review.md`).

## Decision authority
none — solo project, user owns the what and why.

## Behavioral population
The **agent** (main loop + subagents), whose default behavior gains a thin-why probe; and the **user**, who experiences (and can dismiss) the probes. No external team.

## Riskiest assumption
That **ambient thin-why detection (Depth-1 Probe) helps more than it annoys** — i.e., the trigger can separate genuinely thin/unconfirmed whys from legitimate ones without over-firing on factual lookups. We will know we are wrong within ~1–2 weeks of real use if the Probe fires emptily on lookups or the user disables it. Liveness: the signal log (`.beads/.gate-signal.jsonl`) shows Probe firings + empty-fire rate.

## Success criteria
On the dogfood fixtures (below), Depth-1 flags the 3 should-trigger cases and stays silent on the 2 negative controls; and in real use the empty-fire rate stays low enough that the user keeps the Probe on rather than disabling it.
