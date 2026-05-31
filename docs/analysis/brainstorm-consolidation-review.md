# Review: consolidating the brainstorm mechanisms (CSVs ↔ `/brainstorm` ↔ molecules)

**Date:** 2026-05-30
**Proposal reviewed (user's):** (A) pull the best methods out of the two CSVs into the `/brainstorm` skill; (B) optionally relocate the CSVs under the skill; (C) wire **both** `mol-feature` and `mol-rapid` to invoke `/brainstorm`.
**Method:** 4-agent review team (`brainstorm-consolidation`). The lean-critic delivered a complete verdict; architecture/integration facts verified directly against the files. (Provenance caveats at the end — two reviewers' finals did not surface cleanly as messages and were reconstructed from file-verified analysis.)

---

## Headline

**The proposal's riskiest part (wire `mol-rapid` → `/brainstorm`) should be cut outright; the `mol-feature` wiring hits a real architectural collision and needs redesign before it's safe; and the "extract methods" part is mostly redundant because the skill already has 9 lenses.** The user's actual goal — *less duplication* — is real and achievable, but the smallest correct change is much smaller than the proposal, and one piece (mol-rapid) moves in the wrong direction.

The duplication that exists is **two brainstorm mechanisms doing one job**: the `/brainstorm` skill (9 inline lenses + 6-field convergent interview) and the `mol-feature` brainstorm *step* (CSV-sampled, dispatches an agent team). Consolidation should collapse those two — not push brainstorming *down* into mol-rapid, where no brainstorm belongs.

---

## Per-part verdict

| Part | Verdict | Why |
|---|---|---|
| **A — extract best CSV methods into `/brainstorm`** | **Conditional — dedup required; possibly skip** | The skill *already* has 9 lenses (Section 4) covering First Principles (lens 3), Failure-mode (5), **Inversion (6)**, Competitor (7), Simplification (8), Adjacent-domain (9), User (1). So this is **merging onto a non-empty set, not populating an empty slot** — and several CSV "good methods" *duplicate* existing lenses (Assumption Reversal ≈ Inversion; First Principles = lens 3). After dedup, the cleanest genuinely-additive inline methods are **Pre-mortem** and **Five Whys** (SCAMPER / Six Hats as structured aids). lean-critic argues even those don't clear the cost (they only *name* moves the base model already does — see the prior elicitation doc's "names, doesn't add" bound), so the floor is **possibly zero**. Wholesale copy of the 110-item catalog = choice-overload bloat. |
| **B — relocate CSVs under the skill** | **Cosmetic-only — skip unless bundled with C** | The CSVs aren't sourced as a library — they're a *prompt-embedded path string* with **exactly two edit sites** (repo formula + the deployed twin under `~/.beads/formulas/`) and no other consumers. Relocating dangles the reference unless both are updated atomically, and even then changes no behavior. |
| **C — wire `mol-feature` → `/brainstorm`** | **Reframe; do NOT do naively** | Two/three real defects (below): double-discovery (which also **bypasses the human `review-discovery` gate**), double convergent-interview, and fan-out loss. Defensible *only* with redesign that picks a single owner of the brainstorm→discovery transition. |
| **C — wire `mol-rapid` → `/brainstorm`** | **CUT. Refuse to ship.** | **Broken at the input contract** (lead reason): mol-rapid's vars are `[title, acceptance]` — no `{name}`; `/brainstorm` *requires* a kebab `{name}` and writes `openspec/changes/{name}/problem-framing.md`. mol-rapid literally cannot supply what the skill consumes. Compounding: `/brainstorm`'s Section 1 gate **self-terminates** on trivial work, so either branch refutes the wiring (trivial → skill no-ops; survives Section 1 → it was never rapid, belonged in mol-feature). And it contradicts the repo's *own* prior verdict (`elicitation-in-conversational-sessions.md`: divergent methods "belong gated behind mol-feature… concede nothing"). The narrow version already exists: mol-rapid's `diagnose` step escalates to mol-feature. |

---

## The two blockers on the `mol-feature` wiring (verified)

1. **Double-discovery / double-interview collision (highest severity).** `/brainstorm` Section 6 *terminally routes into `/discovery`* (it calls `Skill(skill="discovery", ...)`) and Section 5 runs a 6-field convergent interview. But `mol-feature` **already has its own `discovery` step (step 2)** right after brainstorm. So wiring the brainstorm step to `/brainstorm` makes discovery run twice — and critically, the **skill-internal discovery run is invisible to the molecule's step-graph, so it escapes the human `review-discovery` gate entirely** (the molecule's gate sits after the *second*, molecule-owned run). Two control planes — the molecule step-graph and the skill's internal `Skill()` routing — with zero awareness of each other. *(Verified: SKILL.md §6 lines 199–207 invoke discovery; `mol-feature.formula.json` has a sibling discovery step + a review-discovery gate.)* **Must-fix:** pick ONE owner of the brainstorm→discovery transition — either the molecule owns it (the step borrows only `/brainstorm` Sections 1–5 challenge/framing and does NOT trigger its terminal routing), or the skill owns it (collapse mol-feature's two steps into one, accepting the loss of the separate gate). You cannot have both — having both *is* the bug.

2. **Fan-out loss** *(confirmed by architecture-reviewer)*. The `mol-feature` brainstorm step dispatches a **team of isolated agents** (`TeamCreate`) — real sampling topology, the *only* substrate the prior elicitation panel found delivers lift. The `/brainstorm` skill is **single-agent conversational** (232 lines, zero `TeamCreate`), and is *also* invoked standalone and from the build skill. Naively replacing the step with a skill call **silently drops the fan-out**. The architecture-reviewer rejected both "accept the loss" and "give the skill an optional fan-out mode" (a skill that sometimes spawns a team is a worse abstraction). **Decision (option c): the unit of consolidation is the METHOD CONTENT, not the EXECUTION MECHANISM.** Extract the skill's Sections 1–4 (gate + lenses + adversarial probe + the additive methods) into a **shared method block**; both call sites reference it but keep their own topology (skill = single-agent conversational; step = fan-out team) and their own terminal behavior. The mol-feature step borrows Sections 1–4 only and **must not** trigger the skill's Sections 5–6 (convergent interview + terminal `/discovery` routing) — which is *also* the fix for defect #1 (the molecule owns discovery via its own step + gate). One change resolves both defects.

---

## Recommendation

**Build the small win; cut the harmful part; gate the risky part behind a real design task.**

1. **Part A, minimal:** add **Pre-mortem, Assumption Reversal, Five Whys** to `/brainstorm` (as additional lenses/methods in Section 4, or a small referenced "deep methods" list). Skip the rest of the catalog — the 9 lenses already cover it. Ban the decorative `theatrical`/`quantum`/`wild` rows from ever being surfaced inline (prior-panel finding).
2. **Part C / mol-rapid: do not do it.** Leave mol-rapid lean; its diagnose-step escalation already handles the "this is bigger than a chore" case.
3. **Part C / mol-feature: file a scoped design bead, don't wire blind.** Acceptance criteria must include: (a) no double-discovery — `/brainstorm` invoked in a non-routing mode inside the molecule; (b) fan-out preserved (step keeps `TeamCreate`, or the loss is a conscious decision); (c) no double convergent-interview against the downstream discovery step.
4. **Part B: bundle only with #3** (move CSVs + fix the hardcoded path atomically), else skip.

**Net:** the user's instinct ("consolidate the duplicated brainstorm logic") is right, but — per architecture-reviewer — the unit of consolidation is the **shared method content, NOT one merged execution path.** Read "consolidate" as "one code path" and you get a regression (you'd destroy the two legitimately-different topologies). The buildable win is **a shared method block + two thin call sites** (single-agent skill; fan-out step that suppresses Sections 5–6), **not** a merged orchestrator — and **not** an expansion of brainstorming into mol-rapid. Everything else is a no or a designed change behind acceptance criteria.

---

## Provenance
- **lean-critic (full final delivered):** the per-part verdicts, the "cut mol-rapid / refuse to ship" call, the "consolidate the two mechanisms not expand into rapid" framing, the Section-1 self-termination argument, the bureaucracy failure-mode labels. Also self-corrected one claim (had called `brainstorming-methods.csv` uniformly decorative; withdrew it — the boundary is within-file).
- **integration-verifier (full final delivered):** the input-contract break on mol-rapid (no `{name}`), the double-discovery control-plane collision + gate bypass, the two-edit-site path-coupling for Part B, and the per-part outcome tests (incl. the negative control that the *old* CSV path must stop resolving after a move). Also self-corrected: initially claimed the skill "names zero methods" → retracted after lean-critic cited Section 4's 9 lenses with line numbers; Part A revised from "additive" to "conditional, dedup-required."
- **architecture-reviewer (full final delivered, late):** confirmed the fan-out loss and settled it with option (c) — *consolidate the method content, not the mechanism*: a shared method block referenced by both the single-agent skill and the fan-out step, with the step suppressing Sections 5–6 (which also fixes the double-discovery defect). Provided the concrete migration design (shared `methods.md`, Section-4 reference, formula-step rewrite to challenge/framing-only + path fix, atomic reinstall with old-path negative control, mol-rapid unchanged). Biggest risk named: reading "consolidate" as "one code path" → regression. *(This corrected the earlier synthesizer framing, which had said "merge the two mechanisms"; the doc above now reflects the method-content-not-mechanism framing.)*
- **method-curator (final did not surface):** the extraction-list facet is covered by lean-critic + integration-verifier's dedup analysis and the synthesizer's file check, not by a method-curator report. [marked: that one facet is team-adjacent reconstruction]

> **Note on review quality:** this team did *not* rubber-stamp. integration-verifier made a factual error ("empty skill"), lean-critic caught it with line numbers, and integration-verifier retracted and revised its Part A verdict. That correction cycle is why Part A moved from "GO/additive" to "conditional/dedup-required" — a verdict neither reviewer held alone at the start.
