## Problem

Three pieces of the workflow tooling drifted apart when the `discovery` skill
canonicalized `openspec/changes/` (commit `73425ae`). The `discovery-gate.py`
PreToolUse hook still hardcodes `docs/plans/` (line 169), so it denies every
`bd create --type=feature|epic` in any repo that uses `openspec/changes/` for
design docs — including this one. The same hook has a 30-day `mtime` cutoff
(line 70) that silently hides any design doc older than a month, which is an
oracle-downgrade bug independent of the directory drift. The
`spec_id_enforcement.py` denial message also shows a stale `docs/plans/`
example (line 215), and `planning-discipline.md` still lists
`docs/plans/` as a co-equal source of truth alongside `openspec/changes/`.

## Riskiest Assumption

We believe replacing `docs/plans/` with `openspec/changes/` in the hook and
rule text — and removing the 30-day mtime cutoff — restores correct behavior
without breaking any repo we use. If wrong, we'll see false denials or false
allows on `bd create --type=feature|epic` in some repo, surface that quickly,
and reinstate a fallback path in a follow-up.

## Walking Skeleton

One implementation pass (~45 minutes), four mechanical edits:

1. **`claude/hooks/discovery-gate.py`** — change `plans_dir = Path(project_dir) / "docs" / "plans"` to look at `Path(project_dir) / "openspec" / "changes"` (recursively scan for `design.md` in each subdirectory). Remove the `THIRTY_DAYS` constant and the mtime cutoff in `find_recent_design_docs`. Update the denial message to reference `/discovery` and the new path.
2. **`claude/hooks/spec_id_enforcement.py`** (line 215) — update the example `--spec-id docs/plans/my-design.md` to `--spec-id openspec/changes/{change-name}/specs/{capability}.md#{requirement-name}` matching the work-breakdown skill's convention.
3. **`claude/rules/planning-discipline.md`** — remove `or docs/plans/` from the navigation table; keep `openspec/changes/{name}/design.md` as the single authoritative source.
4. **Verification** — run `~/.claude/harness/bin/verify` with a contract whose `verification_command` greps each file for the expected state and returns 0 iff all four edits are present.

The cake repo has three legacy `docs/plans/*-design.md` files (latest 2026-04-23). Their migration is a *separate* change tracked as a follow-up beads issue in the cake repo — not in scope here. This change is the workflow-tooling repair only.

## Done When

`bd create --type=feature` succeeds in any repo that has an
`openspec/changes/{name}/design.md` with the required section headers (Problem
Statement, Non-Goals, Riskiest Assumption), regardless of file age — and the
denial message, when it does fire, names `openspec/changes/` and `/discovery`
as the path forward.
