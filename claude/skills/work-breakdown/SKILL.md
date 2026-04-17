---
name: work-breakdown
description: >
  Translate a validated design (from openspec/changes/ or docs/plans/) into a
  beads task graph with outcome-based acceptance criteria, failure modes,
  scope boundaries, and spec traceability via --spec-id.
  Invoked after the walking skeleton validates assumptions.
---

# Work Breakdown

Translates an approved, post-skeleton design into a full beads execution graph. This is the bridge between "we know what to build" and "here are the trackable tasks."

## When to Use

- Use `/work-breakdown {path}` where `{path}` is one of:
  - An openspec change directory: `openspec/changes/{name}/`
  - A pre-OpenSpec design doc: `docs/plans/YYYY-MM-DD-{topic}-design.md` (backward compatibility only)
- The design should be post-skeleton -- assumptions tested, placeholders resolved.
- This skill does NOT do design work. If the design is incomplete, route to `/discovery edit` first.

## Path Resolution

All file paths must be resolved relative to the project root. In a git worktree, the project root is NOT the main repo -- it is the worktree root.

**On every invocation**, resolve the project root:
```bash
git rev-parse --show-toplevel
```

All paths in this skill (input resolution, `--spec-id` values, source references) are relative to this root. This ensures correct behavior in both standard repos and worktrees.

## Input Resolution

### Canonical: OpenSpec change directory (`openspec/changes/{name}/`)

`openspec/changes/` is the canonical input location. When the input is an openspec change directory, read these artifacts in order:

1. **`proposal.md`** -- Problem statement, non-goals, capabilities, impact. Non-goals become task boundaries.
2. **`design.md`** -- Riskiest assumption, walking skeleton, proof of delivery, anti-metrics, decisions, risks, future increments.
3. **`specs/*.md`** -- Behavioral specs with requirements (SHALL/MUST) and scenarios (WHEN/THEN). Each requirement becomes a `--spec-id` target.
4. **`tasks.md`** -- Implementation checklist from discovery. Each task maps to spec requirements. This is the seed for the breakdown.

If `tasks.md` does not exist, say: "Discovery hasn't finished all artifacts yet. Run `openspec status --change {name}` to see what's missing."

### Backward compatibility: Legacy design doc (`docs/plans/`)

For projects that predate OpenSpec, fall back to reading a single design doc at `docs/plans/YYYY-MM-DD-{topic}-design.md`. Extract: problem statement, non-goals, riskiest assumption, walking skeleton results, proof of delivery, anti-metrics. No spec traceability is available in this mode.

### Auto-detection

If invoked without a path argument:
1. Check for active openspec changes: `openspec list --json`. If the `openspec` command is not found, say: "OpenSpec isn't set up in this project yet. Run `/discovery` to get started." Then stop.
2. If exactly one active change exists, use it.
3. If multiple exist, pick the most recently modified change directory and present it: "Using change '{name}' (most recently modified). Pass a different name to override." Only list all changes if modification times are within 1 hour of each other.
4. If none exist, look for the most recent file in `docs/plans/*-design.md` (by modification time) and offer it.
5. If nothing found at all, say: "No design found. Run `/discovery` first."

## Pre-Check (Hard Gates)

All pre-checks are hard gates. The skill refuses to proceed until they pass. User-facing messages use plain language -- no internal tag names like `[VALIDATED]` or `[PLACEHOLDER]`.

### OpenSpec mode

Scan `openspec status --change {name} --json` for artifact completion:

- **Incomplete artifacts:** Stop: "Discovery isn't finished yet -- these artifacts are missing: [list]. Run `/discovery` to complete them."
- **Unresolved sections in specs:** If placeholder or deferred tags exist in spec files, stop: "Some specs have sections that haven't been filled in yet: [list]. Finish them in `/discovery` before breaking down tasks."
- **Missing walking skeleton:** If no walking skeleton section exists in `design.md`, stop: "The design doesn't define a walking skeleton yet. It needs 1-3 concrete tasks that test the riskiest assumption."

### Legacy mode

- **Unresolved placeholders:** Stop: "This design has unfinished sections: [list]. Run `/discovery edit {path}` to fill them in."
- **Skeleton not tested:** If no validated sections exist, stop: "The walking skeleton hasn't been tested yet. Build and test it first, then come back for the full breakdown. If you need skeleton tasks to start testing, say so -- I'll generate only the skeleton tasks and stop there." If the user requests skeleton tasks, route to skeleton-only generation (see Walking Skeleton Tasks) and announce: "Generating skeleton tasks only."

## WIP Estimate

**Before generating any tasks**, estimate the total task count from the input:
- In openspec mode: count tasks in `tasks.md` plus any future increment items from `design.md`.
- In legacy mode: count walking skeleton tasks plus future increment items.

If the estimate exceeds 7: "This looks like about [N] tasks. That's above the WIP limit of 7. I can split into phases (sub-epics of ~5 tasks each) or generate the full flat breakdown. Which do you prefer?"

This fires before generation, not after -- it's cheaper to restructure scope than to rewrite a breakdown.

## Reading the Input

Say "Reading {change-name} design..." before reading artifacts. This fills the silence gap while artifacts are being processed.

### OpenSpec mode

Extract from the artifacts:

| Source file | What to extract |
|---|---|
| `proposal.md` | Problem statement, non-goals (become task boundaries), capabilities list |
| `design.md` | Riskiest assumption, walking skeleton tasks, proof of delivery, anti-metrics, decisions, future increments |
| `specs/*.md` | Requirements with names (become `--spec-id` values), scenarios (become verification criteria) |
| `tasks.md` | Task groups with spec requirement mappings (seed for breakdown) |

### Traceability map (user-visible checkpoint)

After reading the artifacts, build a traceability map and **present it to the user before generating tasks**:

```
Here's how tasks map to spec requirements:

| Task (from tasks.md) | Spec requirement | Scenario |
|---|---|---|
| {task description} | specs/{capability}.md > {requirement} | {scenario name} |
| {task description} | specs/{capability}.md > {requirement} | {scenario name} |
| {task with no match} | -- UNMAPPED -- | |

Confirm this mapping is correct, then I'll generate the breakdown.
```

This is the verification step for `--spec-id` correctness. If the mapping is wrong, fix it here -- not after tasks are created. Unmapped tasks are flagged; unmapped spec requirements (specs with no corresponding task) are also flagged as potential gaps.

The user must confirm or adjust before generation proceeds.

### Legacy mode

Read the full design doc. Extract: problem statement, non-goals, riskiest assumption, walking skeleton results, proof of delivery, anti-metrics. The non-goals are critical -- every non-goal becomes a task boundary in the breakdown. No traceability map in legacy mode (no specs to map to).

## Walking Skeleton Tasks

The walking skeleton tasks are special. They are the FIRST deliverable and must be identifiable in beads for mol-feature integration.

**Rules for skeleton tasks:**
- Label with `--label skeleton` on the `bd create` command
- Set priority to P1: `-p P1`
- Must test the riskiest assumption from `design.md`
- Task count: 1-3 at 30-60 min each. If the skeleton is bigger, cut until it fits.
- In openspec mode: each skeleton task must have a `--spec-id` pointing to the requirement it tests

**Skeleton vs. full breakdown:**

Announce which path is being taken before generating:

- **Skeleton only:** "The walking skeleton hasn't been validated yet, so I'm generating skeleton tasks only -- [N] tasks to test the riskiest assumption. After these pass, re-run `/work-breakdown` for the full task graph."
- **Full breakdown:** "The skeleton has been validated. Generating the full breakdown including remaining tasks."

## Per-Task Requirements

The canonical definition of what every task must contain. The output format and enforcement rules reference this section -- it is not repeated elsewhere.

Every task must have these three standing elements:

### 1. Acceptance Criteria (Outcome Format)

> "Done when [real-world state], not when [false proxy]."

The "not when" clause is MANDATORY. It names the exact trap the implementing agent will fall into. Examples:

- "Done when the weekly report Slack message contains real completion rates from the database, not when the query returns results to stdout."
- "Done when the calendar monitor triggers recording within 60 seconds of a meeting starting, not when the API endpoint responds to a manual curl."

The "not when" must be specific to this task -- not a generic "not when tests pass."

**In openspec mode:** Derive the "done when" from the spec scenario's THEN clause. The scenario is the ground truth for acceptance.

### 2. How This Fails

Name the specific failure mode for THIS task. Not "it might have bugs." Specific:

- "Fails if the query counts dismissed follow-ups as completed, inflating the rate."
- "Fails if the Slack message is sent but the blocks render incorrectly on mobile."

### 3. What's NOT in Scope

Per-task boundary derived from non-goals.

- **OpenSpec mode:** Non-goals come from `proposal.md`. Every non-goal must map to at least one task boundary.
- **Legacy mode:** Non-goals come from the design doc.
- Example: if the non-goal is "not a notification system," every task that touches messaging must say "NOT in scope: push notifications, urgency signals, real-time alerts."

## Output Format

Present a human-readable task summary for review. The reviewer reads the summaries, not commands. Raw `bd create` commands stay hidden until the user approves execution.

Each task's fields match the three standing elements from [Per-Task Requirements](#per-task-requirements).

### OpenSpec mode

```markdown
## Beads Import: {change-name}
Source: openspec/changes/{change-name}/
Schema: {rapid|feature|epic}

### Epic: {epic-name}

#### 1. {task-title} [skeleton]
**Traces to:** specs/{capability}.md > {requirement-name}
**Done when:** {outcome}, **not when** {false proxy}.
**Fails if:** {failure mode}
**Not in scope:** {boundary}

#### 2. {task-title}
**Traces to:** specs/{capability}.md > {requirement-name}
**Done when:** {outcome}, **not when** {false proxy}.
**Fails if:** {failure mode}
**Not in scope:** {boundary}

### Dependencies
{task 1} blocks {task 2} because {reason}.
```

The `bd create` commands are generated internally but NOT shown during review. They are executed only after the user approves.

**Command template (internal):**
```bash
bd create "{task title}" \
  --description="{full description with all per-task elements}" \
  --spec-id="openspec/changes/{name}/specs/{capability}.md#{requirement-name}" \
  --label skeleton \
  --parent {epic} -p P1 --json
```

### Legacy mode

```markdown
## Beads Import: {topic}
Source: docs/plans/YYYY-MM-DD-{topic}-design.md

### Epic: {epic-name}

#### 1. {task-title}
**Done when:** {outcome}, **not when** {false proxy}.
**Fails if:** {failure mode}
**Not in scope:** {boundary}

### Dependencies
{task 1} blocks {task 2} because {reason}.
```

**Command template (internal):**
```bash
bd create "{task title}" \
  --description="{full description with all per-task elements}" \
  --parent {epic} -p {priority} --json
```

## Molecule Integration

When invoked as part of a `mol-feature` molecule, the molecule ID will be in the conversation context from the molecule-awareness rule. Use `bd mol show {molecule-id}` to find the root epic ID.

- **Parent epic:** Create all tasks as children of the molecule's root epic.
- **Skeleton tasks:** These correspond to the `execute-skeleton` step of the molecule. Label them `skeleton` and P1 so the molecule-awareness rule can identify them.
- **Remaining tasks:** These correspond to the `execute-full` step. They are created but not started until the skeleton gate passes.
- **Do NOT create the molecule or manage gates.** The molecule-awareness rule handles gate resolution. This skill only creates the task graph.

## Spec-ID Convention

The `--spec-id` value is a structural reference embedded in the `bd create` command. It uses the full path from the project root to the spec file, with a fragment for the requirement name:

```
openspec/changes/{change-name}/specs/{capability-name}.md#{requirement-name}
```

Where:
- `{change-name}` is the openspec change directory name
- `{capability-name}` is the kebab-case filename from `specs/`
- `{requirement-name}` is the requirement heading from within that spec file

The path is relative to the project root (from `git rev-parse --show-toplevel`), ensuring correct resolution in worktrees.

If a task satisfies multiple requirements, use the primary requirement for `--spec-id` and list all in the description.

### Rapid schema

Rapid changes have no `specs/` directory. Use the design doc as the reference:

```
openspec/changes/{change-name}/design.md#walking-skeleton
```

## Enforcement Rules

The skill refuses to finalize the breakdown if any of these checks fail. All per-task element definitions are in the [Per-Task Requirements](#per-task-requirements) section above.

1. **Missing per-task elements.** Every task must have all three standing elements: acceptance criteria, failure mode, scope boundary. (See Per-Task Requirements.)
2. **Ambiguity check.** For each task, re-read it as if you had no context from this conversation. What is the first thing a fresh agent would get wrong? If a misinterpretation can be named, revise the task description until it cannot. If the ambiguity cannot be resolved by revising the description, surface it to the user: "Task '{title}' has an unresolvable ambiguity: {description}. Split it or add context." This is an internal pre-publish check: resolved ambiguities produce no output; only unresolvable ones are surfaced.
3. **Non-goal coverage.** For each non-goal (from `proposal.md` or design doc), at least one task must reference it in "Not in scope." If a non-goal has no corresponding task boundary, add one.
4. **Spec traceability gap (openspec mode only).** Every task must have a `--spec-id`. If a task cannot be traced to a spec requirement: "Task '{title}' doesn't trace to any spec requirement. Add a requirement or explain why it's needed."

## Lean Review (automatic, feature/epic only)

Before presenting the breakdown to the user, dispatch a lean-advisor agent to
review the task graph for waste. This is automatic — do not ask permission.

```
Agent(subagent_type: "personal-lean-advisor"):
  prompt: |
    Review this work breakdown for waste, over-engineering, and unnecessary
    complexity. The breakdown is for: [feature name]

    Tasks:
    [list each task: title, acceptance criteria, spec-id]

    Check:
    - Are any tasks redundant or overlapping?
    - Could any two tasks be merged without losing clarity?
    - Are there tasks that don't trace to the riskiest assumption or a spec requirement?
    - Is the walking skeleton actually minimal, or has scope crept in?
    - Would a lean practitioner cut anything from this list?

    Report only actionable findings. If the breakdown is clean, say so.
```

If the lean-advisor finds waste, revise the breakdown before presenting to the
user. If clean, proceed. The user never sees the lean review unless it changes
something — then note: "Lean review trimmed [N] tasks: [brief explanation]."

Skip this step for rapid-tier work.

## Termination

After generating the breakdown (and lean review for feature/epic), present it
and say: "Here's the breakdown -- {N} tasks across {M} groups. Say 'looks good'
to create them in beads, or name what to change."

Do not show or run `bd create` commands until the user approves. After approval, run all commands and report created issue IDs. In molecule context, add: "Tasks created under molecule {name}. Skeleton tasks are ready for the next step."

## Completion Logging (silent — never surface to the user)

After all `bd create` commands have run successfully and the user has been notified
of the created issue IDs, silently record a completion event. The user must never
see the command or its output.

```bash
echo '{"kind":"breakdown_complete","extra":{"target":"<change-name>","tasks_generated":<N>,"tasks_trimmed_by_lean":<N>,"spec_id_gaps":<N>,"wip_warning_triggered":<true|false>,"input_mode":"<openspec|legacy>","skeleton_tasks":<N>,"total_tasks":<N>}}' | bd audit record --quiet
```

Field definitions:
- `target`: the change name or design doc topic
- `tasks_generated`: total number of `bd create` commands executed
- `tasks_trimmed_by_lean`: number of tasks removed or merged by the lean review (0 if rapid or no changes)
- `spec_id_gaps`: number of tasks that had no `--spec-id` traceability (0 in legacy mode where specs don't exist)
- `wip_warning_triggered`: true if the WIP estimate exceeded 7 and the user was warned
- `input_mode`: "openspec" if reading from `openspec/changes/`, "legacy" if from `docs/plans/`
- `skeleton_tasks`: number of tasks labeled `skeleton`
- `total_tasks`: total task count in the final breakdown (should equal `tasks_generated`)

If the `bd audit record` command fails (e.g., no `.beads/` directory), ignore the error silently. Logging must never block the user flow.
