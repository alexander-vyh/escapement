---
name: "dispatching-parallel-agents"
description: "Use when facing 2+ independent tasks that can be worked on without shared state or sequential dependencies"
---

# Dispatching Parallel Agents

This skill provides named-agent dispatch for parallel work. Every agent MUST have a stable name so it can be addressed while it works and after it reports.

Host mechanics used throughout this skill:

- **Codex:** spawn with `spawn_agent` — `task_name` is the agent's name, `agent_type` a role (`default`, or Escapement's `adversarial-reviewer` / `test-quality-reviewer`), `fork_turns: "none"` so it does not inherit this conversation, `message` the prompt. Every agent is addressable by task name (`/root/<task_name>`) and spawned agents can message each other directly: `send_message` passes a message to a running agent without starting a turn, `followup_task` gives an existing agent a new task and starts a turn. Collect results with `wait_agent` (prefer long waits), inspect the team with `list_agents`, stop an agent with `interrupt_agent`.
- **Pi:** spawn through the `subagent` tool's `workflowScript` — `runs.all([{ key, agent, task }, ...])` for a parallel batch, `runs.run(key, { agent, task })` for one. The `key` is the agent's name; `agent` is a Pi agent (`worker`, `reviewer`, `scout`, `researcher`, `oracle`, or Escapement's `adversarial-reviewer` / `test-quality-reviewer`). Pass `context: "fresh"` so children do not inherit this conversation. Children cannot message each other: a child reaches you with `contact_supervisor` (answer with `subagent_supervisor({ action: "reply", replyTo, message })`), and you relay to a running sibling with `runs.steer(key, message)` inside the script or `subagent({ action: "steer", id, message })`. Follow up with a finished child through `subagent({ action: "resume", id, message })` (`subagent({ action: "children.list" })` shows which runs are resumable).

---

## Overview

You delegate tasks to specialized **named** agents on a **team**. By precisely crafting their instructions and context, you ensure they stay focused and succeed at their task. They should never inherit your session's context or history — you construct exactly what they need.

**Core principle:** Dispatch one **named** agent per independent problem domain. They work concurrently and communicate via messages (relayed through you on Pi).

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

**MANDATORY: Every agent MUST have a name** — Codex `task_name`, Pi `key`. An anonymous agent cannot be messaged, followed up, or told apart in the results.

Codex:

```
spawn_agent(
  task_name="abort_fixer",
  agent_type="default",
  fork_turns="none",
  message="Fix the 3 failing tests in agent-tool-abort.test.ts. [details...]
    If your fix affects batch_fixer's or race_fixer's domain, send_message them."
)

spawn_agent(task_name="batch_fixer", agent_type="default", fork_turns="none",
  message="Fix the 2 failing tests in batch-completion-behavior.test.ts. [details...]
    If your fix affects abort_fixer's or race_fixer's domain, send_message them.")
spawn_agent(task_name="race_fixer", agent_type="default", fork_turns="none",
  message="Fix the 1 failing test in tool-approval-race-conditions.test.ts. [details...]
    If your fix affects abort_fixer's or batch_fixer's domain, send_message them.")
```

Then `wait_agent` for their results. All three can `send_message` each other by task name.

Pi:

```
subagent({ context: "fresh", workflowScript: `
  return runs.all([
    { key: "abort-fixer", agent: "worker", task: "Fix the 3 failing tests in agent-tool-abort.test.ts. [details...] If your fix affects batch-fixer's or race-fixer's domain, report it with contact_supervisor (reason: progress_update)." },
    { key: "batch-fixer", agent: "worker", task: "Fix the 2 failing tests in batch-completion-behavior.test.ts. [details...] If your fix affects abort-fixer's or race-fixer's domain, report it with contact_supervisor (reason: progress_update)." },
    { key: "race-fixer", agent: "worker", task: "Fix the 1 failing test in tool-approval-race-conditions.test.ts. [details...] If your fix affects abort-fixer's or batch-fixer's domain, report it with contact_supervisor (reason: progress_update)." }
  ]);
` })
```

On Pi the fixers report cross-domain effects to you and you relay each one to the affected sibling with `steer`.

### 4. Review and Integrate

When agents return:
- Read each summary
- Verify fixes don't conflict
- Run full test suite
- Integrate all changes
- If in a beads project: `bd close <task-id>` for each completed task
- Stop any agent still running when done (Codex `interrupt_agent`; Pi `subagent({ action: "stop", id })` for a live async run)

## Roundtable Pattern

A "roundtable" is a specific use of team agents where expert personas **argue and critique each other's positions** via messages (relayed through you on Pi).

Codex — the reviewers debate each other directly:

```
spawn_agent(
  task_name="security_reviewer",
  agent_type="default",
  fork_turns="none",
  message="Review the auth middleware changes from a security perspective.
    After your initial review, send_message your findings to ux_reviewer and perf_reviewer.
    Read and respond to the other reviewers' findings.
    Push back if you disagree — this is a debate, not a rubber stamp."
)

# Same message shape, own perspective, the other two reviewers as peers:
spawn_agent(task_name="ux_reviewer", agent_type="default", fork_turns="none",
  message="Review ... from a UX perspective. ... send_message your findings to security_reviewer and perf_reviewer. ...")
spawn_agent(task_name="perf_reviewer", agent_type="default", fork_turns="none",
  message="Review ... from a performance perspective. ... send_message your findings to security_reviewer and ux_reviewer. ...")
```

Pi — children cannot message each other, so run the debate as rounds in one workflow: independent reviews first, then each reviewer answers the others' findings.

```
subagent({ context: "fresh", workflowScript: `
  const lenses = ["security", "ux", "performance"];
  const first = await runs.all(lenses.map((lens) => ({
    key: lens + "-reviewer",
    agent: "reviewer",
    task: "Review the auth middleware changes from a " + lens + " perspective. Do not edit files."
  })));
  return runs.all(lenses.map((lens, i) => ({
    key: lens + "-rebuttal",
    agent: "reviewer",
    task: "You are the " + lens + " reviewer. Your review:\n" + first[i].output +
      "\n\nThe other reviewers found:\n" +
      first.filter((_, j) => j !== i).map((r) => r.output).join("\n\n") +
      "\n\nRead and respond to their findings. Push back if you disagree — this is a debate, not a rubber stamp."
  })));
` })
```

## Agent Prompt Structure

Good agent prompts are:
1. **Named** — a `task_name` (Codex) or `key` (Pi) on every spawn
2. **Focused** — One clear problem domain
3. **Self-contained** — All context needed to understand the problem
4. **Peer-aware** — Lists other agents' names so they can coordinate via messages (relayed through you on Pi)
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
with its read and search tools. Pre-quoted code is pre-interpreted code — interpretation is
exactly what you're delegating. Keep quoting for context the agent genuinely
cannot discover on its own (spec ID, external ticket, error message text).

**Sanity check.** Before dispatching, ask yourself: if a teammate read this
exact prompt with no other context, would the agent's conclusion be
predetermined by your wording? If yes, rewrite.

Reviewer agents whose personas already include a Blinding Discipline section
(e.g. `adversarial-reviewer`) will actively ignore priming in the prompt,
but that is a second line of defense. The first line is you.

## Common Mistakes

**❌ No name:** a spawn without a `task_name` (Codex) or `key` (Pi) — anonymous, unaddressable
**✅ Named:** `spawn_agent(task_name="test_fixer", ...)` / `{ key: "test-fixer", agent: "worker", task: "Fix tests" }` — addressable, can coordinate

**❌ Simulated roundtable:** Writing persona dialogue in your own output
**✅ Real roundtable:** Named agents that independently analyze and argue via messages (relayed through you on Pi)

## Vocabulary

> Canonical, principle-anchored definitions live in
> [`docs/VOCABULARY.md`](../../../docs/VOCABULARY.md). Local quick-reference below.

| User says | Means |
|-----------|-------|
| "agent team" | 2+ named agents |
| "roundtable" | Named agents arguing via messages (relayed through you on Pi) |
| "panel of experts" | Named agents with different persona prompts |
| "have them talk to each other" | Named agents using messages (relayed through you on Pi) |

**"Roundtable" NEVER means writing simulated dialogue in your output.** It ALWAYS means real named agents that independently analyze and communicate via messages (relayed through you on Pi).

## Assignment contract

Use agents regularly for independent work, research, testing, and review.
Every child receives its assigned outcome before dispatch. State the scope and
allowed effects: repositories, evidence, file ownership, commands, and writes.
Pass the existing approved design and task/Jira reference, when present. Ordinary
verification and mandatory commit hooks are included in a writer assignment;
do not prohibit them and then require a commit. Workers return missing context
to the lead rather than starting another preparation or agent-dispatch workflow.
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

## Continuation Discipline for Dispatched Agents

**Every agent prompt MUST include this block** (copy verbatim into the prompt):

> **CONTINUATION DISCIPLINE:** DO NOT wind down prematurely. DO NOT summarize
> remaining work and stop. Reviewers report and recheck; they do not repair or implement.
> If a problem stands between you and your assigned
> outcome, repair it only within your assigned scope and allowed effects. Anything beyond that outcome — other beads, the rest of the
> epic, adjacent bugs or cleanup — is not yours: report it to your lead (or
> `bd create` it) and do not fix it. If you hit an obstacle, investigate and work
> around it — do not report it as a reason to stop. You are done when the OUTCOME
> meets your assignment completion criteria and is handed off. Verify the assigned
> result against its oracle; passing tests alone does not establish the parent outcome.

**For the main agent coordinating the team:**

Deliver the assigned result after collecting agent findings and verifying its
completion criteria. Route causal blockers to an implementer only within the
parent's delegated authority. Record adjacent findings without dispatching repair.
Optional unavailable evidence is unknown; it does not authorize a rescue scan or
prevent delivering supported findings. Continue independent authorized lanes.

## Verification

After agents return:
1. Review the returned evidence against each assignment's completion criteria.
2. Check ownership conflicts before integrating writes.
3. Run checks relevant to the delegated outcome and independently verify it.
4. Route failing checks only when they causally block that outcome; report unrelated failures.
5. **Shut down the team** — stop any agent still running (Codex `interrupt_agent`; Pi `subagent({ action: "stop", id })`)

## Agent Pairing for Quality

When useful, pair implementation agents with independent QA agents that
work from the success criteria or spec — NOT from the code. The always-on
`agent-teams-default.md` rule carries one-line summaries of these patterns and
points here for the full write-ups. The fourth pattern — the **Completeness
Critic** — has its own section immediately below.

### Independent Test Agent Pattern

Use this pattern when an independent test writer adds evidence not already
provided by the assigned tests or approved design. It is not a mandatory round:

Codex:

```
spawn_agent(task_name="implementer", agent_type="default", fork_turns="none",
  message="Implement the auth flow per spec...")
spawn_agent(task_name="qa_tester", agent_type="default", fork_turns="none",
  message="Write tests for the auth flow.
  Work from the SUCCESS CRITERIA and SPEC — do NOT read the implementation code.
  Your tests verify the OUTCOMES, not the implementation details.
  send_message your test file path to implementer when ready for it to run.")
```

Pi (the tester's file reaches the implementer through a resumed turn):

```
subagent({ context: "fresh", workflowScript: `
  const [impl, qa] = await runs.all([
    { key: "implementer", agent: "worker", task: "Implement the auth flow per spec..." },
    { key: "qa-tester", agent: "worker", task: "Write tests for the auth flow. Work from the SUCCESS CRITERIA and SPEC — do NOT read the implementation code. Your tests verify the OUTCOMES, not the implementation details. Return the test file path." }
  ]);
  return runs.run("implementer-verify", { resume: impl.runId, task: "Run the QA tests at " + qa.output + " and fix the implementation until they pass." });
` })
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

A mutation challenger can investigate a specific unresolved weakness in an
oracle. Existing discriminating controls satisfy this prerequisite; do not
commission a separate review merely because implementation is starting.
The mutation challenger does not write production code.

The mutation challenger must:
1. Read the Test Oracle Brief and proposed tests.
2. Invent 2-5 plausible bad implementations.
3. Include the known tempting shortcut.
4. For each bad implementation, answer:
   - Would the current tests/checks fail it?
   - If not, what test/check must be strengthened?
5. Return concrete missing controls to the lead. Block only the implementation
   whose correctness depends on that unresolved finding.

Common bad implementation classes:
- Hardcoded generated IDs instead of semantic business keys
- Filtering at the wrong layer
- Testing only an intermediate artifact when the user cares about final output
- Status code correct but persisted state wrong
- Permission check mocked but real endpoint still allows access
- Snapshot updated but interaction/accessibility behavior broken
- Job stops crashing but output is incomplete or duplicated

### Outcome Verifier

Verify the actual result the user cares about after implementation. The lead
may do this directly or delegate a bounded outcome-verifier assignment. Reuse
accepted evidence for unchanged inputs; another agent is not a prerequisite.

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

**Classify gaps within the assignment.** The critic reports evidence and does not
implement or dispatch repairs. Causal blockers go to the assigned implementer;
adjacent findings are recorded. Re-review uses the round cap: 2 review rounds,
round two checks repairs rather than opening a new sweep; nonblocking leftovers
use `bd create`.

```
# After the per-lens roundtable reports (Codex shown; on Pi run the same prompt as
# runs.run("completeness-critic", { agent: "reviewer", task }) with context: "fresh"):
spawn_agent(
  task_name="completeness_critic",
  agent_type="default",
  fork_turns="none",
  message="You are the completeness critic for the review of <artifact>.
    The lenses that ran were: security, ux, performance. You are NOT given their
    findings — reason about what those three lenses STRUCTURALLY could not cover.
    Answer three questions and report your findings:
      1. MISSING: gaps owned by no lens that ran. Name the gap + the absent lens.
      2. UNDERSTATED: findings whose severity should be calibrated UP (not just down).
      3. MIS-SCOPED: findings attached to the wrong layer or masking a deeper cause.
    Classify each gap against the assigned outcome. Report causal blockers and
    adjacent findings separately; do not implement repairs or start another review. Do not rubber-stamp; if nothing is missing, say so explicitly
    and justify why the lens set was exhaustive for this artifact.
    [CONTINUATION DISCIPLINE block here]"
)
```
