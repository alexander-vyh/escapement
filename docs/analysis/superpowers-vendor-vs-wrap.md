# Superpowers: vendor (copy out) vs keep-wrapping?

**Date:** 2026-05-30
**Question (user's):** "As good as superpowers is, I may be best off copying out the relevant things and not relying on it — the overhead of wrapping it + the conflicts are just too much." Decide: **vendor** (copy the needed superpowers content into the repo, drop the dependency) vs **keep-and-override** vs **hybrid**.
**Method:** 5-agent decision panel (`superpowers-strategy`) with assigned position biases. 3 finals delivered at synthesis time (rules-coherence-advocate, dependency-strategist, upstream-value-skeptic); 2 referees pending (maintenance-cost-analyst, migration-architect) — folded in on arrival.

---

## Verdict: KEEP-AND-OVERRIDE now. Vendor only if/when the packaging goal goes near-term.

The panel reduced a big strategic question to **one fact the user already supplied**: is the self-contained / npx-installable packaging goal real and near-term? The user said earlier this session **"that's a question for later."** By the panel's own logic, that tips the call to keep-and-override now — because **0 of the 4 conflicts require owning the code**; only the (deferred) packaging goal would.

### Why the conflicts don't justify vendoring
All three delivered reviewers converged: none of the four rule-conflicts needs vendoring — they are half-applied overrides + one deletion:

| Conflict | Disposition | Cost |
|---|---|---|
| **#1 worktrees** | **DELETE** the `superpowers:using-git-worktrees` requirement (`beads-execution:818`) + the 28-line band-aid (`:46-73`); point at the repo's `bd worktree create` rule. *(Upstream even defers: its Step 1a is "Native Worktree Tools (preferred)" + Step 0 "explicit user preference wins" — `bd worktree create` IS that native tool.)* | removal, ~0 |
| **#2 named agents** | **already fixed & shipping** — `dispatching-parallel-agents` forces TeamCreate + named. The proof the override pattern works. | none |
| **#3 writing-plans → off-OpenSpec** | **finish the half-done override** — `brainstorming:43` says "do NOT invoke writing-plans" but `:230` still calls `Skill(superpowers:writing-plans)`. Reconcile prose vs code; route to `openspec/changes/`. | 1 edit |
| **#4 finishing → merge-to-main** | **constrain the option set** — `beads-execution:728` calls it raw; default to PR-only. | 1 directive |

### The genuinely-real wrap-pain — now confirmed a LIVE CORRECTNESS BUG (verified independently by 2 reviewers against the upstream file)
Upstream v5.1.0 brainstorming is now a **9-step** checklist: 1 explore / **2 offer-visual-companion (inserted)** / 3 clarify / **4 propose-approaches** / 5 present-design / 6 write-doc / 7 spec-review / 8 user-review / **9 transition-to-writing-plans**. The inserted step 2 shifted everything down. The wrapper still cites OLD numbers, and the drift is **not benign**:
- `brainstorming:41` "SKIP superpowers steps **4-6**" — but step 4 is now **propose-approaches**, the step the wrapper means to *keep*. So the instruction now tells the agent to skip the wrong step.
- The transition-to-writing-plans the wrapper means to suppress moved to **step 9** — *outside* the "4-6" skip range. So `brainstorming:43`'s "do NOT invoke writing-plans automatically" is **silently INERT** — the suppression no longer lands.
- `brainstorming:68` "(superpowers step 3)" for propose-approaches → now step 4.

This is **one root defect, not two** — the `:43` prose-vs-`:230` code contradiction I flagged earlier is *caused by* the skip-range drifting off the transition step. **Fix = de-number to semantic anchors** ("after the flow proposes approaches, before it presents the design / before it transitions to writing-plans"), which the wrapper already does elsewhere — *not* vendoring (a frozen copy stops the drift but freezes bugfixes, and a manual re-sync reintroduces the same bug class). De-number + pin is strictly more drift-robust than a fork.

---

## Converged decision rule (all 3 delivered reviewers agree)

The panel **converged** — including the dependency-strategist walking back from "vendor unconditionally." A **fourth option, PIN, emerged and dominates vendoring on every axis except packaging.** The single decision rule:

> **PIN vs VENDOR, decided by one question: is "self-contained / bun-or-npx-installable" a real, near-term goal?**
> - **NO / hypothetical →** PIN `superpowers@5.1.0` + the cheap override/delete fixes. **Don't vendor.**
> - **YES →** sever the **single live edge** — the only path to **zero external edges** (self-containment is a property of the dependency graph; *you cannot pin your way to zero edges*).

**Crucial measured correction (the vendor cost is far smaller than "6 skills"):** a grep for live `Skill(skill="superpowers:*")` calls found the *entire executed* dependency surface is **ONE edge** — `brainstorming/SKILL.md:230 → superpowers:writing-plans` (~152 lines). Everything else is **already-owned**: `dispatching-parallel-agents` (304 lines) invokes upstream *nowhere* and reimplements it; `beads-execution`'s superpowers mentions are all dot-graph nodes / Related-Skills bullets, never `Skill()` calls; brainstorming "steps 1-3" is inline prose (the content is restated — explore/clarify/propose — only the *step numbers* couple). So vendoring "the 6 skills" would mostly **copy dead bytes the LLM never executes.** The skeptic's parallel cut: touch-points are either *already-owned* (nothing left to copy) or *live-invoked* (one edge) — **neither yields vendor.**

**Therefore punch-list #2 pre-pays the entire vendor cost.** Reconciling `brainstorming:43` vs `:230` (route to **`Skill(skill="work-breakdown")`** — the repo's own planning path — instead of `superpowers:writing-plans`) *is the same edit that severs the only live edge.* Do #2 + #3 (de-number) and the repo is effectively self-contained-by-reimplementation already — even the packaging goal becomes a near-trivial follow-on, not a 6-skill fork.

**Reframe — "mostly dead bytes" is NOT a con of vendoring (corrected).** It is evidence the dependency is *already vestigial for 5 of 6 skills* — you neither depend on them at runtime (your wrappers invoke them nowhere) nor need to copy them (you already own larger reimplementations). So the honest action for those 5 is **delete the dangling reference**, which is neither "vendor" nor "keep." Pushed to its conclusion this *dissolves* the vendor question: the path to self-containment is **deletion + redirect to your own skills**, not copying superpowers content in — so "vendor (copy content in)" may never be the right action *even for packaging*. Verified (2026-05-31): the *only* live `Skill(superpowers:*)` edge is `writing-plans`; `subagent-driven-development` and `requesting-code-review` are **prose-only references** (dot-graph nodes / template mention / no-beads fallback), not executed edges — for packaging they are deleted/redirected, not vendored. Net: the real spectrum was never "vendor vs keep"; it was **"finish severing the vestigial dependency vs leave the stubs dangling."**

*(Heuristic caveat, for the record: the "~50% override rate → fork-in-disguise" rule is calibrated for CODE deps where an override is a runtime shim. These are PROSE instructions an LLM reads — an "override" is one sentence. The threshold doesn't transfer; it mis-prices the decision.)*

**Why PIN dominates (the maintenance dispute, resolved):** pinning to 5.1.0 neutralizes the entire churn/drift class the strategist originally used to argue for vendoring — frozen content can't drift, and the brittle "steps 1-3/skip 4-6" ordinal coupling can't silently re-mean anything when pinned (it only bites on a *deliberate, reviewed* version bump). The strategist **withdrew the ordinal-coupling and maintenance-asymmetry arguments as standalone vendor justifications under pinning.** So the only thing vendoring does that pinning can't is **sever the edge** for packaging.

**Refinement — PIN presupposes a version-lock the repo doesn't have yet, so the rule is really three-pronged:**
1. Packaging near-term → **vendor** (zero edges).
2. Packaging deferred **AND** version-lock available → **PIN** *(current recommendation)*.
3. Packaging deferred **BUT** version-lock NOT available in Claude Code plugins → the breaking-change risk on the *live-invoked* edge is unmitigated → **narrow-vendor just the live-invoked skill** as a supply-chain hedge.

Two facts collapse prong 3 in practice: (a) the **only live-invoked edge is `writing-plans`, which punch-list #2 severs** (routes to OpenSpec) — once #2 is done there is *no live-invoked superpowers skill left for a breaking change to hit*, only inert prose references that don't break on upstream changes; and (b) **prong 3's precondition is now disproven — PIN is mechanically available** (verified): plugin installs are **SHA-recorded** (`~/.claude/plugins/installed_plugins.json` carries `version` + `gitCommitSha`; the marketplace source carries `ref` + `sha`), so the install does **not** float to latest — drift requires a deliberate `plugin update`. *Precise claim (provenance): this is "stable by recorded commit SHA, updates are manual," NOT an explicit user-facing "lock/refuse-updates" flag — no such flag was found.* So prong 3 (the no-version-lock contingency) does not arise, and prong 2 (PIN) holds cleanly.

**Corrections folded in (provenance honesty):** the strategist withdrew an earlier claim of a local `.envrc` band-aid — that workaround lives in the *cake* repo (per `beads-worktree-integration.md`), not here; the *real* local band-aid is `beads-execution:46-73`. And all three agree **0 of 4 conflicts require vendoring.** The skeptic further amended to **keep-override + DELETE the vestigial worktree reference** — which *reduces* dependency surface (the opposite direction from vendoring), reinforcing that the strongest coherence finding argues for *fixing the integration*, never for owning a copy.

---

## Con-by-con rulings (user-led — in progress)

This is a **user-led** review: the analysis below each con is *input*; the **RULING is the user's**. Rows are marked as ruled or pending. (Supersedes an earlier draft that pre-asserted a synthesis — that overstepped; rulings belong to the user.)

**Con #1 (vendor) — "Forfeits upstream improvements / silent staleness."** — **RULED: DEAD (2026-05-31).**
Evidence that decided it (verified, `obra/superpowers` per-file history): the two skills you'd keep for updates barely change — `finishing-a-development-branch` untouched ~7 months (last real change Oct 2025), `subagent-driven-development` ~11 weeks (last real change Mar 12, "context isolation"). The only commit to either in the last 4 weeks is the **v5.1.0 release you already hold** (`installed_plugins.json` lastUpdated 2026-05-04). So there is no meaningful upstream-improvement stream to forfeit. *(Also corrects the maintenance-analyst's "churns weekly on these files" — the repo churns weekly, but these two files do not; the files that did churn are the ones being severed/de-numbered anyway.)*

**Con #2 (vendor) — "Owns more code / copies rot."** — **RULED: MOOT (2026-05-31).** A con *of the vendor option*, not the chosen path. Under deletion+redirect nothing is copied (1 edge → existing `work-breakdown`; 5 → deleted refs; brainstorming steps already inlined), so nothing rots; net owned LOC goes *down*. Caveat: punch-list #4 adds ~8 trivial lines of your own (the inline PR-only finish), which replaces a rule-violating dependency call — strictly good, not a rotting fork.
**Con #3 (vendor) — "Re-sync reintroduces the coupling bug."** — **RULED: MOOT (2026-05-31).** Presupposes a held copy + re-sync loop; deletion+redirect creates neither. Third of the "held-copy" cons (with #1, #2) that fall together once the path is not vendoring.
**Con #4 (vendor) — "Bloated failure mode."** — **RULED: MOOT, but KEEP IN MIND (2026-05-31).** Not a held-copy artifact — it's a *principle*, and it doesn't bite the surgical path. Retained on record as the **guardrail against over-correcting** "decouple" into "fork everything to be safe."
**Con #5 (keep) — "Doesn't achieve self-containment."** — **RULED: REAL but MINOR/dormant ("meh", 2026-05-31).** True, but low-stakes and gated on the deferred packaging goal. The residual shrank to ≈ one live `requesting-code-review` template reference after accounting for: rot (review_gate:41, regardless) + dead-by-invariant (`subagent-driven-development` no-beads fallback refs — unreachable because beads auto-installs everywhere). Minor follow-up (P3, not pressing): delete the dead-by-invariant fallback refs (keep the `:12` "why beads-flow over subagent-driven-development" lineage note).
**Con #6 (keep) — "Requires update discipline."** — **RULED: DEAD-ON-DISCONNECT (2026-05-31).** Purely a cost of *keeping* the link; no link → nothing to update → no discipline, and the detection test (#5) becomes unnecessary too.

> **DIRECTION DECISION (user, 2026-05-31): FULL DISCONNECT.** Rationale: Con #1 (dead) removed the only reason to keep the deep deps (upstream updates), so keeping them is all cost / no benefit. Full disconnect = **deletion + redirect to your own skills** (NOT vendoring/copying → does not trip the Con #4 bloat guardrail). Verified head-to-head: the repo matches or exceeds superpowers on every skill it uses (edge lives in the rules+harness layer, not the skills); the only gaps (`receiving-code-review`, `writing-skills`, standalone `systematic-debugging`) are **unused** and reversibly re-installable. **This supersedes the earlier panel "keep-and-override + pin" recommendation below**, which rested on the now-disproven "upstream churns weekly on the coupled files." The action set is largely the same punch-list, minus the pin/detection-test (no link to monitor), plus redirecting `requesting-code-review` to the repo's own review prompts.
**Con #7 (keep) — "Still couples to upstream semantics."** — **RULED: DEAD-ON-DISCONNECT (2026-05-31).** Coupling needs something to couple to; full disconnect removes the references entirely. #5/#6/#7 collapse together once the direction is disconnect (mirror of how #1/#2/#3 collapsed once it wasn't "copy in").

**Con #8 (keep) — "The override/severance work must actually get done (the live bug)."** — **RULED: SURVIVES — but as a one-time EXECUTION risk, NOT a con of the decision (2026-05-31).** It does not argue against disconnecting; it argues for *finishing* it. Evidence it's real for THIS repo: the live brainstorming step-number bug + the stale `review_gate:41` prove integration work has been left half-done before. **On full disconnect the *ongoing* version of #8 disappears** (no link left to silently rot against upstream) — it reduces to "do the disconnect completely; don't leave a half-severed state." Mitigation: file the punch-list as beads and execute it (analysis ≠ done), with one owner for `brainstorming/SKILL.md` to avoid colliding with a2n/ea3. **Honest residual cost of disconnect vs minimal-keep:** slightly more one-time work (also replace `requesting-code-review` → your own review prompts, delete more refs), but small (deletion+redirect to existing skills) and it buys a cleaner end state (no link, no detection test, self-contained).

### Review complete (8/8 ruled): DECISION = FULL DISCONNECT
No remaining con blocks the decision. The only live item is execution (#8): do it, completely, and don't let it half-rot. Net of the sweep: vendor-side cons #1–#4 were held-copy artifacts/guardrail; keep-side cons #5–#7 collapsed on disconnect; #8 is a one-time execution risk common to any path and *reduced* by disconnecting.

## Recommendation: FULL DISCONNECT (decided 2026-05-31, user-led 8/8 con review)

**Disconnect from superpowers entirely — by deletion + redirect to the repo's own skills, NOT by vendoring/copying.** The repo matches or exceeds superpowers on every skill it uses (the edge lives in the rules+harness layer, not the skills); the only live executed edge is `brainstorming:230 → writing-plans`; the 2–3 gaps (`receiving-code-review`, `writing-skills`, standalone `systematic-debugging`) are unused and reversibly re-installable.

> **This supersedes the earlier draft recommendation ("keep-and-override + pin + detection-test").** That rested on the maintenance-analyst's "upstream churns weekly on the coupled files," which the verified per-file history **disproved** (the two would-be-kept skills are near-static; you already hold the latest). With no value in keeping the link, the keep-side cons (#5/#6/#7) collapse and full disconnect dominates. **No pin and no drift-detection-test** are needed — there is no link left to monitor; the one-time *completeness assertion* below replaces them.

### Action set — filed as beads (epic `escapement-e3o`)
*All deletion + redirect to own skills; zero vendored copies. One owner for `brainstorming/SKILL.md` to avoid colliding with `a2n`/`ea3` (the triplicate-authoring lean violation flagged 2026-05-28).*

- **`917` (P1, LIVE BUG):** de-number `brainstorming:41`/`:68` to semantic anchors + route `:230` → `Skill(skill="work-breakdown")`. The stale "skip 4-6" mis-instructs the agent *today* (skips propose-approaches; leaves the writing-plans transition at upstream step 9 unsuppressed). Fixes that, resolves the `:43`/`:230` contradiction, and severs the only live edge. **Sequence under one owner with `a2n`/`ea3`.**
- **`055` (P2):** worktree — drop `superpowers:using-git-worktrees` REQUIRED + the `:46-73` band-aid → mandate `bd worktree create`. Oracle: `grep -q 'bd worktree create' … && ! grep -q 'superpowers:using-git-worktrees' …`.
- **`7yi` (P2):** finishing — replace the `superpowers:finishing-a-development-branch` call (`beads-execution:728`) with an inline ~8-line PR-only finish (drop merge-to-main).
- **`tzf` (P2):** `requesting-code-review` → repoint to the repo's own review prompts (`review_gate` / `dispatching-parallel-agents` / `adversarial-reviewer`); fill any small gap inline.
- **`dnv` (P2):** `review_gate.py:41` — delete the stale `superpowers:code-reviewer` allowlist entry (removed upstream v5.1.0) + swap the test fixture to a native type.
- **`9i5` (P3):** delete the dead-by-invariant `subagent-driven-development` no-beads fallback refs (keep the `:12` lineage note).
- **`srs` (P2, gated on the above):** **completeness assertion + regression guard** — `grep -rE 'superpowers:' claude/` (excluding `docs/analysis` + backups) returns empty. One-time confirm of full severance; doubles as a guard so refs can't silently reappear. *(Replaces the keep-path's drift-detection-test — there's no link to monitor once disconnected.)*
- **`c1v` (P3):** before removing the marketplace, skim `receiving-code-review` + `writing-skills` (the only unused gaps) → port / keep-standalone / decline-as-reinstallable. Disconnect is reversible.

### Reversibility
Vendoring was never needed and isn't being done; if a gap ever bites, re-install superpowers ad hoc and grab the one skill, or port it then. The decision costs nothing irreversible.

---

## Provenance
- **rules-coherence-advocate (final, delivered):** per-conflict override-vs-vendor classification; the petrified/mock coherence framing; conceded off its assigned pro-vendor bias.
- **dependency-strategist (final, delivered; revised twice):** opened "vendor unconditional" → converged to PIN-unless-packaging. Withdrew the `.envrc`-local-band-aid claim (it's the cake repo's) and the ordinal-coupling/maintenance-asymmetry arguments under pinning. Settled rule: PIN vs VENDOR hinged on the packaging goal; "self-containment is zero external edges, which only vendoring delivers."
- **upstream-value-skeptic (final + amendment, delivered):** bloat/silent-staleness argument; the de-numbering defect (new); amended to keep-override **+ delete the vestigial worktree reference** (reduces surface, anti-vendor direction); packaging goal as the sole vendor trigger.
- **Convergence:** 3/3 delivered reviewers agree on the PIN-vs-VENDOR-on-packaging rule and that 0/4 conflicts require vendoring.
- **migration-architect (final, delivered):** the buildable override edit-list (6 edits, ~40 lines, no fork) + the walking skeleton (worktree edit with grep oracle) + the routing target (`:230` → `work-breakdown`) + the vestigial-`:35` finding (already inlined) + the **a2n/ea3 single-owner composition constraint** (avoid triplicate-authoring brainstorming). Confirmed OVERRIDE; vendor buys ~0 because brainstorming-core is already inlined.
- **maintenance-cost-analyst (final, delivered):** the churn data (**35 releases / 6.5 months, landing on the coupled files** — upstream is NOT frozen) + the realized-rot finding (`code-reviewer` removed v5.1.0, still in `review_gate:41`) + the 13-coupling-point count (8 loud-invocation / 3 silent-step-number / 2 prose). Verdict: **hybrid + detection test** — inline brainstorming's ~15 used lines (kills the 3 *silent* couplings), keep the deep self-healing deps (subagent-driven-dev, finishing), and add a grep-resolves detection test as the structural safeguard. This **converges with the override plan** (inline brainstorming = migration-architect's de-number+drop-vestigial; keep-deep = keep-benign) and **elevates the detection test from optional to central** given weekly churn.
- **Convergence (final, 5/5):** KEEP-AND-OVERRIDE + **a detection test** (not pin-alone) + the brainstorming live-bug fix; vendor only on a confirmed near-term packaging goal. 0/4 conflicts require owning code. The maintenance-cost data reframed "pin" as secondary to the detection test — because upstream churns weekly *on the coupled files*, the safeguard you want is loud-failure-on-drift, not freeze.
