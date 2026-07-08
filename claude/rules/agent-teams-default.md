# Agent Teams as Default — Global Rule

## Default to Agents

For any task beyond a single quick action, dispatch agents. This includes research, exploration, implementation, debugging, code review, investigation — anything that involves multiple steps or could benefit from parallelism.

A single file read, one search, or a small edit is fine inline. Everything else should go to agents.

## Always Use Named Agents

Every dispatched agent MUST have a `name`. This is the only requirement for coordination.
The session has a single implicit team — all named agents are automatically on it and can
address each other via `SendMessage({to: name})`.

(`TeamCreate` and `team_name` are deprecated and ignored by the current Claude Code runtime.)

### Concrete Example — This Is What Every Dispatch Must Look Like

```
# Dispatch named agents — they are automatically on the implicit team
Agent(
  name="researcher-1",
  description="Research auth patterns",
  prompt="Investigate OAuth patterns in the codebase.
    Use SendMessage to share findings with researcher-2."
)
Agent(
  name="researcher-2",
  description="Research session handling",
  prompt="Investigate session management patterns.
    Use SendMessage to share findings with researcher-1."
)
# Named agents can SendMessage to each other by name

# ❌ WRONG — no name at all
Agent(prompt="Investigate OAuth patterns...")
# Fire-and-forget, no coordination possible
```

### Shared terminology before a design fan-out (gated)

**Most research does NOT need this.** But before a multi-agent **design** effort
in an **unfamiliar** domain whose terminology encodes a distinction the model's
default framing would get **wrong** (e.g. entitlement vs ownership, queue vs
group) **and** the output is load-bearing — dispatch a single **living
vocab-scout** to establish the team's shared glossary *before* the design agents
fan out, then have them work from (and challenge) that glossary. Load the
**`vocab`** skill (`/vocab`) for the full protocol. (vocab-first is the one case
this rule's point-to-point SendMessage doesn't cover: a shared living glossary
the whole team queries.)

**Skip** for familiar domains, codebase/org-internal questions, urgent one-fact
lookups, or topics with no external literature. Self-test: if you can't name the
specific wrong prior the field's vocabulary would correct, don't run it. Opt-in
guidance, not a gate.

### Vocabulary — What the User Means

> Canonical definitions for these and all cross-system terms live in
> [`docs/VOCABULARY.md`](../../docs/VOCABULARY.md). The table below is the local
> quick-reference; if the two disagree, the glossary wins.

| User says | What to do |
|-----------|-----------|
| "agent team" | 2-5 named agents |
| "roundtable" | Named agents with persona prompts that argue via SendMessage |
| "panel of experts" | Named agents with different expertise, share findings via SendMessage |
| "have them talk to each other" | Named agents using SendMessage — just give each a `name` |
| "use agents" | Named agents, not inline work |

**"Roundtable" NEVER means writing simulated dialogue in your output.** It ALWAYS means dispatching real named agents on a team that independently analyze and communicate via SendMessage.

### Works With Beads

Named agents and beads are complementary. Beads tracks *what* to do (`bd ready`, `bd close`), named agents handle *how* they coordinate while doing it. When dispatching agents for beads-tracked work, give each agent a `name` — beads adds tracking, naming enables coordination.

## Agent Pairing for Quality

When dispatching implementation agents, consider pairing them with independent
QA agents that work from the success criteria or spec — NOT from the code.

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

### Completeness Critic

The Mutation Challenger and the adversarial review pass both attack **overreach**:
they refute findings that exist and are inflated. They are blind to **underreach**
by construction — a true finding that no reviewer lens was pointed at is never
generated, so there is nothing to refute or mutate. A real defect can slip every
seam between the lenses and be caught only by a human afterward. (This is not
hypothetical: the 2026-05-28 critique's verify phase refuted five inflated claims
but never surfaced the write-side triplicate-authoring lean violation — no lens
owned it.)

After the per-lens reviewers report — and before declaring the review done —
dispatch a **completeness-critic** agent. Unlike the other QA agents it is
**generative, not verifying**. Brief it blinded to the other reviewers' verdicts
(give it the artifact and the *list of lenses that ran*, not their findings) so it
reasons about what those lenses structurally could not cover. It must answer:

1. **What is missing?** Coverage gaps owned by *no* lens that ran. Name the gap and
   the absent lens that would have owned it.
2. **What is understated?** Findings whose severity should be calibrated **up**.
   Severity calibration is bidirectional — the verify pass argues findings down, the
   critic argues the under-rated ones up. A recurring nit may be a systemic
   violation.
3. **What is mis-scoped?** A finding attached to the wrong layer, or a symptom
   standing in for a deeper cause.

The critic does not get the last word — it **restarts the loop**. Each gap it names
is a new finding with no verdict, so it re-enters the pipeline: dispatch a lens at
it, then verify it adversarially like any other finding. Run the critic
**loop-until-dry** (repeat until a round surfaces nothing new), not once. If the
critic finds nothing, it must justify *why the lens set was exhaustive for this
artifact* — "nothing missing" without that justification is a rubber stamp.

### When to Pair

- **Always pair** for feature/epic work with behavioral specs
- **Consider pairing** for complex bug fixes where the fix could mask the root cause
- **Skip pairing** for simple chores, config changes, one-liners

### Subtask Parallelism

Agents aren't just for separate tasks. Within a single task, dispatch parallel
agents for:
- **Research + implementation** — one investigates the codebase, one drafts the code
- **Implementation + testing** — one codes, one writes tests from the spec
- **Multiple approaches** — two agents try different solutions, compare results
- **Ongoing verification** — a background agent runs tests continuously as code changes

### Aggressive Decomposition

If a task takes more than one session or produces more than ~200 lines of changes,
it should have been decomposed further. Break work into pieces small enough that
each agent can complete its piece independently. Smaller tasks = more parallelism =
faster delivery = easier verification.

## Writer Isolation

Two or more agents that will COMMIT means one worktree and branch each —
`bd worktree create` per agent or `isolation: "worktree"` on dispatch, with the
lead merging branches back deliberately. Prompt-level "you own these files"
lanes are merge-planning notes, never the isolation mechanism. This applies to
concurrent *sessions* exactly as it applies to dispatched agents — full rule:
`worktree-discipline.md`.

## Anti-Patterns

- Sequential inline web searches instead of parallel search agents
- Reading 10 files one by one instead of dispatching explore agents
- Doing all investigation yourself instead of dispatching a team
- Using anonymous agents that can't talk to each other
- **Writing simulated persona dialogue in your output instead of dispatching real agents**
- **Dispatching agents without `name`** — they are anonymous and unaddressable
- **Using `Agent(prompt="...")` without `name`** — this is ALWAYS wrong
- **Winding down prematurely** — summarizing remaining work instead of doing it
- **Declaring "done" without verification** — reporting completion without running the actual test/command/workflow

## Continuation Discipline

Agents — both the main thread and subagents — tend to prematurely wind down. This
section exists to prevent that failure mode. These rules are NON-NEGOTIABLE.

### For the Main Agent (You)

**DO NOT STOP until the outcome is verified end-to-end.** Finding a problem is not
finishing — FIXING the problem is finishing. Summarizing remaining work is not
finishing — DOING the remaining work is finishing.

**If you discover additional work during execution, KEEP GOING.** Create new tasks,
dispatch new agents, fix what you find. Never list remaining work and stop. The only
acceptable response to discovering more work is to do that work or dispatch agents
to do it.

**If you hit an obstacle, work around it or escalate to the user — do NOT treat it
as a stopping point.** An obstacle is a problem to solve, not permission to quit.

**Declaring "done" without running verification is FAILURE.** Run the actual
command/test/workflow. See the actual output. Confirm the actual result. "I believe
this works" is not verification. "The tests pass" is verification. "The output
matches expected" is verification.

### Pre-Completion Checklist

Before declaring ANY task complete, mentally run this checklist. If any answer
triggers more work — do that work before stopping.

1. **Did I dispatch all agents that could work in parallel?** If independent work
   remains, dispatch agents for it NOW.
2. **Are there follow-up tasks I found during execution that I haven't addressed?**
   If yes, address them or create tracked tasks for them.
3. **Did I verify the outcome end-to-end?** Not just "my change compiles" — did I
   run the actual workflow and confirm the actual result?
4. **Could I dispatch a review/QA agent to independently verify?** If the work is
   non-trivial, dispatch one.
5. **Am I stopping because the work is DONE, or because I'm tired of working on it?**
   Be honest. If you're stopping because it feels like enough, you're wrong — keep going.

### For Subagents (Include in Every Agent Prompt)

When dispatching agents, include this language in their prompts:

> **CONTINUATION DISCIPLINE:** DO NOT wind down prematurely. DO NOT summarize
> remaining work and stop. If you find additional problems during your work, FIX
> THEM. If you hit an obstacle, investigate and work around it — do not report it
> as a reason to stop. You are done when the OUTCOME is verified, not when you've
> made an attempt. "Maximum Steps Reached" is not an acceptable reason to stop
> unless you have genuinely exhausted every available action.
