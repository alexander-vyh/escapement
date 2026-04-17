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

## Section 5: Terminal Routing

After the user approves a design direction, determine complexity and route accordingly.

### Route A: Needs Discovery

The idea needs further design if ANY of these are true:
- The riskiest assumption is unclear or untested
- Scope is uncertain (can't describe what's in and what's out)
- The change is cross-cutting (touches multiple systems, teams, or domains)
- There are multiple unknowns that interact with each other

**Action:** Announce the routing decision, then **invoke the discovery skill directly** — do NOT tell the user to run it themselves:

> "This is complex enough to need discovery. Here's why: [specific reason from brainstorming]."

Then immediately invoke the Skill tool:
```
Skill(skill="discovery", args="<feature-name>")
```

Build the `args` string to include the brainstorming context that discovery needs:
- **Problem statement** from brainstorming
- **Chosen direction** and rejected alternatives (with reasons)
- **Open questions** that brainstorming couldn't resolve

Discovery should NOT re-explore the problem space. It should focus on the unresolved questions and fill in the 7 required sections using the brainstorming output as input.

If brainstorming can't converge to specific open questions, it hasn't produced value — go back and sharpen the questions before routing.

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
