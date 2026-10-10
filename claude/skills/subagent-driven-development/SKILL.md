---
name: "subagent-driven-development"
description: "Use when executing implementation plans with independent tasks in the current session"
---

# Subagent-Driven Development

Execute the assigned plan with bounded named agents. Verify spec compliance
and code quality together when one review can cover both; separate review
rounds are not mandatory.

**Why named agents:** Named subagents can receive follow-up instructions via `SendMessage` without losing their context. Anonymous subagents are fire-and-forget — if the reviewer finds issues, you have to dispatch an entirely new agent. Named agents allow iterative review loops with the same agent.

**Core principle:** Reuse the approved plan, dispatch concrete assignments,
and verify their results without repeating satisfied preparation.

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

## Beads Integration

Named agents and beads are complementary — beads tracks *what* to do, naming enables *how* they coordinate.

- **Project has `.beads/`:** Track the assigned work with `bd`. Invoke `/beads-execution` only when the user explicitly asks to execute a tracked task; repository presence alone does not start that workflow.
- **No beads:** Use this skill directly. Named agents are the constant.

## When to Use

- Have an implementation plan with mostly independent tasks
- Want to stay in the same session (no context switch)
- Tasks can be executed sequentially with fresh subagents

## The Process

### Per-Task Loop

For each task in the plan:

1. **Dispatch a named implementer** with the existing design, task context,
   allowed verification and commit hooks, and completion criteria.
2. **Handle implementer status** (DONE / DONE_WITH_CONCERNS / NEEDS_CONTEXT / BLOCKED).
3. **Verify spec compliance and code quality** directly or with one bounded
   reviewer. Reuse accepted evidence; separate reviewers are optional.
4. **Repair in-scope causal blockers** using the same implementer and context.
5. **Mark the task complete** when its assigned outcome is independently verified.

### After all assigned tasks

Verify the integrated outcome. Dispatch a final reviewer only for an unresolved
review gap; accepted task evidence does not require another review round.

### Implementer dispatch:

```
Agent(
  name="impl-task1",
  description="Implement hook installation script",
  prompt="[Assigned outcome and task text from the delegated plan]
    [Scope and allowed effects: repository, owned files, commands and permitted writes]
    [Completion criteria and evidence handoff to the lead]
    [Scene-setting context: where this fits in the overall plan]
    [Constraints, patterns to follow, files to touch]
    Use SendMessage to ask questions.
    Before modifying or recommending any file path, verify it exists with Glob or Read. Never assume a path exists based on convention.
    Begin by making an explicit plan. List the steps you will take, then execute them one by one, checking off each step.
    Follow TDD: write tests first, then implement.
    Report status: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED"
)
```

### Spec reviewer dispatch:

```
Agent(
  name="spec-reviewer-task1",
  description="Review spec compliance for task 1",
  prompt="Review the implementation by impl-task1 against this spec:
    [Assigned task requirements and evidence; scope: read-only checks, no writes]
    [Completion: report requirement evidence and hand off findings; no repairs]
    Before reviewing any file path, verify it exists with Glob or Read. Never assume a path exists based on convention.
    Check: Does the code match the spec exactly?
    - Missing requirements?
    - Extra features not in spec?
    - Incorrect behavior?
    Report: ✅ Spec compliant OR ❌ with a numbered list of specific failures."
)
```

### Code quality reviewer dispatch:

Use the `adversarial-reviewer` agent type for quality review — it is hostile, expert, and personally motivated to find failures.

```
Agent(
  name="quality-reviewer-task1",
  subagent_type="adversarial-reviewer",
  description="Review code quality for task 1",
  prompt="Review code quality for the commits by impl-task1.
    [Assigned outcome, relevant Git SHAs/files, scope: read-only checks, no writes]
    [Completion: report evidence and separate causal blockers from adjacent findings]
    Before reviewing any file path, verify it exists with Glob or Read. Never assume a path exists based on convention.
    Check: Is the code well-written?
    - Test coverage adequate?
    - Clean, readable code?
    - Following project patterns?
    Report: ✅ Approved OR ❌ with a numbered list of specific issues."
)
```

### Review loop via SendMessage:

When a reviewer reports in-scope causal blockers, send fixes back to the implementer:

```
SendMessage(
  to="impl-task1",
  message="Spec reviewer found these issues:
    1. Missing progress reporting (spec says 'report every 100 items')
    2. Added --json flag that wasn't requested — remove it
    Fix both and commit."
)
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

## Assignment handoff

Pass the existing design and task/Jira reference to each writer. Ordinary
verification and mandatory commit hooks are authorized within the assignment.
Do not require a commit while prohibiting its hooks. Workers return context gaps
to the lead and do not launch another preparation workflow.

## Handling Implementer Status

**DONE:** Check the handoff against the assigned acceptance criteria. Reuse
existing review evidence; commission review only for a remaining evidence gap.

**DONE_WITH_CONCERNS:** Read concerns. If about correctness or scope, use SendMessage to address. If observations, note and proceed.

**NEEDS_CONTEXT:** Use SendMessage to provide missing context — agent retains full state.

**BLOCKED:** Assess: context problem → SendMessage more context. Too hard → dispatch new agent with more capable model. Too large → break into pieces. Plan wrong → escalate to user.

## Example Workflow

```
You: I'm using Subagent-Driven Development to execute this plan.

[Read delegated plan, select authorized tasks and assignment boundaries]

Task 1: Hook installation script

Agent(name="impl-hooks", prompt="[full task text]")

impl-hooks via SendMessage: "Should hooks install at user or system level?"
You: SendMessage(to="impl-hooks", message="User level (~/.config/myapp/hooks/)")

impl-hooks: DONE — implemented, 5/5 tests passing, committed

Agent(name="spec-review-hooks", prompt="Review against spec...")
spec-review-hooks: ✅ Spec compliant

Agent(name="quality-review-hooks", subagent_type="adversarial-reviewer", prompt="Review quality...")
quality-review-hooks: ✅ Approved

[Mark Task 1 complete. If beads: bd close <task-id>]

Task 2: Recovery modes

Agent(name="impl-recovery", prompt="[full task text]")
impl-recovery: DONE — 8/8 tests passing

Agent(name="spec-review-recovery", prompt="Review against spec...")
spec-review-recovery: ❌ Missing progress reporting, extra --json flag

SendMessage(to="impl-recovery", message="Fix: remove --json, add progress reporting")
impl-recovery: Fixed, committed

# Round 2 of the review round cap (2 review rounds); leftovers -> bd create
Agent(name="spec-review-recovery-2", prompt="Re-review...")
spec-review-recovery-2: ✅ Spec compliant

Agent(name="quality-review-recovery", subagent_type="adversarial-reviewer", prompt="Review quality...")
quality-review-recovery: Issue: magic number (100)

SendMessage(to="impl-recovery", message="Extract PROGRESS_INTERVAL constant")
impl-recovery: Done, committed

[Mark Task 2 complete]

[After all assigned tasks]
Agent(name="final-reviewer", subagent_type="adversarial-reviewer", prompt="Final review...")
final-reviewer: All requirements met, ready to merge

Done!
```

## Continuation Discipline

**For the coordinator (you):**

Continue the authorized tasks in the delegated plan, without adding adjacent
findings to execution. Route reviewer-reported causal blockers to the implementer.
Repair and re-review inside the round cap: at most 2 review rounds, then record
nonblocking findings with `bd create`; a finding that causally blocks the delegated
outcome gets one more repair round, then escalate that blocker. Completion means
the assigned tasks and outcome are verified, with nonblocking findings reported.

**For every implementer prompt, append this block:**

> **CONTINUATION DISCIPLINE:** DO NOT wind down prematurely. DO NOT summarize
> remaining work and stop. If a problem stands between you and your assigned
> outcome, repair it only within your assigned scope and allowed effects. Anything beyond that outcome — other beads, the rest of the
> epic, adjacent bugs or cleanup — is not yours: report it to your lead (or
> `bd create` it) and do not fix it. If an assigned verification fails, debug and fix its causal blocker within your allowed effects — do not report
> the failure and stop. If you hit an obstacle, investigate and work around it.
> You are done when your implementation works end-to-end, tests pass, and you've
> self-reviewed. "I made good progress" is not DONE. "Tests pass and the feature
> works" is DONE.

**For every reviewer prompt, append this block:**

> **CONTINUATION DISCIPLINE:** DO NOT rubber-stamp incomplete work. Read the ACTUAL
> code, not just the report. Reviewers report findings; they do not repair or implement.
> Classify causal blockers and adjacent findings; return evidence at completion. If you find issues, report ALL of them — do not stop
> after finding the first one. Your job is complete when you have verified every
> requirement against the actual implementation code.

## Red Flags

**Never:**
- Dispatch agents without `name` (they're anonymous and unaddressable)
- Start implementation on main/master without explicit user consent
- Skip verifying spec compliance or code quality
- Proceed with unresolved causal blockers to the assigned outcome
- Dispatch multiple implementation subagents in parallel (conflicts)
- Skip scene-setting context
- Accept "close enough" on spec compliance
- Treat separate spec and quality reviewers as mandatory prerequisites
- **Stop after partial completion** — all assigned tasks must be done, not just some
- **Summarize remaining work instead of doing it** — that is premature wind-down

## Integration

**Before starting:**
- Reuse the assigned plan or approved design. Discovery is for unresolved design
  work; implementation authorization does not require restarting it.
- Work on a feature branch, not main: `git checkout -b <branch-name>`

**Final code review:**
- Verify the final diff against the assigned outcome. Reuse accepted review
  evidence; dispatch a bounded reviewer only for a remaining evidence gap.

**Merging:**
- Push the branch: `git push -u origin <branch-name>`
- Open a PR: `gh pr create --fill`
- Merge when CI passes and review is clean.

**With beads:**
- Keep `bd` state aligned with the assigned outcome. An explicit request to
  execute a tracked task may invoke `/beads-execution`; generic implementation
  does not restart that workflow.
