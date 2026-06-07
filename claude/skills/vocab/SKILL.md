---
name: vocab
description: Use whenever you set out to understand or research an UNFAMILIAR external domain — building something is NOT required (also: preparing for a decision or meeting, forming a position, an investigation, or designing) — when getting the field's framing right matters and a load-bearing distinction hinges on terminology you don't command (e.g. entitlement vs ownership, queue vs group, per-system vs per-object). A single living "vocab-scout" recovers the field's real terminology FIRST; then narrow research searches USING those terms, DELEGATING the fan-out to the deep-research skill. Invoke it directly (standalone) OR via the brainstorming/discovery/agent-teams pointers — it is a front door, not only a sub-step. Thin wrapper, not a second research route. Do NOT use for familiar domains, codebase/org-internal questions, urgent one-fact lookups, or topics with no established external literature.
---

# Vocabulary-First Research (`/vocab`)

Promoted from observed practice — recovered from **3 sessions across 2 research
efforts** (Looker deprovisioning, 2026-05-20, two sessions; continuation-harness
stop-gate, 2026-05-22, one session).
**On-demand and opt-in. Not a gate. Nothing here blocks.**

This skill owns **Phase 1 only** (terminology recovery) and **delegates Phase 2
to the `deep-research` skill**. It does not re-implement fan-out / fetch / verify
/ synthesize — that would be a second route to the same output (the
[[feedback_workflow_simplification]] "two routes = retire one" collision).
`deep-research` is a compiled-in skill with no terminology phase; this is the
missing **outward front-end** that feeds it.

> **Implementation guard — do not "amend" deep-research.** `deep-research` is a
> compiled-in binary skill; it has **no editable source** and **cannot** have a
> phase added to it. vocab-first is a thin wrapper that **calls** deep-research
> for Phase 2 — it is NOT a phase prepended inside deep-research, NOT a discovery
> mode (discovery's Input Gate requires confirmed framing; this runs pre-framing),
> and NOT a `dispatching-parallel-agents` use (that skill excludes sequential
> dependencies; this is one). Don't go looking for deep-research's source to edit
> — there isn't one.

## Access — this is a front door, not only a sub-step

Three independent ways in, by design — none depends on the others:
1. **Directly** — invoke `/vocab` (or via the Skill tool) any time, for standalone
   understanding/research with no build attached.
2. **Auto-trigger** — the description above matches research/understanding
   requests into an unfamiliar domain; no other skill needs to be active.
3. **Hand-off** — `brainstorming`, `discovery`, and `agent-teams-default` carry a
   gated pointer for when the need surfaces mid-flow.

The tie-ins are additive discoverability. Removing every pointer would not make
this skill unreachable — paths 1 and 2 stand alone.

## Honest calibration — read this first

The method is **high-variance**. Demonstrated load-bearing in **1 of the 2
research efforts** (the Looker effort; the stop-gate effort was near-theater —
vocabulary applied as post-hoc labels). It is **not** an always-on research
default. The seeding runs
also over-provisioned badly — dozens of agents dispatched for ~3 substantive
synthesis inputs, with duplicate and empty-ack agents. So: **most research does
NOT need a vocab phase.** Run this only inside its narrow positive regime (below),
and keep the fan-out small.

## Why it exists (and why it is not a duplicate)

Searching an unfamiliar field in *your own* words misses the field's literature,
which is indexed under its *terms of art*. Distinct from the neighbors by
**source of truth** (the irreducible axis — file-verified):

| Method | Orientation | Source of truth |
|--------|-------------|-----------------|
| `brainstorming` / `discovery` | **inward** | the user's head + model priors (reshuffles weights; retrieves nothing). Discovery's Input Gate also *requires confirmed framing first* — vocab-first runs pre-framing, so it structurally cannot be a discovery mode. |
| `deep-research` | outward | web fan-out → verify (no terminology phase) |
| **vocab-first** | **outward** | the field's published corpus — recovers terms the model did not hold |

## When to use — the trigger (all three must hold)

1. Domain **unfamiliar** — you cannot confidently name 5+ of the field's core
   terms; **AND**
2. an external literature exists whose **terminology encodes a distinction the
   model's default framing gets WRONG** (not merely relabels); **AND**
3. the output is **load-bearing** — a decision, position, recommendation, design,
   *or your own working understanding that something downstream rests on*
   (a meeting, a 1:1, an investigation, a judgment call). **Building is not
   required**; idle curiosity with nothing resting on it does not qualify.

Clause 2 is the anti-theater guard, and it is **self-testing**: *if you cannot
name the specific wrong prior the field's vocabulary would correct, the trigger
fails — do not run this.* (gate-design rule #3 "validate value not presence",
applied to a trigger; lineage = why-drilling's "load-bearing why".)

**This trigger is testable — bake the control pair in as a standing regression:**
- **POSITIVE control (Looker run):** "a group can *share* access but cannot *own*
  it; a queue *can* own." The obvious-but-wrong instinct is "make it
  group-owned"; the term names why that fails. PASSES — and this distinction
  changed a downstream conclusion (see Evidence).
- **NEGATIVE control (stop-gate run):** an AI-agent domain the model already
  half-knew; vocabulary got applied as post-hoc labels. FAILS the trigger —
  correctly excluded. The trigger must keep failing this class.

## When NOT to use — negative controls

Familiar domain · codebase/org-internal question ("where is this CSV used?") ·
urgent one-fact lookup · pure preference with no literature. If the trigger fires
on any of these, it is mis-specified.

## Evidence — three SEPARATE lanes (do not cross-launder)

The value claim rests on three distinct, separately-cited findings. Conflating
them is an evidence-provenance violation:
1. **Upstream term-correction** *(verified)* — the scout caught the seed brief's
   "KeepAlive" as non-standard (OTP's word is `permanent`; "level/edge-triggered"
   is K8s, not OTP). This corrects *input* vocabulary. It does **not** prove any
   downstream find changed — the stop-gate run recorded zero Phase-1→Phase-2
   corrections.
2. **Outward find** *(verified)* — "disposition / transfer of custody" (a
   records-management term-of-art) opened the ISO 15489 / NARA / NIST AC-2/PS-5
   literature a naive "deprovision a user" search would miss.
3. **Conclusion change** *(verified — the A-class instance, lead with this)* — a
   Phase-2 agent's principle P3 flipped from per-**system** to per-**object**
   ("a load-bearing design constraint, not a footnote") *because* the scout's
   glossary table resolved its open `[verify]`.

The Phase-1→Phase-2 dependency is **concentrated** — load-bearing for the *one
lane* whose conclusion hinged on the unfamiliar distinction (evidenced by the
scout's by-name mid-run handoff resolving that lane's `[verify]`), **not** a
universal property of every Phase-2 agent.

## The method

### Phase 0 — team
`TeamCreate` + named agents with `team_name` + `name`. Mechanics live in
`agent-teams-default` and `dispatching-parallel-agents` — follow them, don't
restate. This is the documented home for the one shape that skill *excludes*: a
**sequential** dependency (Phase 2 consumes Phase 1).

### Phase 1 — a single LIVING vocab-scout
One scout → **one authoritative glossary** (parallel scouts fragment the frame).
Bounded exception: a problem spanning 3+ truly-disjoint literatures may use ≤N
scouts, but a single synthesizer **must merge to one glossary** before Phase 2.

The scout writes a glossary **file** (see Persistence) with three named outputs:
1. a **sourced glossary** — per term: definition, source, **inline provenance
   tag** `[verified]`/`[inferred]`/`[verify]`, and "how it maps to our problem";
2. a **"top 8–12 seed terms"** list;
3. **flagged non-standard / wrong terms** in the user's brief (the
   "KeepAlive"→`permanent` catch).

The scout is **living, not fire-once** — this is the anchoring-hazard mitigation,
not a convenience. A fire-once scout is an anchor; Phase 2 inherits its blind
spots with no correction path. The living scout is re-dispatched against the
union of Phase-2 **glossary deltas** (below) to convert `[verify]`→`[verified]`.

### Abort-on-empty (repair step — do not skip)
If the glossary has **no `[verified]` anchor to a real external named concept,
STOP** — vocab-first doesn't apply; answer directly. Abort on *absence of any
verified anchor*, not on the mere presence of `[inferred]` entries (a
half-inferred glossary with real terms-of-art is still valid).

The `[verified]` anchor must be a **FIND** — a field term-of-art that maps onto
the problem (Looker's "disposition / transfer of custody"). A `[verified]`
*correction of the user's own brief* (the "KeepAlive"→`permanent` catch) does
**not** satisfy abort-on-empty: that's upstream cleanup, not an external find, and
a glossary carrying only corrections is the stop-gate near-theater case this step
exists to catch.

### Phase 1 → 2 handoff
The glossary **file is the single source of truth.** Each Phase-2 prompt carries
**(1) the file path** (read in full) and **(2) inline ONLY the `[verified]`
term-NAMES, labeled "as of dispatch; authoritative list in `<file>`."** Never
inline `[verify]`/`[inferred]` terms (they'd propagate as if settled); Phase-2
pulls those from the file where the tag is visible and challengeable. On any
conflict, the file wins over the stale inline hint.

### Phase 2 — narrow, targeted research (delegates to deep-research)
Dispatch **3 ORTHOGONAL lanes** (principles / prior-art / guidance), disjoint by
construction — if you can't state how lane B differs from lane A, don't dispatch
B. **Hard cap: 4 lanes** (each with a one-line orthogonality justification); **>4
requires explicit user approval** of the named extra angle. (Evidence-derived:
the Looker run's genuinely distinct archetypes were ~4; every lane beyond that
produced duplication or empty acks.)

Each lane searches **using the vocabulary**, hands the fan-out to the
`deep-research` skill, organizes findings by seed-term slot, and emits a
**`## Glossary Deltas`** section (terms it couldn't ground / found mis-defined /
found a better term for / upgraded `[verify]`→`[verified]`).

- **Dedup guard:** before synthesis the lead computes pairwise similarity over
  the findings **files** — concretely, `difflib.SequenceMatcher(None, a,
  b).ratio()` (what surfaced the 1.00-identical agent trio in the seeding run);
  embeddings are an acceptable substitute. >0.9 → lanes weren't orthogonal →
  collapse, don't count duplicates as corroboration. (Free, via the persisted
  files.)
- **Instrumentation (required — this is how the skill earns or loses its keep):**
  each lane logs, **per non-obvious source, which glossary term was the search
  input that surfaced it.** This converts "the vocab step helps" from assertion
  into evidence every run must produce. **Concrete retirement trigger:** after
  **5** real invocations, if **fewer than 2** show a logged term→find linkage,
  retire the skill — the value isn't there.

### Synthesis
The lead reads the per-agent **files** (never transcripts), re-dispatches the
scout against the delta union if needed, then maps the field's vocabulary onto the
user's actual problem.

## Persistence — "nothing load-bearing on the wire"

See the **research-findings-persistence** rule (general, applies to any
multi-agent dispatch). In short: every agent writes its complete artifact —
findings + sources + inline provenance + glossary deltas — to a gitignored
`.research/<topic>-<date>/<NN>-<agent>.md` **before** sending a short pointer
message. Anything that lives only in a SendMessage is lost when the agent shuts
down (the exact bug these runs hit — findings had to be rebuilt forensically from
SendMessage payloads). Three instances of the one principle: findings → file;
provenance tags → inline in the file; glossary deltas → inline in the file.

## Status

Promoted-from-observed-practice (3 sessions / 2 efforts), not invented. **Not a
gate** — no hook, denial, waiver, or signal. Defends against mock-bureaucracy by
being opt-in + the substance-bar trigger + the standing pos/neg control pair — not
by enforcement. Review/retirement trigger: after 5 invocations, retire if fewer
than 2 show a term→find linkage (see Instrumentation).
