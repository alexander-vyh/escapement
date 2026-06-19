---
name: build
description: >
  Unified entry point for feature work. Classifies work type, checks for
  existing state, pours the right molecule. The user says "build X" and
  the system handles the rest.
---

# /build

Optional explicit trigger for the mol-feature pipeline. Claude should also
auto-detect build intent per planning-discipline.md — this skill exists for
when the user wants to be deliberate.

## Usage

```
/build {description of what to build}
```

## What It Does

1. **Classify** — Is this a feature, bug, chore, or spike?
   - Feature/cross-cutting → mol-feature
   - Bug/chore → mol-rapid
   - Spike → mol-rapid with type=spike

2. **Check existing state** — Don't duplicate work.
   - `bd mol current` — active molecule already?
   - `bd list` — existing tasks for this topic?
   - `openspec/changes/` — existing change?
   - If found → resume, don't start fresh

3. **Pour the right molecule:**
   ```bash
   bd mol pour mol-feature --var name="{name}" --var problem="{problem}"
   ```
   Or `mol-rapid` for bugs/chores.

4. **Step back** — molecule-awareness drives the pipeline from here.

## What the User Sees

"Starting {name}. First up: does this need building?"

Then the brainstorm step runs. The user never sees molecule IDs, formula
names, or bd commands.

## No `.beads/` Directory?

Initialize beads and Claude integration automatically:
```bash
bd init
bd setup claude
```
Then proceed with the molecule pour as normal. The user should not have to
set up beads manually — `/build` handles it.
