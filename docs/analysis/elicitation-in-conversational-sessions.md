# Should conversational / non-feature sessions source the elicitation & brainstorming method CSVs?

**Date:** 2026-05-29
**Method:** 4-expert named-agent roundtable (`elicitation-panel`), arguing via SendMessage with assigned position biases. Grounded in base principles + modern LLM theory/practice, with empirical anchoring from the `UditAkhourii/adhd` agent skill's published A/B evals.
**Question (user's words):** *"Would we be better if more sessions — conversational/Q&A ones — also sometimes sourced elicitation-methods and brainstorming-methods? Or would that just be noise?"*

---

## TL;DR

**Conditional yes — but the net-positive claim collapses to ONE cheap move fired by default, plus a router.**

- Source exactly **one** thing on *every* lightweight session by default: a **single-pass premise/assumption check** ("is the user's framing even true?"). It is the only divergence-family move cheap enough to run with no team and no aggregation, and it attacks the highest-frequency, highest-cost error in conversational work: accepting an unexamined frame.
- Source **everything heavier only when routed there** — see the three-gate router below.
- The "just noise" worry is **correct** for blanket injection of the heavy or decorative methods, and is avoided entirely by routing rather than by abstaining.

The current wiring (these CSVs sourced *only* by the `mol-feature` brainstorm step) is **narrower than ideal** (it misses exploration-bound Q&A and hypothesis-free debugging) — but the brainstorm step itself is *correctly placed* and *already defaults to good methods* (see "Correction" below). The actionable gap is the conversational/lightweight case, not the feature case.

> **Correction (added after a user challenge invalidated an earlier claim).** An earlier draft said the fix was to make `mol-feature` "prefer the paper-backed `elicitation-methods.csv` scaffolds over the theatrical `brainstorming-methods.csv` defaults." **That was wrong** — a file-level cut where the real boundary is *within* each file. `brainstorming-methods.csv` contains a substantive core (`deep`: Five Whys, Assumption Reversal, Question Storming, Failure Analysis; `structured`: SCAMPER, Six Hats, Decision Tree) and only a ~16-row decorative tail (`theatrical`/`quantum`/`wild`). Decisively: the brainstorm step's *existing* named defaults — First Principles, Pre-mortem, **Assumption Reversal**, **Question Storming** — already point at the high-value methods, and two of those four *live in `brainstorming-methods.csv`*. So there is essentially **nothing to fix** in `mol-feature`: it is exploration-bound, runs with real agent fan-out (where divergent *and* persona methods are legitimately at home), and already steers toward good defaults. The only defensible micro-refinement is to have it explicitly skip the ~16 decorative rows — low value, since the defaults already avoid them. The methods that matter sort by **mechanism** (surface-new-info vs decorative; needs-fan-out vs runs-inline), which is *orthogonal* to which CSV they live in.

---

## Key evidence

### The ADHD dose-response curve (the load-bearing number)
`UditAkhourii/adhd` productizes structured divergent ideation (Diverge: N isolated parallel agents under distinct frames, evaluation forbidden → no anchoring; Focus: separate critic scores novelty/viability/fit, prunes traps, deepens top-K). Its A/B vs a single-shot baseline at the same model, on 6 open-ended engineering problems, independently judged:

| Dimension | ADHD | Baseline | Ratio |
|---|--:|--:|--:|
| breadth | 9.00 | 4.83 | 1.9× |
| novelty | 7.83 | 2.67 | 2.9× |
| **trap detection** | 9.50 | 1.83 | **5.2×** |
| actionability | 9.50 | 6.50 | 1.5× |
| **builder usefulness** | 7.67 | 6.83 | **1.1×** |

The gap between **trap detection 5.2×** and **builder usefulness 1.1×** *is* the answer: structured ideation reliably manufactures more/weirder/better-stress-tested **options** and catches **seductive-but-broken** ideas, but barely moves whether the final build is more **useful** — because usefulness is gated on the problem being under-determined to begin with. On a well-specified task there is no design space to explore, so divergence pays only its token + attention-dilution cost. This was the *best case* (open-ended engineering); factual Q&A would show even less.

### The two CSVs are different objects
- `elicitation-methods.csv` (50 methods) contains **paper-backed inference-time scaffolds**: Tree of Thoughts (Yao 2023), Graph of Thoughts, Thread of Thought, Self-Consistency (Wang 2022), Meta-Prompting / Step-Back (Zheng 2023), Reasoning-via-Planning — *and* facilitation/persona methods (Stakeholder Round Table, Expert Panel, Debate Club, Good Cop Bad Cop, Red Team vs Blue Team).
- `brainstorming-methods.csv` (60 methods) is mostly **vocabulary priors**: categories `theatrical`, `quantum`, `biomimetic`, `introspective_delight` (Pirate Code Brainstorm, Zombie Apocalypse Planning, Quantum Superposition, Emotion Orchestra…).

Injecting the *wrong* CSV broadly is strictly worse than injecting nothing.

---

## The converged model

### Axis A — the three-gate router (WHEN × premise × WHAT)

1. **WHEN gate — exploration-bound vs verification-bound**, proxied by oracle availability.
   The governing variable is whether the target region of the answer space is *wide/unknown* (divergence reduces mode-collapse over a high-value search space → benefit) or *narrow/known* (divergence adds variance + context cost with zero payoff → the 1.1× regime).

2. **conditioned by PREMISE-PROVENANCE.** An oracle proves you *hit* the target; it cannot prove the target is *right*. So "an oracle exists" only earns a skip if the oracle is anchored in an **independent artifact** (a failing test already in the repo, a lint rule, a reproduced stack trace, an observed metric). If the oracle rests only on the **user's assertion**, run one inline premise-check first — it may flip the session back to exploration-bound.
   *Mechanism:* ordinary divergence fights mode-collapse over the **solution** space; premise-vetting fights it over the **problem** space (lock-in on the first framing) — same failure, one level up.

3. **WHAT gate — the aggregation-operator test.** Does the method's measured lift require aggregating/selecting over *independent* samples (majority vote, value-model pruning, MCTS rollouts)?
   - **Yes → harness-required.** A single forward pass cannot fake a vote over samples it never drew. Surfacing these inline is **mock bureaucracy** (the form of rigor without the mechanism). → Self-Consistency, Tree-of-Thoughts, Graph-of-Thoughts, Reasoning-via-Planning. Gate behind `mol-feature` / real agent fan-out.
   - **No → inline-viable.** The lift is just better conditioning of one trajectory; form = mechanism, no theater. → Meta-Prompting/Step-Back, Thread-of-Thought, single-pass self-critique/Reflexion, the premise-check.

### Axis B — substrate caveat
Method tier is **not** a property of the name; it depends on the runtime substrate. The persona/panel methods (Stakeholder Round Table, Debate Club, Red/Blue Team) deliver their lift **only** under isolated multi-agent dispatch (this very roundtable is the existence proof). Narrated by one model in one context ("now imagine a panel argues…"), they collapse to decorative — vocabulary, no topology change, the anchoring they exist to break still present.

---

## Method classification (of 110 catalogued, what's worth surfacing where)

**Inline-viable, fire by DEFAULT on lightweight sessions (the practical answer):**
1. **Assumption Reversal / "is the premise true?"** — the false-premise guard. The only one worth running even on look-factual questions. A **default-on floor, not a ceiling**: one pass catches the *obvious* false premise cheaply; the non-obvious false premise still needs isolated agents.
2. **Step-Back / Meta-Prompting** — "what *kind* of problem is this?" Doubles as the router itself (self-classifies structured vs ill-structured).

**Inline-viable, SITUATIONAL (not per-turn):**
3. **Pre-mortem** — pre-commit / irreversible moments only (best trap-detection ROI).
4. **Five Whys** — unknown-root-cause debugging only.
5. **First Principles** — stuck / circular-conventional-answer only.

**Fan-out-gated (real lift only under multi-agent dispatch; inline = ceremony):** Tree of Thoughts, Graph of Thoughts, Self-Consistency, Reasoning-via-Planning, and all persona/panel methods.

**Banned from auto-sourcing (decorative; can *degrade* output by pulling the token distribution toward fiction):** the ~20 `theatrical` + `quantum` rows and most `introspective_delight` (Pirate Code, Drunk History, Zombie Apocalypse, Quantum Superposition, Body Wisdom, Emotion Orchestra).

### The "naming vs adding" bound (noise-skeptic's decisive narrowing)
The two catalogs are different *kinds* of artifact and the question conflates them. `brainstorming-methods.csv` (60) is almost entirely **divergent ideation** — there is no defensible non-feature session where "Zombie Apocalypse Planning" improves the answer; it belongs gated behind `mol-feature` exactly where it is, concede nothing. The convergent cluster in `elicitation-methods.csv` (Five Whys, First Principles, Pre-mortem, Failure Mode, Rubber Duck, Critique-and-Refine) is the *only* seam with a real argument — **but even there**: a competent agent already performs these without a CSV telling it to. They are in the base model's behavioral repertoire. **The catalog does not *add* the capability; it only *names* it.** So the marginal value of "sourcing the menu" is not "the agent can now do root-cause analysis" (it always could) — it is the much smaller "the agent is *reminded* to be systematic," which must exceed the token + attention cost to be worth anything.

This bound is decisive for the *mechanism* choice: it is the core reason the recommendation is a **behavioral norm/rule** (a cheap, near-zero-token reliability nudge for moves the model already knows) and **never a catalog/menu injection** (paying real tokens to name a capability that already exists). It also confirms the skeptic's null case survives wholesale against the heavy and decorative methods.

---

## Why this is not "another gate" (the framing that matters)
The premise-check is **turn-1 enforcement of two rules this repo already holds**:
- **`never-suppress` / "never downgrade the oracle":** treating a user-asserted premise as verified *is* an oracle-downgrade, one level up. A green `verification_command` on a false-premise spec certifies the wrong answer.
- **`evidence-provenance` / "don't state an inference with the confidence of a verified fact":** answering a question whose premise is unconfirmed, as if established, is exactly that failure — fired at turn-1 instead of caught in review.

A live example from the very session that prompted this analysis: the user's *"why are closed beads shown as filled circles?"* carried a **false premise** (closed items render as `✓`; the `●` they saw was the priority bullet, a misread). A good answer already ran an implicit premise-check. The proposal is to make that move explicit and reliable, not to bolt a brainstorming ceremony onto Q&A.

---

## Recommendation

**The literal question — "should more sessions *source the catalogs*?" — gets a NO.** What survives is two things that *don't source the CSVs at all*: a silent behavioral norm, and one opt-in command. The catalogs stay exactly where they are (gated behind `mol-feature`).

### The option ladder (workflow-integrator, verified against repo conventions)

| Rung | Trigger | Mechanism | Cost | Failure-mode risked |
|---|---|---|---|---|
| **R0 Do nothing** | n/a | CSVs stay gated behind `mol-feature` only | zero | None added (only petrified-by-omission if real unmet demand exists — R1 measures that) |
| **R1 Opt-in `/lens`** ⭐ | user types `/lens` when *they* feel stuck | thin command → SKILL.md loads the 5 inline-viable methods; agent applies 1 this turn | ~2 files, **zero ambient** | Mock — *avoided by construction* (surfaces only runs-inline methods); no coercion (user-initiated) |
| **R2 Advisory nudge hook** | UserPromptSubmit regex on stuck-language | non-blocking `ask`, ≤1×/session | ~1 hook + signal | **Bloated/coercive**: every-prompt tax; value-validation unsolvable (no artifact to check); FP interrupts lookups |
| **R3 Adopt/wrap ADHD** | its own ideation auto-trigger | external diverge→focus skill | external dep, heavyweight | Bloat: heavy fan-out for Q&A; auto-trigger = coercive |
| **R4 Auto-inject** | ambient turn-1 classification | system auto-applies a method | high ambient + every-prompt tax | **REJECT** — mock + coercive + bloated; *and depends on a turn-1 classifier that does not exist in this repo (verified)* |

### Recommended: a silent norm **plus** R1 — and nothing heavier

1. **Silent behavioral norm (no UI, no command, near-zero tokens):** at turn-1, run the premise/assumption-check ("is the user's framing true?") and a step-back ("what *kind* of problem is this?"). These are **not** "sourcing a brainstorming method" — they are **turn-1 enforcement of rules this repo already holds** (`never-suppress`: don't accept a false premise as verified; `evidence-provenance`: don't assert an inference as fact). They survive *only* because they are silent, inline, fire-once, and add no menu and ask no question. The moment they become a visible "want a lens?" prompt, they become a rung-3 nag — which the panel rejects.

2. **R1 — the opt-in `/lens` command** (the only catalog-shaped thing worth building): the user invokes it when *they* feel stuck. It is the cheapest rung that adds a real affordance, *can't become theater* (by the fan-out exclusion below), *can't coerce* (opt-in), and is the **only rung that measures its own worth**. Concrete spec:
   - **2 files** matching repo convention: `~/.claude/commands/lens.md` (thin pointer) + `~/.claude/skills/lens/SKILL.md` (body).
   - **Surfaces only the runs-inline set:** Assumption-Reversal (default #1), Step-Back/Meta-Prompting (default #2), then situationally Pre-mortem (pre-commit), Five Whys (causal-ambiguity debug), First Principles (circular answer).
   - **Load-bearing exclusion (this is what makes it not-mock):** the command MUST NOT surface Tree-of-Thoughts, Graph-of-Thoughts, Self-Consistency, Reasoning-via-Planning, or any persona/facilitation method. Those deliver lift only via real fan-out (independent samples + aggregation operator); a lone agent narrating "let me use Tree-of-Thoughts" produces the *form* without the *mechanism* = mock rigor, worse than nothing. They stay gated behind `mol-feature` where `TeamCreate` actually dispatches the parallel agents the methods require.
   - **Signal (gate-design Rule 2):** skill calls `_gate_signal.record(gate_name="lens", decision="invoked", reason="<method>", command="/lens <args>")` → `.beads/.gate-signal.jsonl`.
   - **Escape/value (Rules 1, 3):** opt-in *is* the affordance (nothing to escape, never blocks); the skill self-validates by surfacing only the 5 inline-viable methods and hard-excluding the 4 fan-out methods, so it can't degrade into theater.

**Reject (panel-unanimous):** R2 ambient nudge hook (fails `gate-design.md` Rule 3 — no artifact to value-validate, degrades to nag; and compounds friction the user is *already* suffering from the Stop-gate every turn this session), R3 auto-adopt ADHD, R4 auto-inject, narrating any fan-out method inline, and auto-sourcing the decorative rows.

**Not recommended (retracted):** an earlier draft proposed "fix `mol-feature` to prefer `elicitation-methods.csv` over `brainstorming-methods.csv` defaults." Retracted — see the Correction in the TL;DR. The brainstorm step is correctly placed and already defaults to good methods; the optional micro-refinement (skip the ~16 decorative `theatrical`/`quantum`/`wild` rows) is low value because the named defaults already avoid them.

### What to measure (help vs bloat) — all from the signal log, zero new infra
1. **`/lens` invocations / 30 days.** ~0 → retire (fall back to R0, petrified-by-omission confirmed). Healthy non-zero → keep.
2. **Method distribution.** ~100% the 2 defaults → trim the situational tail as dead weight.
3. **Post-invocation continuation** (did the session proceed productively / pour a molecule / close the bug after a `/lens` turn) vs sessions without — proxy for "did the lens unstick anything."
4. **Anti-signal:** users invoke `/lens` then immediately re-ask the raw question → methods aren't landing → revisit the set.
5. **Silent-norm mock-detection (the hard one):** the premise-check is invisible to overreach-checks by construction. Only an A/B with the move stripped, scored by an independent oracle, exposes whether it's real or label-theater. If you can't run that A/B, assume mock and keep the norm minimal.

Half-life review (bureaucracy Operating Rule 1): re-justify `/lens` at 12 months against metric #1.

---

## Provenance of this synthesis
- **llm-theorist (final, delivered):** the three-gate router, the aggregation-operator test, the bounded-floor calibration of the premise-check.
- **elicitation-scientist (final, delivered):** the needs-fan-out vs runs-inline axis, the 5-method inline shortlist, the method taxonomy (surface-new-info / reframe / decorative), and the premise-gate's legitimacy as enforcement of `never-suppress` + `evidence-provenance`.
- **noise-skeptic (opening + sharpened final close delivered):** argued mostly-noise; load-bearing arguments — (1) ADHD's 1.1× builder-usefulness on the *best-case* task undercuts blanket injection; (2) the user's recent sessions are single-correct-answer lookups with no design space; (3) `delicate-art-of-bureaucracy` names the bloat + mock failure modes this mechanism would generate; (4) **the "naming vs adding" bound** (see section above) — the convergent methods are already in the model's repertoire, so the catalog only names a capability the model already has, making the marginal value a small reliability nudge, not a new capability. The skeptic conceded **nothing** on the brainstorming catalog (keep gated behind `mol-feature`) and conceded only the narrow convergent seam — and even there demanded the value be proven over the model just doing the reasoning. This critique is *adopted*, not merely noted: it is why the recommendation's mechanism is a behavioral norm, never menu injection. The skeptic's null case **survives intact** against blanket injection of heavy/decorative methods.
- **workflow-integrator (final not returned before synthesis):** the option ladder above is reconstructed by the synthesizer from the converged material and tied to `gate-design.md`, not delivered by the agent. [marked construction, not agent output]

[Provenance note: agent positions above are summarized from their reported messages. workflow-integrator never delivered a final after two nudges; synthesis proceeded under outcome-bias rather than block indefinitely on a possibly-hung agent. noise-skeptic's sharpened close arrived during synthesis and was folded back in.]
