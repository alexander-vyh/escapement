---
name: brainstorming
description: >
  Enhanced brainstorming — challenges whether work should be done at all,
  rotates creative lenses to fight semantic clustering, and routes to
  /discovery or writing-plans based on complexity.
---

# Enhanced Brainstorming

This skill wraps the superpowers brainstorming skill with additional gates, adversarial probes, anti-bias mechanisms, and terminal routing. The sections below run in order.

---

## Section 1: "Should This Be Done At All?" Gate

This gate runs FIRST, every time, before any brainstorming begins. Ask these three questions and wait for answers before proceeding:

1. **"What's the cost of not doing this?"** — If the user can't name a concrete cost (lost revenue, user pain, blocked work, growing tech debt), stop here. No cost = no work.

2. **"What's the minimum version that produces the outcome?"** — This is appetite-based, not estimate-based. Don't ask "how long will this take?" Ask "what's the smallest thing that delivers the result?"

3. **"How much time is this *worth*?"** — Fixed time, variable scope. The user picks a time budget (a few hours, a day, a week). Scope flexes to fit the budget, not the other way around. This is a Shape Up principle: appetite controls scope.

**Early termination:** If all three answers indicate trivial value (no real cost to skipping, the minimum version is "just do it," and it's worth less than an hour), terminate brainstorming immediately:

> "This doesn't warrant further design. Either do it directly or drop it."

Do not proceed to the core brainstorming flow. The gate exists to prevent over-engineering trivial work.

---

## Section 2: Core Brainstorming Flow

Follow steps 1-3 of the superpowers brainstorming skill (explore context, ask clarifying questions, propose approaches):

1. **Explore project context** — Read CLAUDE.md, relevant code, and existing docs to understand the landscape.
2. **Ask clarifying questions** — One at a time, wait for answers before continuing.
3. **Propose 2-3 approaches** — Each with trade-offs clearly stated.

SKIP superpowers steps 4-6 (present design, write design doc, transition to implementation) — this skill handles routing differently in Section 5 below.

**This skill replaces the superpowers brainstorming terminal routing. Do NOT invoke writing-plans automatically — Section 5 below determines the next step.**

---

## Section 3: Adversarial Probe

This probe is injected AFTER the superpowers flow proposes 2-3 approaches, BEFORE the user picks one. Present it under this heading:

> **"Here's why this might be the wrong thing to build..."**

Requirements for the probe:

- **Grounded in project context.** Read CLAUDE.md, existing design docs, PRDs, and any relevant project files before writing the probe. Generic risks ("this could be complex") are not acceptable.
- **Name a specific alternative** that would be cheaper, simpler, or already partially built. Reference actual code, tools, or patterns in the project if they exist.
- **Challenge the framing**, not just the implementation. Is the user solving the right problem? Is there an upstream fix that eliminates the need entirely?
- **The probe is designed to be wrong sometimes.** That's fine. Its job is to force the user to articulate why the idea IS worth building. If the user can't counter the probe, that's a signal the idea needs more thought.

After presenting the probe, ask: "Does this change your thinking, or should we proceed with choosing an approach?"

The user must respond to at least one specific point from the probe, even if the response is "I've considered this because X." A bare "proceed" is not sufficient — ask which point they're dismissing and why.

---

## Section 4: Anti-Bias Domain Rotation

When proposing the 2-3 approaches (superpowers step 3), use a different lens for each approach. If generating more than 3 approaches or doing extended ideation, rotate lenses every ~10 ideas. LLMs tend to generate ideas that are semantically similar — rotating lenses forces divergent thinking.

**Lenses (rotate through these in order):**

1. **User perspective** — "What does the user actually experience?"
2. **Technical constraint** — "What does the technology make easy or hard?"
3. **First principles** — "What is the irreducible core need? What would we build with 1/10th the budget?"
4. **Business impact** — "What moves the needle on the actual goal?"
5. **Failure mode** — "How does this break? What goes wrong?"
6. **Inversion** — "What if we inverted the main constraint? What if the opposite were true?"
7. **Competitor approach** — "How would [adjacent tool/product] solve this?"
8. **Simplification** — "What if we removed half of this?"
9. **Adjacent domain analogy** — "What problem in [other domain] is structurally similar?"

**Announce each rotation explicitly:** "Switching lens to [X]" — so the user can see the shift and engage with the new perspective.

After cycling through all seven, start over. The point is never to stay in one frame long enough for clustering to take hold.

---

## Section 5: Convergent Interview — Confirm the Problem Framing

Sections 1-4 are **divergent** — they explore the space and fight premature
convergence. This section is **convergent**: it narrows to ONE confirmed problem
framing that downstream skills can trust without re-deriving it.

It runs AFTER the user has picked a direction (post-Section 3 probe) and BEFORE
terminal routing. Its length is set by how much shared understanding already
exists — if Sections 1-4 already nailed the six fields below, this is a fast
confirmation pass; if major fields are still fuzzy, it is a long branch-walking
interview. Do not skip it because it feels redundant; confirm explicitly.

### The interview

Conduct a relentless, one-question-at-a-time interview. This is NOT a batch of
questions — it is a branch-walking conversation where each answer shapes the
next question.

- **One question at a time.** Never present a batch. Ask, wait, hear the answer,
  then form the next question from it.
- **Every question carries your recommended answer.** Do not ask blanks. Propose:
  "I'd assume [X] because [Y] — correct, or not?" The user reviews and corrects;
  they do not author from scratch. Reviewing is faster than authoring.
- **Walk the branches.** When an answer opens a dependency, follow it to its root
  before moving on. ("We'd cap it culturally" → "who enforces the cultural norm?"
  → "no one's named yet" → "then who owns the what-and-why here?")
- **Verify, don't ask, when you can.** If a question can be answered by reading
  the codebase or docs, do that instead of asking the user.
- **Terminate on confirmed shared understanding, NOT on question count.** There
  is no target number. The interview ends when all six fields are confirmed by
  the user — not when you have asked "enough."
- **Do NOT drift into solutioning.** This section narrows the *problem*, the
  *why*, and the *riskiest assumption*. The moment you find yourself proposing
  *how* to build it, stop — that is discovery's job, and moving it here just
  relocates the over-permissiveness upstream.

### The six fields — the interview is done when all six are confirmed

Each field must be **confirmed by the user**, not inferred and assumed:

1. **Problem** — the observable thing that is wrong. Not "what we'll build."
2. **Why now** — the forcing reason this is worth doing now, not later or never.
3. **Decision authority** — who owns the *what* and *why*. If there is no
   distinct owner (a solo project, a personal tool), that is a valid answer:
   record `none — [reason]` (e.g. "none — solo project, I own it"). What is NOT
   acceptable is leaving it `TBD` or blank — that means the question was skipped,
   not answered.
4. **Behavioral population** — who must change their behavior for this to work.
   If the work requires no behavior change from anyone (a library, a standalone
   script), that is a valid answer: record `none — [reason]`. When there IS a
   population, name it specifically — the most dangerous framing error is
   describing the problem in terms of one group while the people who must
   actually change are a different group.
5. **Riskiest assumption + liveness** — "We are betting [X]. We will know we are
   wrong when [Y]. We would discover that within ~2 weeks via [Z]." All three
   blanks filled. If you cannot fill [Z], the assumption is not yet testable —
   keep interviewing.
6. **Success criteria** — the observable real-world outcome that means this
   worked. Not "it ships," not "tests pass."

### Forcing check on the riskiest assumption

After the user confirms field 5, ask one more question before moving on:

> "If this assumption turns out false two weeks from now — what would you do
> differently? One sentence."

If the user can answer that cold, the assumption is genuinely owned. If they
cannot, it was approved, not understood — return to field 5 and keep
interviewing. This costs nothing when the understanding is real; it only adds
time when the framing is thin, which is exactly when the time is worth spending.
A hook can check that the riskiest assumption field is *filled*; only this
exchange checks that it is *owned*.

### Output: the problem-framing artifact

When all six fields are confirmed, write them to:

```
openspec/changes/{name}/problem-framing.md
```

Derive `{name}` as kebab-case from the feature. Create the directory if it does
not exist. The file has one `##` section per field, each holding the *confirmed*
answer — not the interview transcript, not the questions. This artifact is
discovery's required input; discovery will refuse to draft solution artifacts
without it.

**Verify the write before announcing.** After writing the file, read it back and
confirm all six `##` sections are present and non-empty. If the write did not
land — wrong directory, IO error, partial write — do NOT announce success and do
NOT route to discovery. Surface the failure to the user instead. "Problem framing
confirmed" must mean the file actually exists on disk, or routing to discovery
will loop (discovery's gate denies, sends the user back here).

Once verified, announce briefly: "Problem framing confirmed for '{name}'."

---

## Section 6: Terminal Routing

After the user approves a design direction, determine complexity and route accordingly.

### Route A: Needs Discovery

The idea needs further design if ANY of these are true:
- The riskiest assumption is unclear or untested
- Scope is uncertain (can't describe what's in and what's out)
- The change is cross-cutting (touches multiple systems, teams, or domains)
- There are multiple unknowns that interact with each other

**Action:** Announce the routing decision, then **invoke the discovery skill directly** — do NOT tell the user to run it themselves:

> "This is complex enough to need discovery. Here's why: [specific reason from brainstorming]."

Section 5's convergent interview has already written
`openspec/changes/{name}/problem-framing.md`. Then immediately invoke the Skill tool:
```
Skill(skill="discovery", args="<feature-name>")
```

Do NOT re-pass the framing through `args` — it lives in `problem-framing.md`.
Discovery detects that artifact, treats it as its confirmed input, and proceeds
directly to solution design. Discovery does NOT re-explore the problem space.

If Section 5 could not converge all six fields — most often because decision
authority is unnamed — discovery is not unblocked yet. Do not route. Name the
missing field as the blocker and stop here.

### Route B: Ready for Planning

The idea is well-defined if ALL of these are true:
- Clear scope (can describe what's in and what's out)
- No risky assumptions remaining
- Small, contained change

**Action:** Announce the routing decision, then **invoke the writing-plans skill directly** — do NOT tell the user to run it themselves:

> "This is well-defined enough for direct planning. Here's why: [specific reason]."

Then immediately invoke the Skill tool:
```
Skill(skill="superpowers:writing-plans")
```
