# Runbook: rename beads prefix `claude-workflow-setup-` → `escapement-`

**Status:** PREPARED, not executed. Goal: match the bead prefix to the repo name.

## Why this is non-trivial (read before running)

`bd rename-prefix escapement --repair` is the obvious command but is **destructive
here**: the DB has two *detected* prefixes — `claude-workflow-setup` (106) and
`claude-workflow-setup-mol` (50, an artifact of the molecule IDs) — so the tool
forces `--repair`, which **re-IDs every issue to a random hash**
(`...-egc → escapement-791c3ebf`), destroying readable suffixes and the molecule
parent/child hierarchy (`fxh.1/.2/.3`, `mol-5s2`).

The migration instead renames each issue individually with `bd rename`, which
**preserves the suffix** (`...-egc → escapement-egc`) and updates cross-issue
references, dependencies, labels, and comments inside the DB.

## Blast radius

| Surface | Count | Handled by |
|---------|-------|-----------|
| Beads issues (all statuses, both prefixes) | 156 | `bd rename` loop (Step 1) |
| Tracked files referencing the prefix (hooks, tests, launchd plists, INSTALL.sh) | ~62 | `perl -pi` sweep (Step 2) |
| Test files asserting specific IDs | 7 | swept in Step 2; re-run in Step 4 |
| `.beads/config.yaml` issue-prefix | 1 | Step 3 |
| **Git commit messages / history** | many | **NOT handled** — immutable; expected to keep old IDs |

## Preconditions

1. **Concurrent sessions idle.** The beads DB is shared. Renaming changes IDs out
   from under any in-progress work. Check `bd list --status=in_progress` is empty
   (or coordinate with the owners). As prepared, 2 in-progress beads were claimed by
   other sessions — wait for those to clear.
2. **Clean working tree** (beads runtime churn aside) so the diff is reviewable.
3. On a feature branch (not `main`).

## Procedure

```bash
# 1. Dry-run — prints every rename + file sweep, applies nothing
scripts/migrate-bead-prefix.sh

# 2. Review the dry-run output (issue count ≈156, file count ≈62)

# 3. On a fresh feature branch, when sessions are idle:
git switch -c chore/rename-bead-prefix-escapement origin/main
scripts/migrate-bead-prefix.sh --execute

# 4. Verify (the script already runs --check + pytest; confirm green), then:
git add -A
git commit -m "chore(beads): rename issue prefix claude-workflow-setup- -> escapement-"
# push + PR
```

## Verification (oracle)

- `bd list --all --json | jq -r '.[].id'` shows **0** IDs starting with
  `claude-workflow-setup-` and all starting with `escapement-`.
- `git grep -lI claude-workflow-setup- -- ':!.beads/'` returns **nothing**.
- `python3 tools/render_agent_surfaces.py --check` exits 0.
- `pytest tests/ claude/hooks/tests/` green (the 7 ID-asserting tests pass with the
  swept IDs).

## Rollback

The migration is one git commit + a beads DB change. To roll back:
- `git revert` / reset the commit for the file changes.
- Re-run the script with OLD/NEW swapped, OR restore the beads DB from
  `.beads/backup/` (timestamped snapshots exist).

## Residual / accepted

- Historical git commit messages and PR titles keep the old `claude-workflow-setup-*`
  IDs. This is a historical record, not a live reference; accepted.

## Post-execution notes (executed 2026-06-22)

The prepared script (Step 1 per-issue `bd rename` + Step 2 file sweep) was
**necessary but not sufficient** on bd 1.0.5. Step 3 (`bd config set issue-prefix`)
is also **rejected by bd** (`issue_prefix cannot be set via 'bd config set'`). Four
gaps surfaced during execution; all were resolved:

1. **Registered prefix (critical).** `bd rename` changes issue IDs but NOT the
   prefix new `bd create` uses — that lives in the Dolt `config` table
   (`issue_prefix`), not `.beads/config.yaml` (which is `bd init`-only). After the
   156 renames, a probe `bd create` still produced `claude-workflow-setup-*`. Fixed
   with `dolt sql -q "UPDATE config SET value='escapement' WHERE \`key\`='issue_prefix'"`
   (verified: new creates now get `escapement-*`). Note: `bd rename-prefix` cannot
   set this — it validates a **max 8-char** prefix, and "escapement" is 10; the
   per-issue path and the direct config write both bypass that validation, and bd
   accepts the 10-char prefix fine at create time.
2. **Hidden molecule-gate rows.** 6 `claude-workflow-setup-mol-*` gate issues were
   excluded from `bd list --all` (bd's detector treats `*-mol` as a separate,
   hidden prefix family), so the Step-1 loop (sourced from `bd list`) never renamed
   them. They WERE renameable directly: `bd rename claude-workflow-setup-mol-<x>
   escapement-mol-<x>` (bd-native, cascades FKs + recomputes content_hash). After
   renaming, these 6 gates became consistently visible (count 156 → 162); none
   pollute `bd ready`.
3. **Dangling `child_counters`.** 14 dead counter rows referenced parents that
   exist under no prefix (orphaned by past `bd delete`s). Deleted directly (leaf
   table, no FK dependents).
4. **Accepted historical residue (NOT rewritten).** The `events` audit table (250
   rows), `close_reason` prose ("folded into …"), and one task title that literally
   names the migration ("…claude-workflow-setup- -> escapement-") retain old-prefix
   strings. These are historical/self-referential and content_hash-bearing —
   rewriting them buys nothing and risks hash desync. Same principle as the accepted
   git-history residue above.

**Lesson for re-use:** a per-issue `bd rename` migration must also (a) UPDATE the
Dolt `config.issue_prefix`, (b) rename hidden `*-mol` rows by querying the `issues`
table directly (not `bd list`), and (c) sweep dangling `child_counters`. The
`dependencies` table cascaded automatically via `bd rename`.
