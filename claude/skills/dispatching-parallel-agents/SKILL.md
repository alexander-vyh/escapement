---
name: dispatching-parallel-agents
description: Use when facing 2+ independent tasks that can be worked on without shared state or sequential dependencies
---

# Dispatching Parallel Agents

This skill provides named-agent dispatch for parallel work. All agents MUST have a `name` so they can communicate via SendMessage.

---

## Overview

You delegate tasks to specialized **named** agents on a **team**. By precisely crafting their instructions and context, you ensure they stay focused and succeed at their task. They should never inherit your session's context or history — you construct exactly what they need.

**Core principle:** Dispatch one **named** agent per independent problem domain. They work concurrently and communicate via `SendMessage`.

## Beads Integration

Named agent teams and beads are complementary — beads tracks *what* to do, teams handle *how* agents coordinate while doing it.

- **Project has `.beads/`:** Use `/beads-execution` for the dispatch loop (`bd ready` → claim → dispatch → review → `bd close`). Agents dispatched by beads-execution MUST still have a `name`.
- **No beads:** Use this skill directly. Named agents are the constant regardless of whether beads is present.

## When to Use

**Use when:**
- 2+ independent tasks that can run in parallel
- Research, reviews, or analysis with multiple independent angles
- **Roundtable discussions** — expert personas who argue
- Multiple subsystems broken independently

**Don't use when:**
- Failures are related (fix one might fix others)
- Need to understand full system state
- Agents would interfere with each other (editing same files)

## The Pattern

### 1. Identify Independent Domains

Group work by what's independent:
- File A tests: Tool approval flow
- File B tests: Batch completion behavior
- File C tests: Abort functionality

### 2. Dispatch Named Agents

**MANDATORY: Every agent MUST have a `name`.** The hook will block anonymous agents.

```
Agent(
  name="abort-fixer",
  description="Fix abort test failures",
  prompt="Fix the 3 failing tests in agent-tool-abort.test.ts. [details...]
    If your fix affects batch-fixer or race-fixer's domain, use SendMessage to notify them."
)

Agent(
  name="batch-fixer",
  description="Fix batch completion failures",
  prompt="Fix the 2 failing tests in batch-completion-behavior.test.ts. [details...]
    If your fix affects abort-fixer or race-fixer's domain, use SendMessage to notify them."
)

Agent(
  name="race-fixer",
  description="Fix race condition failures",
  prompt="Fix the 1 failing test in tool-approval-race-conditions.test.ts. [details...]
    If your fix affects abort-fixer or batch-fixer's domain, use SendMessage to notify them."
)
```

All three can SendMessage to each other by name.

### 4. Review and Integrate

When agents return:
- Read each summary
- Verify fixes don't conflict
- Run full test suite
- Integrate all changes
- If in a beads project: `bd close <task-id>` for each completed task
- Shut down the team when done

## Roundtable Pattern

A "roundtable" is a specific use of team agents where expert personas **argue and critique each other's positions** via SendMessage.

```
Agent(
  name="security-reviewer",
  description="Security perspective review",
  prompt="Review the auth middleware changes from a security perspective.
    After your initial review, use SendMessage to share your findings with ux-reviewer and perf-reviewer.
    Read and respond to the other reviewers' findings.
    Push back if you disagree — this is a debate, not a rubber stamp."
)

Agent(
  name="ux-reviewer",
  description="UX perspective review",
  prompt="Review the auth middleware changes from a UX perspective.
    After your initial review, use SendMessage to share your findings with security-reviewer and perf-reviewer.
    Read and respond to the other reviewers' findings.
    Push back if you disagree — this is a debate, not a rubber stamp."
)

Agent(
  name="perf-reviewer",
  description="Performance perspective review",
  prompt="Review the auth middleware changes from a performance perspective.
    After your initial review, use SendMessage to share your findings with security-reviewer and ux-reviewer.
    Read and respond to the other reviewers' findings.
    Push back if you disagree — this is a debate, not a rubber stamp."
)
```

## Agent Prompt Structure

Good agent prompts are:
1. **Named** — `name` parameter on every Agent call
2. **Focused** — One clear problem domain
3. **Self-contained** — All context needed to understand the problem
4. **Peer-aware** — Lists other agents' names so they can coordinate via SendMessage
5. **Specific about output** — What should the agent return?

### Effort Calibration

Match depth of work to task type. Do not converge on an answer before reaching the expected effort level:
- **Simple lookup / single-file read:** 3-10 tool calls
- **Investigation / multi-file analysis:** 10-20 tool calls
- **Full implementation with tests:** 20-40 tool calls

## Prompt Hygiene for Review Agents

When you dispatch a review or blinded agent, the `prompt` field IS that
agent's entire worldview. Any framing you write becomes what the agent
thinks the world looks like. Scan for these patterns before dispatching:

| Pattern | Example | Fix |
|---------|---------|-----|
| Hypothesis smuggling | "I think X is broken because Y" | "Assess X for correctness" |
| Conclusion priming | "Confirm Y is fine" / "Verify Z works" | "Determine whether Y/Z" |
| Conversation leakage | "The user said...", "We've been debugging..." | Remove entirely |
| Pre-curated quotes | Pasting code inline in the prompt | File path + line range |
| Desired verdict | "Find a reason to reject" | "Report BLOCK/CONCERN/NOTE" |

**Rule of thumb:** your prompt should describe the TASK, not the VERDICT.
If you can already state the expected conclusion, you're priming the agent.

**Give coordinates, not quotes.** Pass file paths and let the agent forage
with Read/Grep. Pre-quoted code is pre-interpreted code — interpretation is
exactly what you're delegating. Keep quoting for context the agent genuinely
cannot discover on its own (spec ID, external ticket, error message text).

**Sanity check.** Before dispatching, ask yourself: if a teammate read this
exact prompt with no other context, would the agent's conclusion be
predetermined by your wording? If yes, rewrite.

Reviewer agents whose personas already include a Blinding Discipline section
(e.g. `adversarial-reviewer`) will actively ignore priming in the prompt,
but that is a second line of defense. The first line is you.

## Common Mistakes

**❌ No name:** `Agent(prompt="Fix tests")` — anonymous, unaddressable via SendMessage
**✅ Named:** `Agent(name="test-fixer", prompt="Fix tests")` — addressable, can coordinate

**❌ Simulated roundtable:** Writing persona dialogue in your own output
**✅ Real roundtable:** Named agents that independently analyze and argue via SendMessage

## Vocabulary

> Canonical, principle-anchored definitions live in
> [`docs/VOCABULARY.md`](../../../docs/VOCABULARY.md). Local quick-reference below.

| User says | Means |
|-----------|-------|
| "agent team" | 2+ named agents |
| "roundtable" | Named agents arguing via SendMessage |
| "panel of experts" | Named agents with different persona prompts |
| "have them talk to each other" | Named agents using SendMessage |

**"Roundtable" NEVER means writing simulated dialogue in your output.** It ALWAYS means real named agents that independently analyze and communicate via SendMessage.

## Continuation Discipline for Dispatched Agents

**Every agent prompt MUST include this block** (copy verbatim into the prompt):

> **CONTINUATION DISCIPLINE:** DO NOT wind down prematurely. DO NOT summarize
> remaining work and stop. If you find additional problems during your work, FIX
> THEM — do not list them and declare done. If you hit an obstacle, investigate and
> work around it — do not report it as a reason to stop. You are done when the
> OUTCOME is verified end-to-end, not when you've made an attempt. Run the actual
> test/command/workflow and confirm it passes. "I believe this works" is not
> verification — "the tests pass" is verification.

**For the main agent coordinating the team:**

DO NOT STOP after collecting agent results. If any agent reports unresolved issues,
dispatch a follow-up agent or SendMessage instructions to fix them. If the
integrated result fails verification (full test suite, end-to-end check), dispatch
agents to fix the failures. Summarizing what agents accomplished is not completion —
the verified outcome is completion.

## Verification

After agents return:
1. **Review each summary** — Understand what changed
2. **Check for conflicts** — Did agents edit same code?
3. **Run full suite** — Verify all fixes work together
4. **Spot check** — Agents can make systematic errors
5. **Shut down the team** — SendMessage shutdown_request to each agent
6. **If ANY verification step fails** — dispatch new agents to fix, do NOT report partial success

## Agent Pairing for Quality

When dispatching implementation agents, pair them with independent QA agents that
work from the success criteria or spec — NOT from the code. The always-on
`agent-teams-default.md` rule carries one-line summaries of these patterns and
points here for the full write-ups. The fourth pattern — the **Completeness
Critic** — has its own section immediately below.

### Independent Test Agent Pattern

For any non-trivial implementation task, dispatch alongside the implementer:

```
Agent(name="implementer", prompt="Implement the auth flow per spec...")
Agent(name="qa-tester", prompt="Write tests for the auth flow.
  Work from the SUCCESS CRITERIA and SPEC — do NOT read the implementation code.
  Your tests verify the OUTCOMES, not the implementation details.
  Share your test file via SendMessage when ready for the implementer to run.")
```

The QA agent writes tests that the implementer must pass. The tests catch the gap
between what the spec says and what the code does — because the tester never saw
the code.

The QA agent must write tests from the success criteria, business outcome,
independent oracle, solution constraints, and invalid solution classes. The QA
agent should not depend on the implementer's chosen code approach.

The QA agent must produce:
1. Behavioral tests for the outcome
2. Positive and negative controls
3. Contract, architecture, or static checks when invalid implementations could
   otherwise pass
4. A statement of which bad implementations the tests reject

### Mutation Challenger Pattern

For non-trivial behavior changes, dispatch a mutation-challenger before
implementation. The mutation challenger does not write production code.

The mutation challenger must:
1. Read the Test Oracle Brief and proposed tests.
2. Invent 2-5 plausible bad implementations.
3. Include the known tempting shortcut.
4. For each bad implementation, answer:
   - Would the current tests/checks fail it?
   - If not, what test/check must be strengthened?
5. Block implementation until the named fragile implementation fails at least
   one behavioral, fixture, contract, architecture, or static check.

Common bad implementation classes:
- Hardcoded generated IDs instead of semantic business keys
- Filtering at the wrong layer
- Testing only an intermediate artifact when the user cares about final output
- Status code correct but persisted state wrong
- Permission check mocked but real endpoint still allows access
- Snapshot updated but interaction/accessibility behavior broken
- Job stops crashing but output is incomplete or duplicated

### Outcome Verifier

After implementation and code review, dispatch an outcome-verifier. The
outcome-verifier verifies the actual result the user cares about, not just test
status or code quality.

Examples:
- Report task: run the report/query and inspect returned rows or metrics
- API task: call the public endpoint and verify state, response, and permissions
- UI task: exercise the user flow, not just component internals
- Data task: verify the final fact/report, not only intermediate models
- Sync job: verify target data is correct, complete, and in the expected location

The outcome-verifier must not accept:
- "Tests pass" as sufficient proof
- "Implementation looks correct"
- "Intermediate model is fixed" when the user cares about downstream output

Tests pass only counts as outcome verification when those tests exercise the
actual desired outcome and reject known fragile implementations.

### When to Pair

- **Always pair** for feature/epic work with behavioral specs
- **Consider pairing** for complex bug fixes where the fix could mask the root cause
- **Skip pairing** for simple chores, config changes, one-liners

## Completeness Critic (the underreach pass)

A review/critique roundtable that *only* dispatches per-lens reviewers and then an
adversarial verify pass has a structural blind spot. The verify pass refutes
**overreach** — claims that exist and are inflated. It is blind to **underreach**
by construction: a true finding that no lens was pointed at is never *generated*,
so there is nothing for the verifier to refute. A real lean violation can slip
every seam between the lenses and be caught only by a human afterward.

The completeness critic closes that gap. It is a **generative** stage, not a
verifying one, and runs as a final agent *after* the per-lens reviewers report but
*before* you call the review done.

**Dispatch it on the same team, blinded to the other reviewers' verdicts** (give it
the artifact and the list of lenses that ran, not their findings — so it reasons
about what they *structurally could not have covered*, not just what they happened
to miss). Its job is three questions:

1. **What is missing?** — list coverage gaps owned by *no* lens that ran. Name the
   gap and which (absent) lens would have owned it. "No lens looked at write-side
   authoring redundancy across the openspec/beads/harness trio" is a gap finding.
2. **What is understated?** — challenge severity calibration **up**, not only down.
   The verify pass argues findings down ("this P1 is really a nit"); the critic
   argues the reverse ("this was filed as a nit but it's a recurring lean
   violation — raise it"). Severity calibration must move in both directions.
3. **What is mis-scoped?** — a finding attached to the wrong layer, or one true
   finding masquerading as the symptom of a deeper one.

**Feed gaps back as a new round.** Each gap the critic surfaces is a *new* finding
with no verdict yet — so it re-enters the loop: dispatch a lens at it, then verify
it adversarially like any other. The critic does not get the last word; it
*restarts* the loop with the findings the first pass could never have produced.
Run the critic until a round surfaces nothing new (loop-until-dry), not once.

```
# After the per-lens roundtable reports:
Agent(
  name="completeness-critic",
  description="Surface coverage gaps and severity under-calibration",
  prompt="You are the completeness critic for the review of <artifact>.
    The lenses that ran were: security, ux, performance. You are NOT given their
    findings — reason about what those three lenses STRUCTURALLY could not cover.
    Answer three questions and SendMessage your findings:
      1. MISSING: gaps owned by no lens that ran. Name the gap + the absent lens.
      2. UNDERSTATED: findings whose severity should be calibrated UP (not just down).
      3. MIS-SCOPED: findings attached to the wrong layer or masking a deeper cause.
    Each gap you name is a NEW finding with no verdict — it will be dispatched to a
    lens and verified. Do not rubber-stamp; if nothing is missing, say so explicitly
    and justify why the lens set was exhaustive for this artifact.
    [CONTINUATION DISCIPLINE block here]"
)
```
