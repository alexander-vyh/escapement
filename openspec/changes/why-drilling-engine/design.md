# why-drilling-engine — design

## Problem Statement
The system has three scattered, duplicated "why-asking" mechanisms and no shared engine, and it accepts thin/authority-justified whys (C-suite demo anecdote). We want **one drilling engine, three invocation depths**, so the same primitive serves the cheap ambient case and the deep interview — a consolidation (net deletion of duplicated prose), not a new feature bolted on.

## Non-Goals
- NOT an ambient relentless interrogator. Relentlessness is gated to the opt-in deep tier; the always-on tier is shallow by construction (one question).
- NOT a code/executable package (yet). The engine is a prompt procedure an LLM follows. A future `bun`/`npx skills`-style distribution is explicitly deferred (see Future Increments) and does not change the runtime.
- NOT a replacement for `/discovery`. The engine drills *whys*; discovery designs *solutions*.

## Capabilities
### New Capabilities
- **One why-drilling engine** (the grill-me primitive + a provenance stop-rule), exposed at three depths:
  - **Probe** (depth 1) — one why, **one question**; default-on, anywhere; the premise-check.
  - **Drill** (depth 2) — one why, **one branch to root** (Five-Whys-shaped); `mol-rapid` diagnose, opt-in `/why`.
  - **Grill** (depth 3) — **all** whys, **every branch** to shared understanding; opt-in `/grill`, `/brainstorm` Section 5, `mol-feature` brainstorm.
- **Shared engine invariants:** one question at a time; each carries a recommended answer ("I'd assume X because Y — correct?"); verify-don't-ask (explore code/docs first); **terminate when the why bottoms out in a confirmed observable outcome OR an explicitly-flagged unconfirmed inference with a named confirmer**; hard termination guard (max-N whys / diminishing-returns) so drilling cannot stall.
- **Non-blocking by default:** in non-interactive runs the Probe surfaces + marks + proceeds (no stall); escalates to blocking only when interactive.

### Modified Capabilities
- `/brainstorm` **Section 5** → becomes an invocation of the engine at **Grill** depth (removes the duplicated interview prose).
- `mol-rapid` **diagnose** → invokes the engine at **Drill** depth for root-cause (formalizes what it already asks for).

## Impact
- New: `claude/skills/why-drill/SKILL.md` (engine body); `claude/rules/why-drilling.md` (thin Depth-1 trigger + pointer); later `claude/commands/why.md`, `claude/commands/grill.md`.
- Modified (follow-ups): `/brainstorm` SKILL.md Section 5; `mol-feature`/`mol-rapid` formula step prompts.
- Signal: Probe firings recorded to `.beads/.gate-signal.jsonl` via `_gate_signal.record()`.

## Riskiest Assumption
Ambient Depth-1 detection helps more than it annoys (the trigger separates real thin whys from legitimate ones). The walking skeleton tests **this**, not "the Probe works."

## Walking Skeleton (shrunk per the self-review — YAGNI on the engine abstraction)
Do NOT build the engine/skill abstraction yet. The minimum that tests the riskiest assumption:
1. **Depth-1 Probe as a thin always-on rule** (`claude/rules/why-drilling.md`) — trigger + one-question probe + the confirmed-outcome-or-flagged-inference stop-rule, non-blocking, with a one-word **escape** ("just answer").
2. **Signal**: record each Probe firing + empty-vs-caught to `.beads/.gate-signal.jsonl`.
3. **Dogfood fixtures** as the oracle:
   - should-trigger: C-suite "it's a mandate"; the "one CSV good, one bad" false premise; the "mol-rapid symmetric with mol-feature" assumption.
   - should-NOT-trigger (negative controls): "why is bd grey", "where is this CSV used" (factual lookups).
Engine extraction to a skill + Depth-2/Depth-3 wiring are **follow-ups, gated on Depth-1 proving useful.**

## Proof of Delivery
- Fixtures: Depth-1 flags the 3 should-trigger cases, stays silent on the 2 negative controls.
- Real use (1–2 weeks): empty-fire rate low; user has not disabled the Probe; signal log populated.

## Anti-Metrics (kill conditions)
- High empty-fire rate on factual lookups, or user disables the Probe → **do not ship Depth-1**; keep only opt-in Depth-2/3.
- Probe blocks a non-interactive run → bug, must be non-blocking.

## Decisions
- **Home:** engine body in a **skill**; default-on tier is a **thin rule trigger + pointer** (cheap-always-on vs heavy-on-demand). This split also makes future packaging clean (engine is one self-contained dir).
- **Authoring vs deploy:** canonical source in the repo (`claude/...`); `INSTALL.sh` deploys to `~/.claude/`. Edits land in the repo.
- **Replaces vs sits-beside (anti-duplication map):** Section 5 → *replaced* by Grill. mol-rapid diagnose → *uses* Drill. `/brainstorm` Section 1 "should this be done" gate and `/discovery` → **left alone** (they are decision-gates, not why-drills) — decided explicitly to avoid creating a fourth overlapping why-asker.
- **Three depths, one engine** parameterized by breadth (one why / one branch / all branches) and stopping rule.

## Risks & Trade-offs
- **Trigger precision is the whole risk** (no turn-1 classifier exists in the repo — prior elicitation panel finding). Mitigated by making trigger-precision the skeleton's measured success criterion + dogfood fixtures.
- **Bloat risk** if the ambient tier becomes relentless. Mitigated by Depth-1 being one-question-by-construction; relentlessness gated to opt-in Grill.
- **Coercion risk.** Mitigated by first-class escape + non-blocking default + signal (gate-design Rules 1–2).

## Future Increments
- Extract engine to `claude/skills/why-drill/` once ≥2 consumers are proven.
- Depth-2 into `mol-rapid` diagnose; Depth-3 refactor of `/brainstorm` Section 5 (this absorbs the `brainstorm-consolidation` Part-A/Depth-3 overlap).
- Distribution as an installable package (`npx skills`-style) — versioning/update concern only, not runtime.

## Prior Art
- `grill-me` (mattpocock/skills) — the relentless one-question-at-a-time interview primitive; Depth-3 ≈ this, generalized. `/brainstorm` Section 5 is already a richer implementation.
- Five Whys / laddering / working-backwards — the Drill-depth root-cause patterns.
- Repo lineage: `evidence-provenance` (inference-as-fact), `never-suppress` (don't downgrade the oracle — a user-asserted premise treated as verified IS a downgrade), `delicate-art-of-bureaucracy` (escape + signal + lean).
