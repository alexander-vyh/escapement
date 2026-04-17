---
name: dispatching-parallel-agents
description: Use when facing 2+ independent tasks that can be worked on without shared state or sequential dependencies
---

# Dispatching Parallel Agents

This skill wraps the superpowers dispatching-parallel-agents skill with mandatory TeamCreate + named-agent dispatch. All agents MUST be on a team so they can communicate via SendMessage and show up as selectable teammates.

---

## Overview

You delegate tasks to specialized **named** agents on a **team**. By precisely crafting their instructions and context, you ensure they stay focused and succeed at their task. They should never inherit your session's context or history — you construct exactly what they need.

**Core principle:** Create a team, then dispatch one **named** agent per independent problem domain. They work concurrently and communicate via `SendMessage`.

## Beads Integration

Named agent teams and beads are complementary — beads tracks *what* to do, teams handle *how* agents coordinate while doing it.

- **Project has `.beads/`:** Use `/beads-execution` for the dispatch loop (`bd ready` → claim → dispatch → review → `bd close`). Agents dispatched by beads-execution MUST still use TeamCreate + team_name + name.
- **No beads:** Use this skill directly. TeamCreate + named agents are the constant regardless of whether beads is present.

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

### 1. Create a Team

**ALWAYS start by creating a team.** Without this, agents cannot talk to each other.

```
TeamCreate(team_name="debug-session")
```

### 2. Identify Independent Domains

Group work by what's independent:
- File A tests: Tool approval flow
- File B tests: Batch completion behavior
- File C tests: Abort functionality

### 3. Dispatch Named Agents ON the Team

**MANDATORY: Every agent MUST have both `name` AND `team_name`.** The hook will block agents missing either.

```
# Step 1: Create the team
TeamCreate(team_name="debug-session")

# Step 2: Dispatch agents on the team
Agent(
  name="abort-fixer",
  team_name="debug-session",
  description="Fix abort test failures",
  prompt="Fix the 3 failing tests in agent-tool-abort.test.ts. [details...]
    You are on team 'debug-session' with batch-fixer and race-fixer.
    If your fix affects their domain, use SendMessage to notify them."
)

Agent(
  name="batch-fixer",
  team_name="debug-session",
  description="Fix batch completion failures",
  prompt="Fix the 2 failing tests in batch-completion-behavior.test.ts. [details...]
    You are on team 'debug-session' with abort-fixer and race-fixer.
    If your fix affects their domain, use SendMessage to notify them."
)

Agent(
  name="race-fixer",
  team_name="debug-session",
  description="Fix race condition failures",
  prompt="Fix the 1 failing test in tool-approval-race-conditions.test.ts. [details...]
    You are on team 'debug-session' with abort-fixer and batch-fixer.
    If your fix affects their domain, use SendMessage to notify them."
)
```

All three show up as selectable teammates and can SendMessage to each other.

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
# Create the team
TeamCreate(team_name="auth-review")

# Dispatch persona agents on the team
Agent(
  name="security-reviewer",
  team_name="auth-review",
  description="Security perspective review",
  prompt="Review the auth middleware changes from a security perspective.
    You are on team 'auth-review' with ux-reviewer and perf-reviewer.
    After your initial review, use SendMessage to share your findings.
    Read and respond to the other reviewers' findings.
    Push back if you disagree — this is a debate, not a rubber stamp."
)

Agent(
  name="ux-reviewer",
  team_name="auth-review",
  description="UX perspective review",
  prompt="Review the auth middleware changes from a UX perspective.
    You are on team 'auth-review' with security-reviewer and perf-reviewer.
    After your initial review, use SendMessage to share your findings.
    Read and respond to the other reviewers' findings.
    Push back if you disagree — this is a debate, not a rubber stamp."
)

Agent(
  name="perf-reviewer",
  team_name="auth-review",
  description="Performance perspective review",
  prompt="Review the auth middleware changes from a performance perspective.
    You are on team 'auth-review' with security-reviewer and ux-reviewer.
    After your initial review, use SendMessage to share your findings.
    Read and respond to the other reviewers' findings.
    Push back if you disagree — this is a debate, not a rubber stamp."
)
```

## Agent Prompt Structure

Good agent prompts are:
1. **Named** — `name` parameter on every Agent call
2. **On a team** — `team_name` matching the TeamCreate call
3. **Focused** — One clear problem domain
4. **Self-contained** — All context needed to understand the problem
5. **Team-aware** — Lists other agents' names so they can coordinate via SendMessage
6. **Specific about output** — What should the agent return?

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

**❌ No team:** `Agent(name="fixer", prompt="...")` — named but isolated, can't talk to others
**✅ On a team:** `Agent(name="fixer", team_name="debug", prompt="...")` — can SendMessage

**❌ No name:** `Agent(prompt="Fix tests")` — anonymous, unaddressable
**✅ Named:** `Agent(name="test-fixer", team_name="debug", prompt="Fix tests")`

**❌ No TeamCreate:** Dispatching with team_name but never called TeamCreate
**✅ TeamCreate first:** `TeamCreate(team_name="debug")` then dispatch agents

**❌ Simulated roundtable:** Writing persona dialogue in your own output
**✅ Real roundtable:** TeamCreate + named agents that argue via SendMessage

## Vocabulary

| User says | Means |
|-----------|-------|
| "agent team" | TeamCreate + named agents on the team |
| "roundtable" | TeamCreate + named agents arguing via SendMessage |
| "panel of experts" | TeamCreate + named agents with different persona prompts |
| "have them talk to each other" | Agents on a team using SendMessage |

**"Roundtable" NEVER means writing simulated dialogue in your output.** It ALWAYS means TeamCreate + real named agents that independently analyze and communicate via SendMessage.

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
