# Execution Log — gascity Adoption (first rig: unified_order_intake)

Date: 2026-06-06. Provider: **codex** (city default). First rig: **unified_order_intake**
(prefix `uoi`). This log records what was actually done, what was found, and a diagnosis that
was corrected mid-stream — including a fix (Option A) that was **withdrawn** because it rested
on a stale-read misdiagnosis.

## What we stood up (and why)

1. **Installed `gc` via pinned direct-download, not `brew install gascity`.** Rationale: brew pulls
   the `beads` formula as a mandatory dep and brew's `beads` is now stable **1.0.5** — the gated,
   corrupting version (migration 0043 breaks multi-machine `bd dolt` sync). Direct-download fetches
   only the `gc` binary, protecting the pinned **bd 1.0.4** dev build. *(Note: the install ultimately
   present is at `/opt/homebrew/bin/gc`; `bd` still resolves to the 1.0.4 dev build — verified.)*
2. **Freed the `gc` shell alias.** `~/.zshrc` had `alias gc='git commit -m'`, which shadows the
   gascity binary (aliases beat PATH). Repointed it to `gcm`; `gc` now resolves to the gascity CLI.
3. **City already stood up** (`~/gascity-hq`) with `provider = "codex"` and the **gastown pack**
   imported (always-awake `mayor`/`deacon`/`boot` + demand-spawned worker pools). The user accepted
   the gastown pack's always-on codex agents; **claude agents are manual-only by default** (none
   defined; any added later get `provider="claude"` + `min_active_sessions=0` + no auto-routing).
4. **Adopted `unified_order_intake` as a rig.** It was not a git repo and had no beads, so:
   `git init` + initial commit (23 files, `main`), then `gc rig add` (plain — it initialized beads,
   prefix `uoi`, imported the gastown pack, generated `routes.jsonl`).

## Smoke test — PASSED end to end (codex, hands-free)

Slung `gc sling unified_order_intake/gastown.polecat "Create SMOKE.txt containing: gascity works"`.
Result, verified by the real artifact (not just a closed bead):
- The rig polecat `gastown.furiosa` (codex) spawned, did the work in its worktree, the `refinery`
  agent integrated it, committed **"Add smoke file"**, and `SMOKE.txt` (content `gascity works`)
  landed in the **rig root**. Bead `uoi-krm` closed; the session slept.
- Full loop proven: **sling → spawn → route → execute → integrate → commit → sleep**, zero
  hand-launching, zero Claude tokens (codex did the work). This is the core of the riskiest-assumption
  test, and the early signal is positive (a handful of commands; agents idle at rest).

## The dependency error, and a corrected diagnosis (bead `claude-workflow-setup-85t`)

During `gc sling`, the auto-convoy dependency-link failed:
`Error 1105: table "d" does not have column "depends_on_id"`. `bd dep list` reproduced it.

**Initial diagnosis (WRONG):** "the rig's beads DB is missing `depends_on_id`; the city's has it;
`gc rig add` emitted a stale schema." This was based on querying the **on-disk dolt repo directly**,
which is **stale** relative to bd's live server connection — the classic stale-read trap.

**Corrected diagnosis (via `bd sql`, the live source of truth):**
- The error is **not rig-specific and not a missing column.** It fires on **any bead with
  dependency rows, in *both* stores** — the *city* bead `gh-wap` throws the identical error.
- Live column lists: the **rig's** `dependencies` table HAS `depends_on_id` (col 11); the **city
  `hq`** does **not**. The schema was migrated to split `depends_on_id` into
  `depends_on_issue_id` / `depends_on_wisp_id` / `depends_on_external`.
- The `bd dep`-with-metadata query in this **bd 1.0.4 dev build (`ce242a`)** still references the
  old `depends_on_id` on a JOIN alias `d` that no longer carries it. **This is a bd dev-build query
  bug, triggered whenever dependencies exist** — it affects convoys and (critically) `mol-feature`
  step-deps everywhere, not just this rig.

**Why Option A was withdrawn:** the chosen fix was "surgically `ALTER` the rig table to add the
missing column." But the column is not missing (the rig already has it), and an `ALTER` cannot fix a
**query** that references a removed column name on a join alias. Running it would have changed schema
for no effect and muddied the real story. **No `ALTER` was run.**

## The real fix (user's bd-version decision — not done here)

The defect is in bd itself, so it's squarely the version-gated decision:
1. **Move off the `ce242a` dev build to a clean stable bd 1.0.4** (already recommended in the
   version-gating note) and re-test — most likely the dev branch carries this query/schema skew.
2. **`bd migrate`** to reconcile the schema (lower risk on 1.0.4 than 1.0.5, but still a migration).
3. **Report upstream** — the dep-with-metadata query references a removed column.

**Not** an upgrade to 1.0.5/1.0.6: 1.0.6 (the corruption fix) is not released; 1.0.5 is the gated
corrupting version.

## Net status
- gascity adoption mechanics: **validated** (rig runs real codex work hands-free).
- Dependency-bearing work (convoys, `mol-feature` step-deps): **blocked by a bd dev-build bug**,
  everywhere — must resolve the bd-version question before running the molecule pipeline through any rig.
- Single-task slings: **work fine today.**

## Addendum (2026-06-07) — the dep bug is a version incompatibility, not a column gap

Attempting the fix surfaced the true root cause and an incident:

1. **Schema gap mapped:** `hq` was missing `depends_on_id` on BOTH `dependencies` and
   `wisp_dependencies`; the rig `uoi` had it on both.
2. **Partial fix applied + kept:** added `depends_on_id` (nullable) to the two `hq` tables.
   This made dependency **reads** succeed and **stopped the continuous dep-query error flood
   that was flapping the shared dolt server** — a real stability win, so it was left in place.
3. **But writes still fail at a deeper layer:** `bd dep add` errors — on the rig because
   `depends_on_id` is a **generated column** ("value not allowed"); on `hq` because it trips a
   **`ck_dep_one_target` CHECK constraint**. The dependency schema (typed targets
   `depends_on_issue_id` / `_wisp_id` / `_external` + `ck_dep_one_target` + generated
   `depends_on_id`) is **newer than bd 1.0.4's `dep add` code**, which writes `depends_on_id`
   directly. **bd 1.0.4 cannot insert a dependency satisfying the gascity-created schema.**
4. **Conclusion:** this is a **version incompatibility** between the pinned **bd 1.0.4** and
   **gascity 1.2.1's beads schema**, not a hand-patchable column gap. Going deeper (dropping
   `ck_dep_one_target`, converting generated columns) is escalating schema surgery on a live,
   corruption-sensitive store — **stopped deliberately.**
5. **Incident (recovered):** running `bd` test commands briefly destabilized the shared dolt
   server (auto-start race → stale `uoi` lock). It self-healed via the supervisor; the
   `reticle` and `cake` dolt servers (other projects) were never touched.

**Real fix — the bd-version decision (user-owned):** bd **1.0.6** when it ships (corruption fix)
then upgrade; OR a gascity/beads version whose `dep add` matches the schema; OR report upstream.
Not 1.0.5 (gated/corrupting). Until then: single-task slings work; **dependency-bearing work
(convoys, `mol-feature` step-deps) is blocked.**

**State left behind (interim):** `hq` carried two added nullable `depends_on_id` columns. (See
RESOLUTION below — these were dropped once 1.0.5 was activated.)

## RESOLUTION (2026-06-07) — activated bd 1.0.5, single-machine-safe

The version incompatibility was the whole story, and the user confirmed **no second machine**,
which removes the only 1.0.5 danger:

- **The 1.0.5 risk (issue #4259 / migration 0043)** forks the `dependencies` primary key and only
  corrupts on **multi-machine** sync (2+ clones both upgrade + cross-machine `bd dolt pull`).
  Exposure audit: only **cake** has a dolt remote (`refs/dolt/data`); gascity (`hq`/`uoi`),
  claude-workflow-setup, and reticle have none. With **no second machine**, the fork cannot occur.
- **Fix applied:** moved the two 1.0.4-dev binaries aside (`~/.local/bin/bd.1.0.4dev.bak`,
  `~/bin/bd.1.0.4dev.bak`) so brew's **bd 1.0.5** (`/opt/homebrew/bin/bd`) is active. Backed up
  gascity + cake dolt stores first (`/tmp/bd-backups-1780827410`).
- **Verified working:** `bd dep add` + `bd dep list` round-trip on **both** the rig (`uoi`) and
  `hq` (*"✓ Added dependency … (blocks)"*); the dolt-server error flood / flapping is **gone**
  (0 `depends_on_id` errors); server stable. No migration was needed (stores were already
  post-0043). Then **dropped** the two vestigial `hq` `depends_on_id` columns — deps still work
  (1.0.5 uses the typed target columns), so `hq` is back to its original schema.
- **Net:** dependency-bearing work (convoys, `mol-feature` step-deps) is **fully functional**.
  Bead `claude-workflow-setup-85t` closed.

### 🚨 Forward constraint while on 1.0.5
Do **not** add a second machine that syncs beads, and do **not** cross-machine `bd dolt push/pull`
— especially **cake** (the only cross-machine-synced store) — until **bd 1.0.6** ships. Doing so
risks the 0043 PK fork. Do **not** revert to 1.0.4 (re-breaks gascity deps). Both recorded in the
`beads-version-gating-2026-06` memory.
