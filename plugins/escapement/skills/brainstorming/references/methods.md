# Brainstorming Method Block (shared)

Canonical method vocabulary for brainstorming, shared by two consumers with
different execution topologies (per the consolidation in
`docs/analysis/brainstorm-consolidation-review.md`):

- the **`/brainstorm` skill** — single-agent conversational (rotates lenses inline);
- the **`mol-feature` brainstorm step** — dispatches a team (one agent per lens/method).

Keep the methods here; both consumers reference this one file so the vocabulary
does not drift. Each consumer keeps its own topology and terminal behavior.

## Part A — Anti-bias lenses (perspective reframes, rotate through in order)

Use a different lens per approach; for extended ideation rotate every ~10 ideas.
LLMs cluster toward one distribution mode — rotating lenses forces divergence.

1. **User perspective** — "What does the user actually experience?"
2. **Technical constraint** — "What does the technology make easy or hard?"
3. **First principles** — "What is the irreducible core need? What would we build with 1/10th the budget?"
4. **Business impact** — "What moves the needle on the actual goal?"
5. **Failure mode** — "How does this break? What goes wrong?"
6. **Inversion** — "What if we inverted the main constraint? What if the opposite were true?"
7. **Competitor approach** — "How would [adjacent tool/product] solve this?"
8. **Simplification** — "What if we removed half of this?"
9. **Adjacent domain analogy** — "What problem in [other domain] is structurally similar?"

After cycling through all nine, start over. Never stay in one frame long enough
for clustering to take hold.

## Part B — Structured methods (procedures, not single reframes)

Pull these when the situation calls for a multi-step procedure the lenses lack.
Good defaults for a "should we build this?" challenge: **First Principles,
Pre-mortem, Assumption Reversal, Question Storming.**

- **First Principles** — strip to the irreducible need; rebuild from there.
- **Five Whys** — chain "why?" ~5 deep to the root cause (debugging / causal ambiguity).
- **Pre-mortem** — assume it's shipped and failed; write the story of *why* (prospective hindsight surfaces more, more-specific risks than "what could go wrong").
- **Assumption Reversal** — enumerate every stated premise, then negate each in turn.
- **Question Storming** — generate questions, not answers, until the real problem sharpens.
- **SCAMPER** — Substitute / Combine / Adapt / Modify / Put-to-other-use / Eliminate / Reverse, applied to an existing artifact (forces operator completeness).
- **Six Thinking Hats** — rotate facts / caution / benefit / emotion / creativity / process views.

## Topology note

The persona/panel and sampling-aggregation methods (Stakeholder Round Table,
Debate Club, Red/Blue Team, Tree-of-Thoughts, Self-Consistency) deliver their lift
ONLY under real multi-agent dispatch — they belong to the `mol-feature` team
topology, not single-agent inline narration (where they are ceremony, not mechanism).
