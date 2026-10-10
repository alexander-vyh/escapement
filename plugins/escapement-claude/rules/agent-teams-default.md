# Agent Teams — Global Rule

## When to Dispatch

**Use agents regularly for bounded assignments.** Dispatch independent work,
research, testing, and review when those roles help deliver the requested outcome.
Choose inline execution for small self-contained actions. Neither choice widens
the question or grants authority beyond the assignment.

## Assignment contract

Use agents regularly for independent work, research, testing, and review.
Every child receives its assigned outcome before dispatch. State the scope and
allowed effects: repositories, evidence, file ownership, commands, and writes.
State completion criteria and the handoff to the lead; a completed review or
research assignment returns findings rather than delivering the parent's build.
Reviewers report findings and recheck assigned repairs; they do not repair or
implement without a new assignment. Implementers may fix what causally blocks
their assigned outcome only within the authorized scope and allowed effects.
For adjacent findings, report them and do not fix them. A parent applies the
same boundary before assigning repairs; a child's discovery adds no authority.
Use `bd ready` to select only authorized tasks; readiness is not delegated scope.
Unknown optional evidence does not block a useful answer. Return available
findings and the precise uncertainty; the parent persists returned payloads
without recomputing them merely because the child lacked file tools.

## Always Use Named Agents

Every dispatched agent MUST have a `name`. This is the only requirement for coordination.
The session has a single implicit team — all named agents are automatically on it and can
address each other via `SendMessage({to: name})`.

(`TeamCreate` and `team_name` are deprecated and ignored by the current Claude Code runtime.)

<!-- escapement:detail:start -->

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


<!-- escapement:detail:end -->
<!-- escapement:detail:start -->

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


<!-- escapement:detail:end -->
### Works With Beads

Named agents and beads are complementary. Beads tracks *what* to do (`bd ready`, `bd close`), named agents handle *how* they coordinate while doing it. When dispatching agents for beads-tracked work, give each agent a `name` — beads adds tracking, naming enables coordination.

## Causal Scope And Action-Local Continuation

Team capacity serves the delegated outcome, not every issue an agent happens to find.
Implementers own and repair work that **causally blocks the delegated outcome** when it remains
inside the delegated repository, audience, privilege, effect, and ownership boundaries.
Record **adjacent discoveries** separately; do not dispatch execution for them or suspend
the active outcome to solicit a scope expansion.

When one lane reaches an unresolved consequential choice, preserve that dependency and
keep other authorized lanes running. A blocked agent is not a blocked team. Escalate
only the narrow decision after all independent authorized work has continued as far as
it can.

## Agent Pairing for Quality

When dispatching implementation agents, consider pairing them with independent
QA agents that work from the success criteria or spec — NOT from the code.

The full QA-pattern catalog — with dispatch templates and worked examples — lives
in the **`dispatching-parallel-agents` skill**; load it when you actually pair.
Use these patterns for a concrete evidence gap, not as mandatory preparation
rounds. Reuse the approved design, existing controls, and accepted review evidence.
The lead can verify directly or delegate a bounded assignment.

- **Independent Test Agent** — when independent test writing helps, give the tester
  the spec and success criteria, including positive and negative controls.
- **Mutation Challenger** — when a plausible bad implementation is not already
  rejected by an existing check, ask a challenger to identify that missing check.
  Block only the implementation that depends on the unresolved oracle.
- **Outcome Verifier** — verify the actual user-facing result; delegate this when
  independent verification adds evidence. Passing tests alone is not that result.
- **Completeness Critic** — use a bounded critic for an unresolved coverage gap,
  rather than automatically adding another review after other reviewers finish.
  Classify findings as causal blockers or adjacent discoveries.

Include ordinary verification and mandatory commit hooks in writer assignments,
along with existing design and task/Jira context. A delegated worker returns a
missing-context question to its supervisor instead of launching more agents.

See the `dispatching-parallel-agents` skill for the full write-ups, the bad-
implementation-class checklist, and the dispatch templates.

### Review Round Cap

Every review→repair pairing runs at most 2 review rounds: round 1 reviews,
repair fixes, round 2 checks those fixes and does not start a fresh sweep.
After round 2, each remaining finding that does not block the assigned outcome is recorded with
`bd create` and report it, not another repair round. Exception: a finding that
causally blocks the delegated outcome gets one more repair round; if it is still
open after that, escalate it as the blocker. A lane that has spent its rounds
reports; it does not re-dispatch itself or its partner.

### When to Pair

- **Always pair** for feature/epic work with behavioral specs
- **Consider pairing** for complex bug fixes where the fix could mask the root cause
- **Skip pairing** for simple chores, config changes, one-liners

<!-- escapement:detail:start -->
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


<!-- escapement:detail:end -->
## Writer Isolation

Two or more agents that will COMMIT means one worktree and branch each —
one session-injected `escapement-worktree create` transaction per agent or
`isolation: "worktree"` on dispatch, with the lead merging branches back
deliberately. Prompt-level "you own these files" lanes are merge-planning notes,
never the isolation mechanism. This applies to concurrent *sessions* exactly as
it applies to dispatched agents — full rule: `worktree-discipline.md`.

## Anti-Patterns

- **Writing simulated persona dialogue instead of dispatching real agents**
- **Dispatching without `name`** — `Agent(prompt="...")` is ALWAYS wrong; anonymous
  agents are unaddressable and cannot coordinate
- **Winding down prematurely** — summarizing remaining work instead of doing it

## Continuation Discipline

`outcome-ownership.md` governs when you may stop, and it binds the lead and every
subagent equally. Two additions specific to teams:

- **A blocked agent is not a blocked team.** Escalate the narrow consequential choice and
  keep every independent authorized lane running.
- **Subagents do not inherit this rule.** Put it in their prompts (block below).

### For Subagents (Include in Every Agent Prompt)

> **CONTINUATION DISCIPLINE:** Do not wind down prematurely. Do not summarize remaining
> work and stop. Reviewers report and recheck; they do not repair or implement.
> As an implementer, repair what blocks your assigned outcome only within your scope and allowed effects.
> Anything beyond that outcome — other beads, the rest of the epic, adjacent bugs or
> cleanup — is not yours: report it to your lead (or `bd create` it) and do not fix it.
> If you hit an obstacle, investigate and work around it — that is not a reason to stop.
> You are done when your assignment completion criteria are met and handed off, not when you have made an attempt. "Maximum
> Steps Reached" is not acceptable unless you have genuinely exhausted every available
> action. Review→repair pairings stop at 2 review rounds: after that, file each
> remaining non-blocking finding with `bd create` instead of another repair round. If
> one action needs an unresolved consequential choice, continue every independent
> authorized lane before escalating that narrow dependency.
