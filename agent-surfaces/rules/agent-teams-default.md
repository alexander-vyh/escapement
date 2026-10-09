---
op: agent-teams-default
slots:
  named_agents:
    claude: |-
      Every dispatched agent MUST have a `name`. This is the only requirement for coordination.
      The session has a single implicit team — all named agents are automatically on it and can
      address each other via `SendMessage({to: name})`.

      (`TeamCreate` and `team_name` are deprecated and ignored by the current Claude Code runtime.)
    codex: |-
      Every spawned agent MUST have a stable `task_name` on `spawn_agent`. This is the only
      requirement for coordination. The spawned agent is told its canonical task name, and the
      lead addresses it with `send_message` (or `followup_task` to give it a new turn), collects
      results with `wait_agent`, and lists the live team with `list_agents`.

      Give every agent the task names of the teammates it reports to, so findings flow by name
      via `send_message` rather than through the lead's memory.
    pi: |-
      Every dispatched child MUST have a stable key: launch it through the `subagent` tool with
      `runs.run("<key>", { agent, task })`, or as a `{ key, agent, task }` item of `runs.all([...])`,
      inside a `workflowScript`. The key is the only requirement for coordination.

      By default a child reaches only the lead, with `contact_supervisor`. The lead relays between
      children by key with `runs.steer("<key>", message)` (or `subagent({ action: "steer", id, message })`
      for a top-level run).
  dispatch_example:
    claude: |-
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
    codex: |-
      ```
      # Spawn named agents — each is addressable by its task_name
      spawn_agent(
        task_name="researcher-1",
        message="Investigate OAuth patterns in the codebase.
          Use send_message to share findings with researcher-2."
      )
      spawn_agent(
        task_name="researcher-2",
        message="Investigate session management patterns.
          Use send_message to share findings with researcher-1."
      )
      # Named agents can send_message each other by task name; the lead collects with wait_agent

      # ❌ WRONG — no task_name at all
      spawn_agent(message="Investigate OAuth patterns...")
      # Fire-and-forget, no coordination possible
      ```
    pi: |-
      ```
      # Dispatch keyed children — each is addressable by its key
      subagent({ workflowScript: `
        const results = await runs.all([
          { key: "researcher-1", agent: "scout", task: "Investigate OAuth patterns in the codebase." },
          { key: "researcher-2", agent: "scout", task: "Investigate session management patterns." }
        ]);
        return results.map(result => result.output);
      ` })
      # The lead relays between keyed children with runs.steer(key, message)

      # ❌ WRONG — opaque keys that name no lane
      runs.all([{ key: "a", agent: "scout", task: "..." }, { key: "b", agent: "scout", task: "..." }])
      # Nobody can tell which lane to steer, resume, or relay to
      ```
  vocab_first:
    claude: |-
      **`vocab`** skill (`/vocab`) for the full protocol. (vocab-first is the one case
      this rule's point-to-point SendMessage doesn't cover: a shared living glossary
      the whole team queries.)
    codex: |-
      **`vocab`** skill (`$vocab`) for the full protocol. (vocab-first is the one case
      this rule's point-to-point `send_message` doesn't cover: a shared living glossary
      the whole team queries.)
    pi: |-
      **`vocab`** skill (`/skill:vocab`) for the full protocol. (vocab-first is the one case
      this rule's point-to-point lead relay doesn't cover: a shared living glossary
      the whole team queries.)
  vocab_table:
    claude: |-
      | "agent team" | 2-5 named agents |
      | "roundtable" | Named agents with persona prompts that argue via SendMessage |
      | "panel of experts" | Named agents with different expertise, share findings via SendMessage |
      | "have them talk to each other" | Named agents using SendMessage — just give each a `name` |
      | "use agents" | Named agents, not inline work |

      **"Roundtable" NEVER means writing simulated dialogue in your output.** It ALWAYS means dispatching real named agents on a team that independently analyze and communicate via SendMessage.
    codex: |-
      | "agent team" | 2-5 named agents |
      | "roundtable" | Named agents with persona prompts that argue via `send_message` |
      | "panel of experts" | Named agents with different expertise, share findings via `send_message` |
      | "have them talk to each other" | Named agents using `send_message` — just give each a `task_name` |
      | "use agents" | Named agents, not inline work |

      **"Roundtable" NEVER means writing simulated dialogue in your output.** It ALWAYS means spawning real named agents that independently analyze and communicate via `send_message`.
    pi: |-
      | "agent team" | 2-5 keyed children |
      | "roundtable" | Keyed children with persona prompts; the lead relays each position to the others with `runs.steer` |
      | "panel of experts" | Keyed children with different expertise; the lead relays findings between them with `runs.steer` |
      | "have them talk to each other" | Keyed children the lead relays between with `runs.steer` — just give each a meaningful key |
      | "use agents" | Keyed children, not inline work |

      **"Roundtable" NEVER means writing simulated dialogue in your output.** It ALWAYS means dispatching real keyed children that independently analyze while the lead relays their positions via `runs.steer`.
  writer_isolation:
    claude: |-
      Two or more agents that will COMMIT means one worktree and branch each —
      one session-injected `escapement-worktree create` transaction per agent or
      `isolation: "worktree"` on dispatch, with the lead merging branches back
      deliberately. Prompt-level "you own these files" lanes are merge-planning notes,
      never the isolation mechanism. This applies to concurrent *sessions* exactly as
      it applies to dispatched agents — full rule: `worktree-discipline.md`.
    codex: |-
      Two or more agents that will COMMIT means one worktree and branch each —
      one `escapement-worktree create` transaction per agent, named in each writer's
      `spawn_agent` task, with the lead merging branches back
      deliberately. Prompt-level "you own these files" lanes are merge-planning notes,
      never the isolation mechanism. This applies to concurrent *sessions* exactly as
      it applies to spawned agents — full rule: `worktree-discipline.md`.
    pi: |-
      Two or more agents that will COMMIT means one worktree and branch each —
      one `escapement-worktree create` transaction per agent or
      `isolation: "worktree"` on the `subagent` call, with the lead merging branches back
      deliberately. Prompt-level "you own these files" lanes are merge-planning notes,
      never the isolation mechanism. This applies to concurrent *sessions* exactly as
      it applies to dispatched children — full rule: `worktree-discipline.md`.
  anonymous_dispatch:
    claude: |-
      - **Dispatching without `name`** — `Agent(prompt="...")` is ALWAYS wrong; anonymous
        agents are unaddressable and cannot coordinate
    codex: |-
      - **Spawning without `task_name`** — an unnamed `spawn_agent` is ALWAYS wrong; anonymous
        agents are unaddressable and cannot coordinate
    pi: |-
      - **Dispatching with opaque keys** — a `runs.run` key like `"a"` or `"1"` is ALWAYS wrong; the
        key is how the lead steers, resumes, and relays to that lane
targets:
  claude: claude/rules/agent-teams-default.md
  codex: plugins/escapement/claude/rules/agent-teams-default.md
  pi: plugins/escapement-pi/claude/rules/agent-teams-default.md
frontmatter:
  claude:
  codex:
  pi:
---

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

{{slot:named_agents}}

<!-- escapement:detail:start -->

### Concrete Example — This Is What Every Dispatch Must Look Like

{{slot:dispatch_example}}


<!-- escapement:detail:end -->
<!-- escapement:detail:start -->

### Shared terminology before a design fan-out (gated)

**Most research does NOT need this.** But before a multi-agent **design** effort
in an **unfamiliar** domain whose terminology encodes a distinction the model's
default framing would get **wrong** (e.g. entitlement vs ownership, queue vs
group) **and** the output is load-bearing — dispatch a single **living
vocab-scout** to establish the team's shared glossary *before* the design agents
fan out, then have them work from (and challenge) that glossary. Load the
{{slot:vocab_first}}

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
{{slot:vocab_table}}


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
The operative directive for each pattern, one line, stays here:

- **Independent Test Agent Pattern** — for any non-trivial implementation, pair a
  `qa-tester` with the `implementer`; the tester writes tests from the SPEC /
  success criteria and NEVER from the code, producing behavioral tests +
  positive/negative controls + a statement of which bad implementations they
  reject. The implementer must pass them.
- **Mutation Challenger Pattern** — before a non-trivial behavior change, dispatch
  a challenger (no production code) that invents 2-5 plausible bad implementations
  including the tempting shortcut, and BLOCKS implementation until the named
  fragile implementation fails at least one behavioral / fixture / contract /
  architecture / static check.
- **Outcome Verifier** — after implementation and review, dispatch a verifier that
  checks the actual user-facing result (run the report/query, call the endpoint,
  exercise the UI flow, verify the data/sync target), NEVER accepting "tests pass"
  or "looks correct" as proof.
- **Completeness Critic** — after the per-lens reviewers report and before
  declaring the review done, dispatch a generative, blinded critic that surfaces
  what is MISSING (gaps no lens owned), UNDERSTATED (severity to calibrate up),
  and MIS-SCOPED within the assigned requirements; classify gaps as causal blockers
  or adjacent discoveries. Apply the round cap below (2 review rounds;
  nonblocking leftovers go to `bd create`).

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

{{slot:writer_isolation}}

## Anti-Patterns

- **Writing simulated persona dialogue instead of dispatching real agents**
{{slot:anonymous_dispatch}}
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
