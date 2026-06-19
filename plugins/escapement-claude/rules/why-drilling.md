# Why-Drilling — Depth-1 Probe (always-on)

When a **load-bearing why is thin**, drill it once before acting. A *why* is
load-bearing if a decision, design, or recommendation rests on it. It is **thin**
when it is (a) **authority-shaped** ("X asked for it", "it's a mandate",
"leadership wants it"), (b) **a premise the user asserted that no artifact has
confirmed**, or (c) **a reason that restates the request** instead of naming an
observable outcome.

## The Probe — one question, non-blocking

On a thin load-bearing why, run ONE inline check before proceeding:

> "Is the stated reason the real, observable outcome — or an unconfirmed inference?"

Bottom out at one of two terminals, then continue:

- **Confirmed observable outcome** — the why resolves to something checkable (a
  metric, a failing test, a reproduced symptom, a stated success criterion). Proceed.
- **Unconfirmed inference** — the why rests on a guess or a proxy (e.g. someone
  invoking an absent authority). **Mark it unconfirmed, name who/what would confirm
  it, and proceed — do not block.** Interactive: you may ask. Non-interactive:
  record the assumption and continue.

This is a **floor, not a ceiling.** One pass catches the *obvious* false premise.
Non-obvious framing errors need the deeper tiers (Drill = root-cause / Grill = full
interview) — opt-in and gated behind real agent fan-out, NOT this probe.

## This is not new ceremony

The Probe is turn-1 enforcement of two rules already in force:
- **never-suppress** — treating a user-asserted premise as verified is an oracle downgrade.
- **evidence-provenance** — answering as if an unconfirmed premise were established
  is asserting an inference as fact.

## Escape

A one-word user out — "just answer" / "skip" — suppresses the Probe for that turn.

## Signal (walking-skeleton form — compliance-based)

When you fire a Probe, append one record via `claude/hooks/_gate_signal.py`
`record(...)`: gate `why-drilling`, decision `probe-fired` | `probe-empty` |
`escape-used`, with the why excerpt. This is rule-based (not a hook), so it relies
on compliance; the **observe phase** (`claude-workflow-setup-7ki`) tests whether the
empty-fire rate stays low enough to keep the Probe on. If it fires emptily on plain
lookups or the user disables it → Depth-1 does not ship.

## Dogfood fixtures (the oracle for the observe phase)

- **Should-trigger:** "it's a C-suite ask / mandate" (authority); "one CSV is good,
  the other isn't" (unconfirmed premise); "mol-rapid is symmetric with mol-feature"
  (unverified assumption).
- **Should-NOT-trigger** (negative controls — single-answer lookups): "why is bd
  grey?"; "where is this CSV used?".

## Status

Depth-1 of the why-drilling engine (epic `claude-workflow-setup-a2n`). Depth-2
(Drill / root-cause) and Depth-3 (Grill / full interview) are follow-ups, gated
behind real multi-agent dispatch. Engine extraction deferred until Depth-1 proves
useful in the observe phase.
