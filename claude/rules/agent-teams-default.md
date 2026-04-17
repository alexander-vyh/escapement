# Agent Teams as Default — Global Rule

## Default to Agents

For any task beyond a single quick action, dispatch agents. This includes research, exploration, implementation, debugging, code review, investigation — anything that involves multiple steps or could benefit from parallelism.

A single file read, one search, or a small edit is fine inline. Everything else should go to agents.

## Always Use TeamCreate + Named Agents

Agent teams require THREE things. Missing any one means agents CANNOT talk to each other:

1. **`TeamCreate`** — creates the team infrastructure (call ONCE per task)
2. **`name`** on each Agent — makes agent addressable by name
3. **`team_name`** on each Agent — puts agent ON the team

Without all three, agents are isolated subprocesses that cannot coordinate.

### Concrete Example — This Is What Every Dispatch Must Look Like

```
# Step 1: Create the team FIRST
TeamCreate(team_name="research")

# Step 2: Dispatch agents ON the team
Agent(
  name="researcher-1",
  team_name="research",
  description="Research auth patterns",
  prompt="Investigate OAuth patterns in the codebase.
    You are on team 'research' with researcher-2.
    Use SendMessage to share findings and argue."
)
Agent(
  name="researcher-2",
  team_name="research",
  description="Research session handling",
  prompt="Investigate session management patterns.
    You are on team 'research' with researcher-1.
    Use SendMessage to share findings and argue."
)
# Now they show up as selectable teammates and can SendMessage to each other

# ❌ WRONG — no TeamCreate, no team_name
Agent(name="researcher-1", prompt="Investigate OAuth patterns...")
Agent(name="researcher-2", prompt="Investigate session management...")
# These look named but are ISOLATED — cannot communicate

# ❌ WRONG — no name at all
Agent(prompt="Investigate OAuth patterns...")
# Fire-and-forget, no coordination possible
```

### Vocabulary — What the User Means

| User says | What to do |
|-----------|-----------|
| "agent team" | TeamCreate + 2-5 named agents with `team_name` |
| "roundtable" | TeamCreate + named agents with persona prompts that argue via SendMessage |
| "panel of experts" | TeamCreate + named agents with different expertise, share findings via SendMessage |
| "have them talk to each other" | Agents must use SendMessage — requires TeamCreate + team_name + name |
| "use agents" | TeamCreate + named agents, not inline work |

**"Roundtable" NEVER means writing simulated dialogue in your output.** It ALWAYS means dispatching real named agents on a team that independently analyze and communicate via SendMessage.

### Works With Beads

Named agents and beads are complementary. Beads tracks *what* to do (`bd ready`, `bd close`), named agents handle *how* they coordinate while doing it. When dispatching agents for beads-tracked work, STILL use TeamCreate + team_name + name — beads adds tracking, not replaces naming.

## Agent Pairing for Quality

When dispatching implementation agents, consider pairing them with independent
QA agents that work from the success criteria or spec — NOT from the code.

### Independent Test Agent Pattern

For any non-trivial implementation task, dispatch alongside the implementer:

```
Agent(name="implementer", team_name="feature-x", prompt="Implement the auth flow per spec...")
Agent(name="qa-tester", team_name="feature-x", prompt="Write tests for the auth flow.
  Work from the SUCCESS CRITERIA and SPEC — do NOT read the implementation code.
  Your tests verify the OUTCOMES, not the implementation details.
  Share your test file via SendMessage when ready for the implementer to run.")
```

The QA agent writes tests that the implementer must pass. The tests catch the gap
between what the spec says and what the code does — because the tester never saw
the code.

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

## Anti-Patterns

- Sequential inline web searches instead of parallel search agents
- Reading 10 files one by one instead of dispatching explore agents
- Doing all investigation yourself instead of dispatching a team
- Using anonymous agents that can't talk to each other
- **Writing simulated persona dialogue in your output instead of dispatching real agents**
- **Dispatching agents without `team_name`** — they look named but are isolated
- **Dispatching agents without `name`** — they are anonymous and unaddressable
- **Skipping `TeamCreate`** — without it, `team_name` has no team to join
- **Using `Agent(prompt="...")` without `name` and `team_name`** — this is ALWAYS wrong
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
