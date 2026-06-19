# Molecule Awareness — Global Rule

## On Every Session Start

If the current directory has a `.beads/` directory, run `~/.beads/mol-status.sh` and act on the output.

If active molecules are found:
- Present the current phase (Design / Validate / Build) and the next step
- Offer to run the next step — don't wait for the user to ask
- If a gate is ready, present it as a decision with a summary of what was produced
- Never show bd commands, gate IDs, step IDs, or molecule internals to the user

If no active molecules are found, say nothing about molecules.

## Gate Resolution

When the user approves a gate (says "looks good", "approved", "yes", "continue", "proceed", or similar affirmative):
- Run `bd gate resolve <gate-id>` silently
- Record the gate resolution (silently — never surface to user):
  ```
  bd audit record --kind gate_resolved \
    --issue-id <gate-id> \
    --response '{"molecule": "<mol-id>", "gate": "<gate-name>", "phase": "design|validate|build", "decision": "approved"}'
  ```
- Then check `bd mol current <molecule-id>` for the next step
- Offer to run it

When the user rejects a gate (says "revise", "no", "go back", or similar):
- Record the rejection (silently):
  ```
  bd audit record --kind gate_resolved \
    --issue-id <gate-id> \
    --response '{"molecule": "<mol-id>", "gate": "<gate-name>", "phase": "design|validate|build", "decision": "rejected"}'
  ```
- Keep the gate open
- Help the user revise the previous step's output
- When they're satisfied, ask again

## Phase Presentation

Map internal steps to phases for the user:

| Internal Steps | User-Facing Phase |
|---------------|-------------------|
| discovery, review-discovery | **Design** — "We're designing X" |
| work-breakdown | **Design** (tail end) — "Breaking down the work" |
| execute-skeleton, review-skeleton | **Validate** — "Testing the riskiest assumption" |
| execute-full | **Build** — "Building out the full feature" |

## Automatic Progression

When a step completes and the next step has no gate:
- Proceed automatically — don't ask permission for mechanical steps
- Announce what you're doing: "Discovery is done. Running work-breakdown now."

When a step completes and the next step has a gate:
- Stop and present the gate as a decision
- Summarize what was produced in the previous step

When all steps in a molecule are complete, record completion (silently):
```
bd audit record --kind molecule_complete \
  --issue-id <mol-id> \
  --response '{"name": "<feature-name>", "total_steps": N, "amendments": N, "formula": "mol-feature|mol-rapid"}'
```

## Timing Analysis

`bd mol progress <molecule-id>` already tracks step-level timing data including:
- Completed / total steps with percentage
- Rate (steps/hour based on closure times)
- ETA for remaining work

Use this for retrospectives or when the user asks about velocity — no need to
add redundant timing audit records. For per-issue timestamps, use
`bd show --long --local-time <issue-id>`.

## Multi-Molecule Routing

If multiple molecules are active, present the highest-priority one first and mention others exist:
- "You have a feature in the Validate phase (dark-mode) and one in Design (auth-refactor). Want to continue with dark-mode?"

## Creating New Molecules

When the user describes new feature work, offer to create a molecule:
- "This sounds like a feature. Want me to set up the discovery → build pipeline for it?"
- If yes, run `bd mol pour mol-feature --var name="<name>" --var problem="<problem>"`
- Then immediately start the discovery step

**How to create a molecule (exact sequence):**

1. Check available formulas: `bd formula list`
   - `mol-rapid` — bug fixes, chores, one-off tasks (2 steps, no gates)
   - `mol-feature` — standard features (6 steps, 2 gates)
   - If no formulas found, fall back to manual `bd create` with an epic + child tasks

2. Select the formula based on scope:
   - Quick fix / bug / chore → `mol-rapid`
   - Feature work → `mol-feature`

3. Pour the molecule:
   ```
   bd mol pour mol-feature --var name="<kebab-case-name>" --var problem="<one-sentence problem>"
   ```
   This creates the root epic + all step tasks + gate tasks with dependencies.

4. Check the molecule state: `bd mol current <molecule-id>`
   - The first step (discovery) will show as [ready]
   - Offer to start it immediately

**Do NOT use `bd mol show` to find formulas** — that command only works on existing molecules.
Use `bd formula list` to see available formulas and `bd formula show <name>` for details.

**Variable naming:** The `name` var should be kebab-case (e.g., "zoom-data-expansion"). The `problem` var is a one-sentence problem statement.

## Scope Change Detection

During any conversation with an active molecule, listen for scope-change language:
- "let's also...", "can we add...", "what about including..."
- "actually we don't need...", "cut X", "remove Y from scope"
- "scope change:", "actually...", "change of plans"
- "the spec assumed... but actually..."

When detected:
- Confirm: "That sounds like a scope change. Want me to update the spec and
  re-evaluate affected tasks?"
- If yes: trigger the Spec Amendment Flow (§2h in beads-execution). Draft a
  delta spec, create an amendment task, block affected tasks, present for approval.
- If no: note it and continue with current scope. Do not silently adjust.

**Scope changes are always human-driven.** Claude may detect the language and
offer the amendment path, but the user must explicitly approve any change to
what is being built. Never adjust scope, specs, or task descriptions based on
conversational signals alone.
