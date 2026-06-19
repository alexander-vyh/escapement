# Planning Discipline — Global Rule

## Detection and Dispatch

When the user describes new work ("build X", "add X", "implement X", or similar),
detect the type and dispatch automatically — do not ask the user which tool to use.

**New feature or cross-cutting change (project has `.beads/`):**
Pour `mol-feature`:
```bash
bd mol pour mol-feature --var name="{kebab-case-name}" --var problem="{one-sentence problem}"
```
The molecule handles the full pipeline: brainstorm → discovery → review → breakdown →
skeleton → validation → build → ceremony retro → outcome check.
Molecule-awareness drives step progression automatically.

**Bug fix or chore (project has `.beads/`):**
Pour `mol-rapid`:
```bash
bd mol pour mol-rapid --var name="{name}" --var problem="{problem}"
```

**No `.beads/` directory:**
Run `bd init` to set up beads, then pour the appropriate molecule.
Beads should be available in every repo where work is tracked.

**User explicitly says "proceed without discovery":**
Skip discovery. Go straight to implementation. Allowed, no judgment.

## Resume Detection

Before pouring a new molecule, check for existing work:
1. `bd mol current` — active molecule for this feature?
2. `bd list` — existing tasks matching this topic?
3. `openspec/changes/` — existing change with this name?

If found, resume rather than start fresh.

## Navigation (read before any implementation work)

| Question | Source of truth |
|----------|----------------|
| Why are we building this? What's the riskiest assumption? | `openspec/changes/{name}/design.md` |
| What does component X do in state Y? | `openspec/changes/{name}/specs/` |
| What tasks exist? What's unblocked? | beads (`bd ready`) |

Authority: `openspec/changes/*/design.md` wins on design intent. beads wins on task state.

## Escape Hatches

- Bug fixes: no discovery needed
- Chores: no discovery needed
- Exploratory/spike work: no discovery needed, but if it reveals new feature work,
  pour a molecule before committing to implementation
- User explicitly says "proceed without discovery": allowed

## The Walking Skeleton Rule

The first deliverable from any new feature must be the walking skeleton — the minimum
system that tests the riskiest assumption. 1-3 tasks at 30-60 min each. If bigger, cut.
