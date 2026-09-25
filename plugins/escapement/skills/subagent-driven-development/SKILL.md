---
name: "subagent-driven-development"
description: "Use when executing implementation plans with independent tasks in the current session"
---

# Subagent-Driven Development

Execute a plan by dispatching fresh **named team** subagents per task, with two-stage review after each: spec compliance review first, then code quality review.

**Why named agents:** Named subagents can receive follow-up instructions without losing their context. Anonymous subagents are fire-and-forget — if the reviewer finds issues, you have to dispatch an entirely new agent. Named agents allow iterative review loops with the same agent.

Host mechanics used throughout this skill:

- **Codex:** spawn with `spawn_agent` (`task_name` = the agent's name, `agent_type` = its role, `fork_turns: "none"` for a fresh context, `message` = the prompt) and collect with `wait_agent`. Follow up with `followup_task` to the same task name — the agent keeps its context. A subagent asks you questions with `send_message` to `/root`; answer with `send_message` back to its task name.
- **Pi:** spawn through the `subagent` tool, e.g. `subagent({ context: "fresh", workflowScript: "return runs.run('impl-task1', { agent: 'worker', task: TASK_TEXT })" })` with the prompt as the task (`worker` implements, `reviewer` checks, Escapement's `adversarial-reviewer` reviews quality). Follow up with `subagent({ action: "resume", id, message })` on the retained run — `subagent({ action: "children.list" })` shows which runs are resumable — or, inside one workflow, `runs.run(key, { resume: previous.runId, task })`. A subagent asks you questions with `contact_supervisor` (reason `need_decision`); answer with `subagent_supervisor({ action: "reply", replyTo, message })`.

**Core principle:** Fresh named subagent per task + two-stage review (spec then quality) = high quality, fast iteration

## Beads Integration

Named agents and beads are complementary — beads tracks *what* to do, naming enables *how* they coordinate.

- **Project has `.beads/`:** Use `/beads-execution` for the dispatch loop (`bd ready` → claim → dispatch → review → `bd close`). Agents dispatched by beads-execution MUST still have a `name`.
- **No beads:** Use this skill directly. Named agents are the constant.

## When to Use

- Have an implementation plan with mostly independent tasks
- Want to stay in the same session (no context switch)
- Tasks can be executed sequentially with fresh subagents

## The Process

### Per-Task Loop

For each task in the plan:

1. **Dispatch named implementer on the team**
2. **Handle implementer status** (DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED)
3. **Dispatch named spec reviewer on the team**
4. **If issues:** Send fix instructions to implementer (same agent, retains context)
5. **Dispatch named quality reviewer on the team**
6. **If issues:** Send fix instructions to implementer
7. **Mark task complete**

### After all tasks

Dispatch named final-reviewer on the team for entire implementation.

## Dispatching Named Team Subagents

**MANDATORY: Every subagent MUST have a name** — Codex `task_name`, Pi `key`. Without one it cannot be followed up.

### Implementer dispatch:

```
spawn_agent(
  task_name="impl_task1",
  agent_type="default",
  fork_turns="none",
  message="[Full task text from plan]
    [Scene-setting context: where this fits in the overall plan]
    [Constraints, patterns to follow, files to touch]
    Ask questions with send_message to /root.
    Before modifying or recommending any file path, verify it exists by listing or reading it. Never assume a path exists based on convention.
    Begin by making an explicit plan. List the steps you will take, then execute them one by one, checking off each step.
    Follow TDD: write tests first, then implement.
    Report status: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED"
)
```

On Pi, send the same prompt as `runs.run("impl-task1", { agent: "worker", task })`, with "Ask questions with contact_supervisor (reason: need_decision)." in place of the `send_message` line.

### Spec reviewer dispatch:

```
spawn_agent(
  task_name="spec_reviewer_task1",
  agent_type="default",
  fork_turns="none",
  message="Review the implementation by impl_task1 against this spec:
    [Full spec text]
    Before reviewing any file path, verify it exists by listing or reading it. Never assume a path exists based on convention.
    Check: Does the code match the spec exactly?
    - Missing requirements?
    - Extra features not in spec?
    - Incorrect behavior?
    Report: ✅ Spec compliant OR ❌ with a numbered list of specific failures."
)
```

On Pi, send the same prompt as `runs.run("spec-reviewer-task1", { agent: "reviewer", task })`.

### Code quality reviewer dispatch:

Use the `adversarial-reviewer` agent role (Codex `agent_type`, Pi `agent`) for quality review — it is hostile, expert, and personally motivated to find failures.

```
spawn_agent(
  task_name="quality_reviewer_task1",
  agent_type="adversarial-reviewer",
  fork_turns="none",
  message="Review code quality for the commits by impl_task1.
    [Git SHAs or file paths for the relevant changes]
    Before reviewing any file path, verify it exists by listing or reading it. Never assume a path exists based on convention.
    Check: Is the code well-written?
    - Test coverage adequate?
    - Clean, readable code?
    - Following project patterns?
    Report: ✅ Approved OR ❌ with a numbered list of specific issues."
)
```

On Pi, send the same prompt as `runs.run("quality-reviewer-task1", { agent: "adversarial-reviewer", task })`.

### Review loop via follow-ups:

When a reviewer finds issues, send fixes back to the implementer:

```
Codex:
followup_task(
  target="impl_task1",
  message="Spec reviewer found these issues:
    1. Missing progress reporting (spec says 'report every 100 items')
    2. Added --json flag that wasn't requested — remove it
    Fix both and commit."
)

Pi:
subagent({ action: "resume", id: "<impl-task1 run id>", message: "Spec reviewer found these issues:
  1. Missing progress reporting (spec says 'report every 100 items')
  2. Added --json flag that wasn't requested — remove it
  Fix both and commit." })
```

The implementer retains its full context and can fix efficiently.

## Model Selection

Use the least powerful model that can handle each role:

- **Mechanical tasks** (isolated functions, clear specs, 1-2 files): fast model
- **Integration tasks** (multi-file, pattern matching): standard model
- **Architecture and review tasks**: most capable model

## Effort Calibration

Match depth of work to task type. Do not converge on an answer before reaching the expected effort level:
- **Simple lookup / single-file read:** 3-10 tool calls
- **Investigation / multi-file analysis:** 10-20 tool calls
- **Full implementation with tests:** 20-40 tool calls

## Handling Implementer Status

**DONE:** Proceed to spec compliance review.

**DONE_WITH_CONCERNS:** Read concerns. If about correctness or scope, use a follow-up to address. If observations, note and proceed.

**NEEDS_CONTEXT:** Use a follow-up to provide missing context — agent retains full state.

**BLOCKED:** Assess: context problem → send more context. Too hard → dispatch new agent with more capable model. Too large → break into pieces. Plan wrong → escalate to user.

## Example Workflow

```
You: I'm using Subagent-Driven Development to execute this plan.

[Read plan file, extract all tasks]

Task 1: Hook installation script

spawn_agent(task_name="impl_hooks", agent_type="default", fork_turns="none", message="[full task text]")

impl_hooks → /root: "Should hooks install at user or system level?"
You: send_message(target="impl_hooks", message="User level (~/.config/myapp/hooks/)")

impl_hooks: DONE — implemented, 5/5 tests passing, committed

spawn_agent(task_name="spec_review_hooks", agent_type="default", fork_turns="none", message="Review against spec...")
spec_review_hooks: ✅ Spec compliant

spawn_agent(task_name="quality_review_hooks", agent_type="adversarial-reviewer", fork_turns="none", message="Review quality...")
quality_review_hooks: ✅ Approved

[Mark Task 1 complete. If beads: bd close <task-id>]

Task 2: Recovery modes

spawn_agent(task_name="impl_recovery", agent_type="default", fork_turns="none", message="[full task text]")
impl_recovery: DONE — 8/8 tests passing

spawn_agent(task_name="spec_review_recovery", agent_type="default", fork_turns="none", message="Review against spec...")
spec_review_recovery: ❌ Missing progress reporting, extra --json flag

followup_task(target="impl_recovery", message="Fix: remove --json, add progress reporting")
impl_recovery: Fixed, committed

spawn_agent(task_name="spec_review_recovery_2", agent_type="default", fork_turns="none", message="Re-review...")
spec_review_recovery_2: ✅ Spec compliant

spawn_agent(task_name="quality_review_recovery", agent_type="adversarial-reviewer", fork_turns="none", message="Review quality...")
quality_review_recovery: Issue: magic number (100)

followup_task(target="impl_recovery", message="Extract PROGRESS_INTERVAL constant")
impl_recovery: Done, committed

[Mark Task 2 complete]

[After all tasks]
spawn_agent(task_name="final_reviewer", agent_type="adversarial-reviewer", fork_turns="none", message="Final review...")
final_reviewer: All requirements met, ready to merge

Done!
```

The example uses Codex calls. On Pi the loop is identical: each `spawn_agent` becomes `runs.run(key, { agent, task })` in a `subagent` `workflowScript` (`worker` implementers, `reviewer` spec reviewers, `adversarial-reviewer` quality reviewers), each `followup_task` becomes `subagent({ action: "resume", id, message })`, and an implementer's `contact_supervisor` question is answered with `subagent_supervisor({ action: "reply", replyTo, message })`.

## Continuation Discipline

**For the coordinator (you):**

DO NOT STOP after a task completes. Check `More tasks remain?` and KEEP GOING.
If a reviewer finds issues, loop until they're fixed — do not report "issues found"
and stop. If the final reviewer finds problems, dispatch agents to fix them. The
process ends when ALL tasks are done AND the final review passes AND verification
confirms the outcome end-to-end. Anything short of that is not done.

**For every implementer prompt, append this block:**

> **CONTINUATION DISCIPLINE:** DO NOT wind down prematurely. DO NOT summarize
> remaining work and stop. If you find additional problems while implementing, FIX
> THEM. If a test fails, debug and fix it — do not report the failure and stop. If
> you hit an obstacle, investigate and work around it. You are done when your
> implementation works end-to-end, tests pass, and you've self-reviewed. "I made
> good progress" is not DONE. "Tests pass and the feature works" is DONE.

**For every reviewer prompt, append this block:**

> **CONTINUATION DISCIPLINE:** DO NOT rubber-stamp incomplete work. Read the ACTUAL
> code, not just the report. If you find issues, report ALL of them — do not stop
> after finding the first one. Your job is complete when you have verified every
> requirement against the actual implementation code.

## Red Flags

**Never:**
- Dispatch agents without `name` (they're anonymous and unaddressable)
- Start implementation on main/master without explicit user consent
- Skip reviews (spec compliance OR code quality)
- Proceed with unfixed issues
- Dispatch multiple implementation subagents in parallel (conflicts)
- Skip scene-setting context
- Accept "close enough" on spec compliance
- **Start code quality review before spec compliance is ✅**
- **Stop after partial completion** — all tasks must be done, not just some
- **Summarize remaining work instead of doing it** — that is premature wind-down

## Integration

**Before starting:**
- Have a plan. For new features, use `/discovery` to produce a design doc and walking skeleton tasks. For bugs and chores, a task list or notes are sufficient.
- Work on a feature branch, not main: `git checkout -b <branch-name>`

**Final code review:**
- After all tasks pass, run a diff-level review pass (Codex: `/review`), or dispatch an `adversarial-reviewer` agent against the branch as the final gate before merge.

**Merging:**
- Push the branch: `git push -u origin <branch-name>`
- Open a PR: `gh pr create --fill`
- Merge when CI passes and review is clean.

**With beads:**
- Use `/beads-execution` which wraps this skill with `bd` status tracking. Named agents are still required.
