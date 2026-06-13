# Tasks — why-drilling-engine walking skeleton

Walking skeleton ONLY. The engine/skill abstraction and Depth-2/Depth-3 wiring are explicitly NOT included; they are follow-ups gated on Depth-1 (the ambient Probe) proving useful in real use.

## 1. Depth-1 Probe as a thin always-on rule
- [ ] 1.1 `claude/rules/why-drilling.md` — trigger (load-bearing why that is thin / authority-shaped / user-asserted-and-unconfirmed) + one-question Probe + the stop-rule (confirmed observable outcome OR explicitly-flagged unconfirmed inference with a named confirmer). Keep it lean (~trigger + pointer), non-blocking by default.
- [ ] 1.2 First-class escape: a one-word out ("just answer" / "skip") that suppresses the Probe; captured as a waiver in the signal log.

## 2. Signal
- [ ] 2.1 Wire `_gate_signal.record()` for each Probe firing: {fired, caught-real-thin-why | empty-fire, the why excerpt, escape-used}. Target: `.beads/.gate-signal.jsonl`.

## 3. Dogfood fixtures (the oracle)
- [ ] 3.1 should-trigger fixtures: C-suite "it's a mandate"; "one CSV good, one bad" false premise; "mol-rapid symmetric with mol-feature" assumption. Probe must flag all three.
- [ ] 3.2 negative controls: "why is bd grey", "where is this CSV used". Probe must stay silent (or resolve in one shot without interrogation).

## 4. Observe
- [ ] 4.1 Use in real work 1–2 weeks; populate the signal log. Kill condition: high empty-fire rate on lookups OR user disables the Probe → do not ship Depth-1; keep only opt-in deeper tiers.

## Follow-ups (NOT in skeleton — gated on §4 outcome)
- Extract engine to `claude/skills/why-drill/SKILL.md` once ≥2 consumers proven.
- Depth-2 (Drill) into `mol-rapid` diagnose.
- Depth-3 (Grill) = refactor `/brainstorm` Section 5 to invoke the engine (absorbs the brainstorm-consolidation overlap).
- Distribution as an installable package (deferred; versioning concern only).
