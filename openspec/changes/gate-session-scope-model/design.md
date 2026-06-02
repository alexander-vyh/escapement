# Gate Session-Scope Model

**Bead:** `claude-workflow-setup-858`
**Status:** design (panel `scope-panel`: architect / adversary / bureaucracy / implementer)
**Lands after:** PRs #12 (worktree false-allow), #13 (Stop messages drive continuation), #14 (validate_no_shirking ignores prose/docs edits).
**Problem framing:** see `problem-framing.md` (confirmed by team-lead).

## Problem

The continuation-harness Stop gate (`harness/bin/stop_hook.py`) blocks a session from
stopping while beads work is in-flight. It does this in one of two ways:

1. **Scoped path** — `_check_task_mode_queue(session_mode)` (stop_hook.py:128). When
   `session_mode.json` exists (written by `task_mode_entry.py` on the first `bd ... --claim`
   the PreToolUse hook sees), the gate runs `bd ready --parent <parent_id>` /
   `bd list --status=in_progress --parent <parent_id>`. **`parent_id` is the bead's
   *immediate* parent, NOT the molecule root** — `_lookup_parent_id` reads exactly
   `data.get("parent_id") or data.get("parent")` from one `bd show`, one level up (verified
   against source, 2026-06-02). For a standalone leaf the scope is the `task_id` itself. The
   one-level lookup is **FN-1** (the grandchild hole, Adversarial Review): `bd ready --parent`
   is transitive *downward*, but the parent *lookup* is one level *up*, so a deep molecule
   (epic → sub-epic → leaf) scopes to the sub-epic and misses ready siblings under other
   sub-epics — a premature-stop false-negative the design must close.

2. **Unscoped path** — `_check_bd_queue_implicit(cwd)` (stop_hook.py:210). When
   `session_mode.json` is **absent**, the gate runs `bd list --status=in_progress` and
   `bd ready` **repo-wide** and blocks if either is non-empty.

The unscoped path is the defect. It cannot tell **(a)** beads that ARE this session's
just-decided work from **(b)** unrelated backlog or other sessions' long-running epics.

> **Real incident (reported by the user/team-lead this session [reported, not independently
> reproduced]):** a session that had *completed* its actual work was Stop-blocked because the
> repo had ready backlog (`uf5`, `7ki`, `385`) plus an unrelated in-progress epic (`a2n`) —
> **none of which were in the session's scope**. The gate had no model of session scope, so
> any non-empty repo queue read as "you're not done." The code path is verified by inspection.

`session_mode.json` is absent precisely in the cases that matter most:

- The `bd ... --claim` was issued **inside a subagent**, whose Bash calls do not fire the
  *parent* session's PreToolUse `task_mode_entry` hook.
- No explicit `bd update <id> --claim` command was ever visible to the PreToolUse matcher
  (e.g. the session read `bd ready`, reasoned, and worked without a literal claim string).

So the gate needs a real **model of session scope**: executing decided work is rewarded
(the gate keeps the session going), and unrelated backlog generates **no** spurious
stop/continue pressure.

### Problem 2 — shirking meta-false-positive

`claude/hooks/validate_no_shirking.py` keyword-matches dismissive phrases ("pre-existing
failure", "unrelated to our changes", "CI issue", "infrastructure problem") in the agent's
**own** prose and blocks Stop / denies the tool call. It already strips code spans
(`_strip_code_spans`), ignores quoted mentions (`_inside_quotes`), and honors in-clause
negation (`_negation_guards`) — collectively `_is_guarded`.

The residual gap: the gate fires when the agent is **discussing a false positive of this
very gate** (e.g. "the shirking gate flagged my use of 'unrelated' but I was describing the
codebase, not deflecting") rather than actually shirking. Meta-discussion of the gate is not
shirking; today it can trip the gate.

### Primary risk (weights every decision below)

The whole point of the harness is to **not let sessions stop prematurely**. A scope model
that is too **narrow** re-introduces premature stops — a **false-negative** (gate allows Stop
while real in-scope work remains). We weight false-negatives **above** false-positives
(spurious continue pressure). When scope is *unknown*, the design must fail toward the
option that least risks stranding real work, while not re-creating the unscoped-block FP.

## Options

Verified capabilities the options draw on:

- `session_id` is present in the hook **payload** (`payload["session_id"]`) for both the
  PreToolUse hook (`task_mode_entry.py`) and the Stop hook (`stop_hook.py`). Both derive the
  same `thread_dir = {harness_root}/threads/{session_id}`. This is a **stable per-session key**.
- `bd create` supports `--label`; `bd list` supports `--label` / `--exclude-label` /
  `--created-after` / `--assignee`. Tagging and time-window filtering exist.
- **`bd ready --json` and `bd list --json` both carry `created_at` per item** (verified live
  2026-06-02). So a session-start *watermark* can separate session-fresh beads from backlog
  with **no new bead schema** and **no command interception**.
- A **`SessionStart` hook is already wired** (`claude/settings.template.json`;
  `mol_status_check.py` / `session_status.py` run on it). A watermark write at session start is
  cheap and universal (fires even for non-task sessions that never claim).
- The harness `bin/` is deployed to `~/.claude/harness/bin/` and is **state-only** — it
  cannot import repo modules like `claude/hooks/_gate_signal.py`. Scope state must live in
  the thread dir; signal persistence options are constrained accordingly (see Bureaucracy Review).

| Option | Mechanism | Where state lives | How gate reads it | Key failure modes |
|---|---|---|---|---|
| **A — Session-label tag** | At claim/create, write `session:<sid>` label to the bead | The bead itself (shared Dolt DB) | `bd list --label session:<sid> --status=in_progress` + `bd ready` ∩ label | Mutates **shared DB from a hook** (cross-session side effect, Dolt write contention); ready-but-unclaimed work can't be pre-labeled → "decided not-yet-claimed" invisible; label cruft accumulates |
| **B — Time-window (`entered_at`)** | Scope to beads created/updated since `entered_at` | `entered_at` (in session_mode.json — only written on claim) | `bd list --created-after <entered_at>` | `entered_at` only exists for *task-mode* sessions (claim required); the unscoped path has no watermark. Superseded by Option E (universal SessionStart watermark). |
| **C — Extend parent-scope to implicit path** | Reconstruct `parent_id` scope when session_mode.json is absent | session_mode.json (when it exists) | `bd ready --parent <reconstructed>` | The FP case **is** the absent-manifest case — there is no `parent_id` to reconstruct from. Solves nothing for the actual incident |
| **D — Explicit session manifest** | Append every claimed/created bead id to a per-session manifest | `{thread_dir}/session_scope.json` (per-session, **not** shared DB) | For each manifest bead, check still-open/in_progress; block only on those | Depends on **intercepting** a `bd create`/`bd claim` Bash command → a zero-claim or never-claim session (FN-3 / G-1) and subagent/MCP creates produce no manifest entry. Gameable by avoiding the matched verb. |
| **E — Watermark (`created_at`)** ⭐ | Watermark = `contract.created_at` when a contract exists (already stored, init_contract.py:98), else a SessionStart-written timestamp; the implicit path keeps a queue item only if `created_at >= watermark` | `contract.json` (reused) → else `{thread_dir}/scope_watermark.json` (per-session, not shared DB) | filter `bd list`/`bd ready`/`bd list --status=open` `--json` by `created_at >= watermark` | A bead **created in a prior session** but worked in this one reads as backlog → not blocked on (under-block). This is the **acceptable** failure direction (under-nagging on backlog is the bug being fixed), not premature-stop on *this session's* decided work. |

**Adler–Borys trade per option (bureaucracy reviewer's mapping).** A trades **Global Transparency**
(hidden shared-DB side effects) and **Flexibility** (can't pre-tag decided-but-unclaimed work). B
trades **Repair** (silent timestamp exclusion → premature stop the agent can't easily detect) — and
its `entered_at` only exists for claim sessions. C trades nothing useful (a no-op for the actual
incident). D trades a small **Internal-Transparency** cost (the agent must know the manifest exists)
for full **Repair + Flexibility** — but is still command-interception-bound (FN-3/G-1). **E (chosen)**
pays the *same* small Internal-Transparency cost as D (the agent must understand `created_at` scoping)
for full Repair + Flexibility, and is **strictly better on Global Transparency** than D — there is no
manifest file to even presence-check, the signal is the system-assigned `created_at`. The
advisory-allow default trades a sliver of premature-stop risk for not-trapping unknown-scope sessions
— correct given the false-negative > false-positive weighting. (Reviewer reviewed the pre-pivot doc
and picked D as the most-enabling of A–D; the watermark pivot keeps every property they valued in D
and removes D's command-interception weakness, so the verdict carries to E.)

**Repair, E vs D — E is simpler, not weaker (reviewer's on-the-record reasoning).** D's Repair
strength was live-revalidation: the manifest caches bead ids and the gate re-checks each one's live
`bd` status at Stop time, so a stale entry self-heals on read. That is a good Repair property — but it
exists *because* D carries mutable cached state that **can** go stale; it repairs a problem the
mechanism itself introduces. E carries **no cached state**: the watermark is one system-assigned
timestamp and the gate reads live `bd` queue status filtered by it, so there is nothing to desync and
nothing to self-heal. E's one failure class is not a staleness bug but a **boundary judgment** (a
bead's `created_at` falls just on the wrong side of session-start — exactly the NS-2 case), and a
boundary misfire is repaired by the **same first-class wakeup escape** the design already validated
under Rule 1 (the agent recognizes the in-scope-but-pre-watermark work and drains it or files
beads + ScheduleWakeup). So E owes **no new repair machinery and no cache-coherence surface**. Net
Adler–Borys: Global-Transparency and Rule-3/mock-resistance **strictly better** for E; Internal
Transparency and Flexibility **equal**; Repair **equal-or-better** for E (fewer moving parts). The
manifest as a *deferred fallback that the gate does not block on* preserves this; promoting it to a
gate-blocking mechanism would re-introduce the cached-state surface and re-incur D's
value-validation + per-entry-signal story (the standing bureaucracy caveat, gated on the NS-2 verdict).

## Recommendation

**Hybrid E + root-walk + capability-probe.** The **SessionStart watermark (Option E)** replaces
the unscoped block in `_check_bd_queue_implicit`; a **transitive root-walk** fixes the task-mode
parent-scope path (FN-1); and a **capability probe** fixes the implicit path's worktree
false-allow (E-1). The explicit manifest (Option D) is **deferred to Option-B-of-last-resort** —
built only if the watermark's prior-session under-block proves a real problem.

This is a **revision from the v2 manifest-primary recommendation**, driven by the implementer's
cost analysis and a coverage comparison: the watermark **strictly dominates the manifest on the
two seams the manifest could not close**. The manifest depends on *intercepting* a `bd create` /
`bd claim` Bash command, so it produces no scope for a **zero-claim session (FN-3)** and is
**gameable by avoiding the matched verb (G-1)** — both of which I had to list as acknowledged
residuals. The watermark reads `created_at` off the *live queue*, so it needs no command
interception: it covers the zero-claim session and cannot be gamed by avoiding claims. It also
closes FN-4 more cleanly (a session-filed bead has `created_at >= watermark` natively, no
interception). The manifest's *only* advantage — catching a bead created in a prior session and
re-worked now — is exactly the case the watermark deliberately treats as backlog (the acceptable
under-block direction). So the watermark is the better default and the manifest is the fallback,
not the reverse.

Rationale, tied to the primary-risk weighting and the FN seams:

1. **The watermark separates session-fresh from backlog with no schema change and no
   interception.** `bd ready --json` / `bd list --json` carry `created_at` (verified live). A
   universal SessionStart watermark (written even for non-task sessions) lets
   `_check_bd_queue_implicit` keep only items with `created_at >= watermark`. This closes the
   `a2n` over-block (those beads predate the session ⇒ filtered out as backlog) **and** covers
   **FN-3** (zero-claim session: the filter works with no claim) and **G-1** (not gameable by
   avoiding the claim verb). Side-effect-free: the watermark lives in the thread dir, never
   mutating the shared Dolt DB (rules out Option A).

2. **The watermark closes FN-4 (the inversion the bead names) — *if* the query set includes
   `open`.** A bead the agent files this session and that sits `open` with **unmet deps** appears
   in neither `bd ready` (ready excludes blocked) nor `bd list --status=in_progress`. So the
   implicit-path query set MUST be **`{in_progress ∪ ready ∪ open}`, each filtered to
   `created_at >= watermark`** — only then does a session-filed *blocked* bead still drive the
   block. Filtering only `ready`+`in_progress` re-opens FN-4. *(Confirmation of the exact query
   set requested from the implementer; this is the line between closing FN-4 and re-opening it,
   and is the panel's PRIMARY risk.)*

3. **Transitive root-walk fixes FN-1 for the task-mode path.** `_lookup_parent_id` gets a loop:
   `bd show` up the `parent_id` chain until `parent_id` is null, store the **root**.
   `bd ready --parent <root>` is transitive downward, so root-down covers the whole molecule —
   closing the grandchild hole for sessions that claim. (~10 lines; recommended *inside* the
   walking skeleton because it is a live premature-stop, not a fast-follow.)

4. **Capability-probe fixes the implicit path's worktree false-allow (E-1).** Line 223 hard-allows
   on a missing `.beads/` dir — the *exact directory-proxy bug PR #12 fixed only in the task_mode
   path* (verified still live at stop_hook.py:223-224). Replace it with the same **bd-capability
   probe** (run bd; degrade only on bd *failure*, not on a missing dir), so a worktree (no dir,
   bd resolves via redirect/BEADS_DIR) is correctly gated. With the watermark scoping the queue,
   the implicit path now *blocks on session-fresh work* and *allows on backlog* — it is no longer
   an unconditional advisory-allow, so in-scope work in a no-claim session is still caught.

**Note on "advisory downgrade":** the v2 framing downgraded the whole implicit block to advisory
`allow`. With the watermark, that blanket downgrade is **no longer needed or correct** — the
watermark makes the implicit path *precise* (block on session-fresh, allow on backlog) rather than
*off*. Advisory-allow survives only as the degradation path when bd itself fails or no watermark
exists (e.g. a session that started before this feature shipped).

**Problem 2 fix:** add a `_STRONG_META_CUES` branch to `_is_guarded` (validate_no_shirking.py:606)
that suppresses a match even *unquoted* when a **detector-naming** cue is present — keying on the
gate's own vocabulary (`"shirking"`, `"the hook"`, `"false positive"`, `"validate_no_shirking"`),
**not** the dismissive category words. No existing pattern is loosened. See Implementation Plan
Step 3 and the Bureaucracy Review (never-suppress guardrail + NC-5).

## Adversarial Review

The `adversary` reviewed the source before this design landed and surfaced six false-negative
seams (premature-stop = the original bug = rank-1 danger), three gaming vectors, and several
edge cases. Each is listed with its **verification status** and the **concrete code path** that
closes it. The adversary's standing bar: *"not passing anything until the grandchild hole and
the filed-but-unclaimed hole are both closed."*

> **Pivot note:** after the implementer's cost analysis, the primary mechanism changed from the
> manifest (Option D) to the **SessionStart watermark (Option E)**. The watermark *closes* FN-3
> and G-1 outright (it reads `created_at` off the live queue — no claim/create interception, not
> gameable by avoiding the verb), which the manifest could only list as residuals. The pivot
> introduced a **new attack surface** (NS-1/NS-2/NS-3, in Deferred/residual) — the watermark's
> prior-session under-block — which is **under active adversary review**; if the resumed-molecule
> case (NS-2) proves a real premature-stop, the manifest returns as a *companion*, not a fallback.

### False-negative seams (rank-1 — premature stop)

- **FN-1 — grandchild hole [CONFIRMED against source].** `_lookup_parent_id` reads exactly one
  level (`data.get("parent_id") or data.get("parent")`). A deep molecule scopes to the
  immediate parent and misses ready siblings under other branches. **Closed two ways:** (a) the
  implicit watermark path does not walk parents at all — it filters the whole queue by
  `created_at`, so grandchildren under any branch are caught if session-fresh; (b) the
  `_check_task_mode_queue` path gets a **transitive root-walk** in `_lookup_parent_id` (loop
  `bd show` up the chain to the root), so `bd ready --parent <root>` covers the whole molecule.
  *Open adversary question:* a DAG-shaped molecule (a bead with multiple parents) where the
  root-walk picks the wrong root — flagged for the adversary's verdict; the watermark path is
  immune (no walk), so the DAG risk is confined to the task-mode parent-scope path.
- **FN-2 — first-claim-wins pins the wrong scope [CONFIRMED behavior].** If the first claim is
  an incidental chore, scope is pinned to its parent. **Closed by the watermark** (the implicit
  path no longer depends on `session_mode.json`'s pinned parent — it filters the whole queue by
  `created_at`, so claim order is irrelevant). `session_mode.json`'s first-claim-wins now only
  anchors `repo_cwd`. For the task-mode path, the root-walk (FN-1) also reduces the blast radius.
- **FN-3 — the no-claim / zero-claim session [NOW CLOSED by the watermark].** Previously an
  acknowledged residual under the manifest design (the manifest needs a claim/create command to
  populate). The watermark needs **no** command: it filters the live queue by `created_at`, so a
  session that files in-scope work without ever claiming still blocks on that fresh work. Closed.
- **FN-4 — filed-but-unclaimed in-scope beads [the inversion the bead names].** Beads the agent
  files this session that sit `open` with unmet deps are returned by neither `bd ready` nor
  `bd list --status=in_progress`. **Closed by the watermark *iff* the query set includes
  `--status=open`:** the implicit path's candidate set is `{in_progress ∪ ready ∪ open}` filtered
  to `created_at >= watermark`, so a session-fresh blocked bead survives the filter ⇒ blocks.
  This is "created/decided this session" expressed as `created_at` off the live queue — no command
  interception. **NC-2 enforces the `open` inclusion** (a query set without it re-opens FN-4).

### Gaming vectors (rank-2)

- **G-1 — never-claim easy stop [NOW CLOSED by the watermark].** The watermark does not depend on
  any voluntary claim/tag/create command — it reads `created_at` off the live queue. An agent
  cannot escape scope by avoiding the claim verb: its session-fresh beads are still caught by the
  timestamp filter. Closed (was a residual under the manifest).
- **G-2 — claim-then-drop.** Un-claiming (`status → open`) does not hide the bead from the
  watermark: the candidate set includes `--status=open`, and the bead's `created_at` is unchanged,
  so a dropped-to-`open` session-fresh bead still blocks. *Claimed closed; pending adversary
  confirmation.*
- **G-3 — tag something tiny.** N/A under the watermark — there is no agent-authored tag/manifest to
  poison. Scope is `created_at` (system-assigned, not agent-controllable). The gaming vector
  evaporates with the manifest it targeted (gate-design.md Rule 3: the value is system-validated).

### False-positive / coercion (rank-3)

- **FP-1 / FP-2 — the `a2n` over-block.** The unscoped implicit path blocks on a cross-session
  `in_progress` epic + unrelated ready backlog. Closed by the manifest (those beads were never
  in scope) + the advisory downgrade for the no-manifest case. The adversary's sharpest point:
  *narrowing this is exactly how FN-1..FN-4 get created* — which is why a **positive scope signal**
  (now the watermark, formerly the manifest) is load-bearing rather than a naive "scope the implicit
  path by parent_id" (that would inherit the grandchild hole).

### Edge cases (each with a stated answer)

- **E-1 — implicit-path worktree false-allow [CONFIRMED still live at stop_hook.py:223-224].**
  PR #12 fixed the directory-proxy only in the task_mode path; the implicit path still
  hard-allows on missing `.beads/`. **Closed:** replace with the bd-capability probe (degrade
  only on bd failure) in the same change.
- **E-2 — subagent claims.** A subagent's bd action runs under its own session_id → a different
  thread dir → the parent never sees it. **Under the watermark this matters less:** a subagent that
  *creates* a session-fresh bead is caught by the timestamp filter regardless of which thread
  created it (the bead's `created_at` is after the parent watermark). The residual is subagent
  *claim attribution*, which the verified `HARNESS_THREAD_DIR`-as-rung-#1 mechanism
  (would_block_stop.py:163, keyed for "named subagents") can close at dispatch time. Deferred.
- **E-3 — compaction / restart split-brain [NOW LOAD-BEARING].** `stop_hook` reads
  `payload["session_id"]`; `init_contract` reads `CLAUDE_CODE_SESSION_ID` env. The **watermark MUST
  key the same thread dir the Stop hook reads** — if SessionStart/Stop `session_id` and
  `CLAUDE_CODE_SESSION_ID` diverge, the watermark is written to one dir and read from another ⇒
  silently disabled. **Implementer to verify equality**; if not guaranteed, key all off
  `HARNESS_THREAD_DIR` when set. Also see NS-3 (resume-with-new-session-id) in Deferred/residual.
- **E-4 — "created this session" mechanism.** Answered above (FN-4): **`created_at >= watermark`**
  off the live queue — system-assigned timestamp, no command interception, so the MCP/non-Bash
  create concern that applied to the manifest is moot. The watermark sees any bead the queue
  reports, regardless of how it was created.

**Status:** FN-1, FN-2, FN-3, FN-4, G-1, G-2, G-3, E-1 closed in-design (the watermark pivot closed
FN-3 and G-1 that the manifest left residual); E-3 is now load-bearing (implementer-verify); the
**new watermark surface NS-1/NS-2/NS-3 is under active adversary review** (Deferred/residual). The
adversary's two blocking bars — the grandchild hole (FN-1) and the filed-but-unclaimed hole (FN-4)
— are both closed.

## Bureaucracy Review

The `bureaucracy` reviewer evaluated the design against `gate-design.md`'s three rules and the
four bureaucracy failure modes. **Its central principle decided the Cluster-2 pivot:** *"favor a
scope signal the gate can DERIVE rather than one the agent ASSERTS — derived = not game-able =
not mock."* It named `created_at`/`updated_at` within the session window as a preferred derived
signal, and flagged any agent-written session-tag as *the agent grading its own homework* — the
**mock-bureaucracy** failure mode by construction. This is the decisive argument for the
watermark over the manifest, independent of the implementer's cost argument: the manifest, even
though it is system-populated from observed commands, is closer to an agent-controllable assertion
than the watermark's system-assigned timestamp.

- **Rule 3 (validate value, not presence) — the hard test, PASSED by the watermark.** The
  watermark is a **derived** signal: `created_at` is assigned by beads, not by the agent. The gate
  reads live queue status, not an agent-written tag. There is no "tag everything / tag nothing to
  control the gate" lever — the mock-bureaucracy vector the reviewer flagged for any self-tag
  scheme **does not exist** here. (Had the manifest been primary, it would have needed the
  reviewer's full value-validation + per-tag-signal story; the watermark sidesteps it.) The
  reviewer's follow-up sharpened the *source*: the watermark reuses **`contract.created_at`**
  (already stored, init_contract.py:98) when a contract exists — no new field, reusing a mechanism
  that already passes review.
- **Must-drain vs may-defer (avoids coercive drift on backlog).** The reviewer's split is adopted:
  session-fresh (derived in-scope) beads are *must-drain-or-ScheduleWakeup*; out-of-scope ready
  backlog is **allow stop — do not block, do not drain**. Draining backlog is the scope-creep the
  harness already warns against at stop_hook.py:204; the watermark must never turn "the repo has
  backlog" into "go work the backlog." (See Implementation Plan Step 2.)
- **Rule 1 (first-class escape) — VERDICT: existing escapes suffice; NO new waiver file.** The
  reviewer drew a distinction the v2 framing conflated:
  - The **advisory-allow on scope-UNKNOWN** (no watermark, no contract) is a **fail-open DEFAULT**,
    not an escape — the gate declining to block when it can't prove scope. Correct, and it satisfies
    Internal Transparency *iff the message says why* ("scope unknown — not blocking, but in-scope
    work may remain"). Keep it; do not call it "the escape."
  - The **escape from an actual block** (a session-fresh bead is open) is the two universal overrides
    — **user-release** and **ScheduleWakeup** — already first-class, agent-invokable, wired
    (would_block_stop.py:142-145), and structurally validated (future-date / bd existence). That
    fully satisfies Rule 1. **No third escape is needed.** Crucially, **ScheduleWakeup is itself the
    reason-carrying state-only waiver**: a scheduled entry persists a `prompt` (the intent — the tool
    accepts `prompt` or `reason`, schedule_wakeup_bridge.py:143) AND **re-invokes the agent** with
    that prompt when it fires. So the "reason" is not logged-and-forgotten — it is *actionable
    resumption state*. That is strictly better than a `scope_release.json` reason file, which would
    log a reason and then let the agent walk away.
  - `scope_release.json` is **REJECTED** (see Deferred/residual): an agent-authored reason file the
    gate can only presence-check is mock-bureaucracy with maximal game incentive, and it is strictly
    unnecessary — ScheduleWakeup is the state-only waiver analogue and already exists. The coercion
    guard is the wakeup escape (checked *before* the scope check), so a long session's legitimate
    pause is a sanctioned signal-producing path, not a nag. This is **Cluster-1 Candidate-A**
    (Step 4): A over B (louder nag, Rule-1 fail) and C (forced turn, no escape).
- **Rule 2 (persistent signal) — VERDICT: incidents.jsonl sufficient, with TWO requirements.**
  `gate-design.md` Rule 2 explicitly lists "append-only log file" as acceptable; `incidents.jsonl`
  qualifies and is the correct state-only substitute for the un-importable `_gate_signal.record()`.
  Requirements:
  1. **Emit `scope_decision` on EVERY path, including advisory-allow** — values
     `scope_fresh_block` / `scope_backlog_allow` / `scope_no_watermark` / `scope_bd_failed` /
     `scope_drained`, plus `scope_wakeup_pause` for the Cluster-1 pause. The **advisory-allow count
     IS the half-life metric** that tells us whether the scope-unknown blind spot is rare (keep
     fail-open) or common (escalate). Logging only the block path makes the load-bearing metric
     uncountable.
  2. **Don't split the corpus silently [verified gap with a SCHEDULED consumer].** The half-life
     tooling (`claude/bin/gate_signal_query.py` / `gate_signal_analysis.py` / `gate_signal_monitor.py`)
     reads `.beads/.gate-signal.jsonl` (monitor.py:82-89, every repo); `incidents.jsonl` is read
     **only** by `stop_hook.py` + `INSTALL.sh` today. Crucially, `gate_signal_monitor.py` runs on a
     **schedule** via an installed launchd job (`~/Library/LaunchAgents/com.alexv.gate-signal-monitor.plist`,
     verified present, sourced from `claude/launchd/`). So scope decisions appended only to
     `incidents.jsonl` are invisible to a *running automated monitor*, not merely an ad-hoc review —
     the very metric this `scope_decision` field exists for would never be seen.
     **Chosen fix — Option 2 (write to BOTH, one corpus):** `stop_hook.py` ALSO appends the scope
     decision to `.beads/.gate-signal.jsonl` in the existing append-only line shape. `bin/` cannot
     import `_gate_signal.record()`, but the line format is trivially replicable — verified shape is
     `json.dumps({"gate", "decision", "reason", ...}) + "\n"` (_gate_signal.py:9-40). So stop_hook
     writes the same `{gate: "session_scope", decision: <scope_decision>, reason, ...}` line directly.
     Alternatives considered: Option 1 (point the three query tools at `incidents.jsonl` too — fine,
     but three readers to change); Option 3 (document the second corpus in the runbook — weakest,
     relies on a human remembering two files). Option 2 keeps ALL gate signal in one corpus so the
     scheduled monitor "just works." **Bonus (reviewer-verified):** `incidents.jsonl` already carries
     a `was_correct` field — the exact label half-life review wants — so `scope_decision` slots in
     cleanly on the incidents side too.

### Problem 2 (meta-FP) — bureaucracy verdict + a verified precision

The reviewer correctly identified the existing guards and the residual. One claim needed a
precision check, now verified against source:

- **`_HOOK_SIGNATURES` (line 160, used at line 840) is real but path-scoped.** It skips an entire
  assistant message that contains the hook's **own block-output signatures** (e.g.
  `"outcome-ownership.md"`) so the hook does not re-fire on its own denial text echoed into the
  transcript (self-poisoning prevention). It does **NOT** cover the agent *reasoning about* the
  gate in its own unquoted prose without reproducing those signatures. So the `_STRONG_META_CUES`
  fix is **complementary, not duplicative** — it closes the residual the reviewer named (unquoted
  discussion of the gate's category words while explaining a prior fire).
- **Never-suppress / oracle-downgrade guardrail (the reviewer's hard bar, ACCEPTED).** The fix must
  NOT widen into a false-negative hole. The design satisfies this because `_STRONG_META_CUES` names
  the **detector** (`"shirking"`, `"the hook"`, `"false positive"`, `"validate_no_shirking"`), NOT
  the dismissive category words (`"pre-existing"`, `"unrelated"`, `"CI failure"`). The mandatory
  negative control the reviewer requires — *genuine unquoted shirking still fires* — is locked as
  NC-5 and the two canonical strings (*"pre-existing failure, not from my change"*, *"OOM, unrelated
  to my fix"*) MUST still block. A guard that "skips any message mentioning shirking concepts" is
  explicitly rejected; the cues are detector-naming only.

**Net bureaucracy verdict:** the watermark is the *enabling* design (derived signal, no
self-grading, wakeup escape stays first-class); the manifest would have been the weaker,
mock-risk option requiring extra value-validation machinery. The `_STRONG_META_CUES` fix is sound
provided the detector-naming constraint and NC-5 hold. No coercive-drift because the wakeup escape
precedes the scope check.

## Implementation Plan

Ordered, with the testable seam named for each. Smallest-viable-cut first; the walking
skeleton is steps 1+2+2b+2c (watermark scope + root-walk + capability-probe) — that alone
resolves the reported incident and closes FN-1/FN-3/FN-4/E-1.

### Step 1 — Watermark source (reuse `contract.created_at`; SessionStart writer as fallback)
- **Primary source — the contract (verified, bureaucracy reviewer's find).** `contract.json`
  already stores `created_at` (ISO8601 UTC, init_contract.py:98) and `thread_id` per session
  (live contract keys confirmed: `created_at`, `goal`, `thread_id`, `verification_command`, …).
  When a contract exists, the implicit path uses **`contract.created_at`** as the watermark — no
  new field, no new file, and it aligns the watermark to the same session anchor the contract
  uses. This is the leanest path and the reviewer's preferred derived signal.
- **Fallback — SessionStart writer for contract-less sessions.** A session that never declares a
  contract has no `contract.created_at`. For those, a SessionStart hook writes
  `{thread_dir}/scope_watermark.json` (`{"watermark": "<iso8601>", "session_id": "<sid>"}`),
  first-write-wins (a resumed/compacted session keeps its original start). The Stop path reads
  `contract.created_at` first, then `scope_watermark.json`.
- The `SessionStart` payload carries `session_id`; derive `thread_dir` via the existing
  `thread_dir_for_session`. Mirror the existing SessionStart hooks (`session_status.py`,
  `mol_status_check.py`) for the wiring.
- **Risk to verify (E-3):** the watermark (from either source) must key the SAME thread dir the
  Stop hook reads. Confirm `SessionStart` payload `session_id` == Stop payload `session_id` ==
  the `CLAUDE_CODE_SESSION_ID` env `init_contract` uses; if any diverge, key all off
  `HARNESS_THREAD_DIR` when set. (Reusing `contract.created_at` *reduces* this risk: the contract
  is already keyed to its own thread dir, so a contract-bearing session is self-consistent.)
- **Test seam:** unit test for both sources — contract present ⇒ uses `contract.created_at`;
  contract absent + watermark file ⇒ uses the file; both absent ⇒ degradation path (Step 2).

### Step 2 — Watermark-scope the implicit path (`harness/bin/stop_hook.py`)
- `_check_bd_queue_implicit` resolves the watermark by priority: **`contract.created_at` if a
  contract exists, else `{thread_dir}/scope_watermark.json`**. Build the candidate queue as
  **`{in_progress ∪ ready ∪ open}`** via `bd list --status=in_progress --json`,
  `bd ready --json`, and `bd list --status=open --json` — then **keep only items with
  `created_at >= watermark`**. Block iff the filtered set is non-empty; else allow
  (`implicit_queue_scoped_drained`). This closes the `a2n` over-block (backlog filtered out) and
  FN-4 (a session-filed `open`-with-unmet-deps bead survives the filter ⇒ blocks).
- **Must-drain vs may-defer (bureaucracy coercion guard).** The filtered (session-fresh) set is
  *must-drain-or-ScheduleWakeup* before stop. The filtered-OUT (older backlog) set is **allow
  stop — do NOT block and do NOT drain it.** Draining out-of-scope backlog is the exact
  scope-creep the harness already warns against at stop_hook.py:204; the watermark must not turn
  "you have backlog" into "go work the backlog." The wakeup override (checked before this scope
  check) keeps a long session's legitimate pause a first-class allowed path.
  - The three-way union is REQUIRED: dropping `--status=open` re-opens FN-4 (a blocked,
    session-filed bead is in neither `ready` nor `in_progress`). **Implementer confirming the
    cheapest equivalent query** (e.g. one `bd list --status=open,in_progress --json` + `bd ready`,
    or a single `bd list --all --json` filtered in-process) — the *coverage* set is the oracle,
    the exact commands are the implementer's to optimize.
- Degradation: if the watermark file is absent (session predating this feature) OR bd fails,
  degrade to **advisory `allow`** + a logged incident with `scope_decision`
  (`scope_no_watermark` / `scope_bd_failed`) — never a hard block on unscoped backlog.
- **Test seam:** extend `test_task_mode_queue.py` with a fake `run_bd` returning items with
  `created_at` before/after a fixture watermark. Required cases: incident replay (only
  pre-watermark backlog ⇒ `allow`); FN-4 (a post-watermark `open` blocked bead ⇒ `block`);
  positive control (a post-watermark in_progress bead ⇒ `block`).

### Step 2b — Transitive root-walk in `_lookup_parent_id` (`harness/bin/task_mode_entry.py`) — closes FN-1 for the parent-scope path
- Change `_lookup_parent_id` from a single `bd show` to a **loop**: walk `parent_id → parent's
  parent_id → …` until `parent_id` is null; return the **root**. Cap the loop (e.g. 20 hops) to
  prevent a cycle from hanging the hook; on cap-hit, fall back to the last seen id and log.
- DAG caveat (adversary open question): if a bead has multiple parents, the walk picks one path.
  Until resolved, prefer the manifest path (no walk); document the parent-scope path's DAG risk.
- **Test seam:** unit test with a fake `bd show` returning a 3-level chain ⇒ asserts root returned.

### Step 2c — Capability-probe the implicit path (`harness/bin/stop_hook.py`) — closes E-1
- Replace `_check_bd_queue_implicit`'s line 223-224 directory check
  (`if not (repo_path / ".beads").exists(): return ("allow", "implicit_queue_no_beads")`) with
  the **bd-capability probe** PR #12 introduced in the task_mode path: attempt the bd query;
  degrade to allow only on bd *failure* (None response), never on a missing `.beads/` dir. A
  worktree (no dir, but bd resolves via redirect/BEADS_DIR) is then correctly gated.
- **Test seam:** mirror `test_worktree_with_ready_work_blocks` / `test_real_beads_repo_bd_failure_blocks`
  from the task_mode tests onto the implicit path.

### Step 3 — Meta-discussion guard (`claude/hooks/validate_no_shirking.py`)
- **Current behavior (verified, line 606):** `_is_guarded` suppresses a match only when it is
  BOTH `_inside_quotes(...)` AND preceded by a `_META_CUES` hit. So an agent reasoning in its own
  **unquoted** prose — e.g. *"the hook fires on phrases about a CI failure being unrelated"* — has
  no quotes and no negation ⇒ **false positive**.
- **Fix (implementer's sharpened design):** add a `_STRONG_META_CUES` regex and a third branch in
  `_is_guarded` — if a strong meta-cue appears in the window before the match, guard it **even
  unquoted**. Strong cues name the **DETECTOR, not the work**: `"shirking"` (the gate's own name),
  `"false positive"`, `"the hook"`, `"validate_no_shirking"`, `"this gate/check fires on"`,
  `"keyword match"`, `"meta-discussion"`. An agent actually shirking does not say *"the shirking
  hook fires on 'unrelated'"* — so detector-naming cues are safe to guard unquoted; category words
  (`"pre-existing"`, `"unrelated"`) are NOT cues and are never added.
- **REJECTED alternative — "require the disputed phrase QUOTED" (reuse `_inside_quotes`).** The
  bureaucracy reviewer's verdict: this is the wrong tightening. The quoted+meta-cue path ALREADY
  fires today (`_is_guarded` line 606: `_inside_quotes(...) and _META_CUES.search(...)`), so a
  quote-required guard would be **redundant** with the existing guard AND would leave the actual
  residual bug **unfixed** — the bug is *unquoted* meta-discussion of the gate's category words while
  explaining a prior fire. Quote-required guarantees that exact case still false-positives. The
  never-suppress work the quote requirement was reaching for is instead done by guardrail 2
  (clause-break precedence) below, *without* missing the unquoted-meta bug.
- **Never-suppress guardrail (per Rule 3 / never-suppress.md):** because the cues name the detector
  and not the dismissive category, the guard cannot exempt a real deflection. The mandatory negative
  controls (below) prove it: *"This is a pre-existing failure, not from my change."* and *"All three
  jobs died OOM, unrelated to my fix."* MUST still fire (no detector-naming cue present).
- **Three guardrails against the false-negative hole (bureaucracy verdict — REQUIRED):**
  1. **Window-scope the cue.** The detector cue must be PROXIMATE to the match (the same
     `GUARD_WINDOW` window `_is_guarded` already uses), not anywhere-in-message. Otherwise one
     "validate_no_shirking" at the top of a long message blanket-exempts a real shirk 2000 chars
     later. Proximity is what keeps the mixed-message negative control passing.
  2. **Clause-break = assertion wins.** Mirror the clause-break logic in `_negation_guards`
     (line 568): if a clause break (comma/semicolon/colon/dash) sits between the detector cue and
     the match, the meta framing does NOT scope the assertion ⇒ it fires. The cue must be the
     *nearer* anchor to guard.
  3. **Keep `_HOOK_SIGNATURES` separate, don't widen it.** That skip (line 840) is
     `any(sig in text ...)` — a **whole-message substring** check (reviewer-verified) — dropping any
     message containing literal `"validate_no_shirking"`/`"outcome-ownership.md"`. That is already the
     blanket breadth to avoid; `_STRONG_META_CUES` must stay the NARROWER **windowed** guard and must
     NOT be routed through the line-840 whole-message path. They are complementary, not merged —
     folding them together would lose the proximity property guardrail 1 depends on.
- **Test seam:** `claude/hooks/tests/test_validate_no_shirking.py` — call `find_shirking_match`
  directly on the canonical strings (two must-block, one must-allow meta-FP, one already-guarded
  positive) and assert the block/allow pattern. **Plus the mixed-message NC (NC-6):** a single
  message that BOTH discusses the gate AND commits a real unquoted shirk in a *later clause* ⇒ must
  still **block**. This is the case guardrails 1+2 protect and the one a naive implementation
  regresses.

### Step 4 — Cluster 1 pacing-pause escape (`harness/bin/stop_hook.py` message + signal) — sequenced AFTER the Cluster-2 skeleton
- **The escape is already half-wired (verified against source).** `would_block_stop` has three
  allow paths in order (would_block_stop.py:140-145): `verification_passed`, `wakeup_registered`,
  `user_released`. `_wakeup_registered` (line 105) returns allow on any `scheduled.json` entry with
  `wake_at > now`. In task mode, `stop_hook.py:293-295` checks these universal overrides (with
  `contract=None`) and short-circuits to allow BEFORE the queue-drain block. **So a ScheduleWakeup
  already bypasses the queue block today** — the mechanism is live (bead `0wg` fixed the bridge).
  What is missing is that the agent does not *know* filing-beads + ScheduleWakeup is the sanctioned
  pause. Candidate A supplies exactly that, in the denial text.
- The implicit-path display already says the right thing in part (stop_hook.py:204:
  *"do not drain it (that is scope creep) … call ScheduleWakeup if you are waiting on something
  external"*) — Candidate A extends this to name the pause as a first-class allowed path.
- **Candidate A over B/C (bureaucracy verdict).** B (louder nag, no new allowed path) is a Rule-1
  fail → coercive. C (re-block on a no-op turn) adds friction, is bounded by `stop_hook_active` (can
  force only one extra turn), and offers no escape → coercive-leaning. A is the only Rule-1-compliant
  option and reuses an already-wired escape.
- **Mock-bureaucracy caution (REQUIRED both-conditions, per bureaucracy).** The sanctioned pause must
  require BOTH (a) the remaining in-scope beads **filed** (durable in bd) AND (b) a **ScheduleWakeup**
  (future-dated `scheduled.json`). "ScheduleWakeup alone" lets the agent pause-and-evaporate the work
  (the wakeup fires but nothing records WHAT to resume) — the "I'll check back later" prose-as-polling
  stall class the harness exists to kill. Both are structurally validated by existing code
  (`_wakeup_registered` checks the date is future; bd validates the bead exists) — no agent free-text.
- **Signal (Rule 2):** emit a `_gate_signal`-equivalent incident (`scope_decision: pacing_pause`) on
  the pause path so half-life review can count pacing-pause-fires vs genuine completion.
- **Test seam:** `would_block_stop` unit test — a future-dated `scheduled.json` entry ⇒ `allow`
  (`wakeup_registered`) even with a non-empty task-mode queue; assert the pause incident is logged.

### Test Oracle (full 9-section brief required — six negative controls across two files)
- **Business invariant:** a *completed* session is not Stop-blocked by unrelated **prior-session**
  repo backlog; a session with *real in-scope* (session-fresh) work still cannot stop; genuine
  shirking is still caught.
- **Negative controls (mandatory):**
  1. A queue item with `created_at >= watermark` and status `in_progress` ⇒ gate **blocks**
     (session-fresh in-scope work not abandoned).
  2. **FN-4:** a session-fresh (`created_at >= watermark`) bead that is `open` with **unmet deps**
     (so `bd ready` would NOT return it, nor `bd list --status=in_progress`) ⇒ still **blocks**.
     Rejects any implementation whose query set omits `--status=open`.
  3. **FN-1:** task_mode session on a deep molecule (epic → sub-epic → leaf, ready sibling under
     another sub-epic) ⇒ root-walk scopes to the root ⇒ **blocks** on the ready sibling. Rejects
     the one-level-parent implementation.
  4. **E-1:** worktree (no `.beads/` dir, bd resolves via redirect) with session-fresh ready work ⇒
     implicit path **blocks** (capability probe), not allows. Rejects the directory-proxy.
  5. Real shirking prose that mentions the gate ⇒ still **blocked** (meta-guard not a loophole).
  6. **Mixed-message (bureaucracy):** ONE message that BOTH discusses the gate (detector cue present)
     AND commits a real unquoted shirk in a *later clause* ⇒ still **blocks**. Rejects an
     anywhere-in-message meta exemption; forces the windowed + clause-break guardrails (Step 3).
- **Positive controls:** genuine meta-discussion of the gate ⇒ allowed; the `a2n` incident
  (all repo backlog has `created_at < watermark`) ⇒ allowed; a session whose only fresh beads are
  all `closed` ⇒ allowed.
- **Fragile-implementation challenge:** (a) "downgrade *all* implicit blocks to allow
  unconditionally" passes the incident replay but FAILS NC-1 (session-fresh in_progress). (b)
  "filter only `ready`+`in_progress` by watermark" passes the happy path but FAILS NC-2 (FN-4 —
  blocked bead is in neither). (c) "use immediate parent_id" passes a shallow molecule but FAILS
  NC-3 (FN-1). (d) "keep the `.beads/` directory check on the implicit path" passes a normal repo
  but FAILS NC-4 (E-1). (e) "suppress any match containing the word 'gate'" passes the meta
  positive control but FAILS NC-5. (f) "exempt the whole message if a detector cue appears anywhere"
  passes simple meta-discussion but FAILS NC-6 (mixed message). Each fragile shortcut is rejected by
  a named negative control ⇒ the oracle is sound. Six distinct negative controls across two files ⇒
  this is **not** a low-blast-radius change; author the full 9-section Test Oracle Brief.
- **Final outcome verification:** replay the incident fixture (all of `uf5`/`7ki`/`385`/`a2n` with
  `created_at < watermark`) through `stop_hook` ⇒ `allow`; a fresh-filed blocked bead ⇒ `block`;
  run `harness/tests/` + `claude/hooks/tests/` green.

### Continuation-harness contract (for the build session)
```
--goal "stop_hook blocks on session-fresh in-scope work (incl. open-with-unmet-deps) but NOT on prior-session backlog; deep-molecule task sessions block on ready siblings; shirking still caught"
--verify "python3 -m pytest harness/tests/test_task_mode_queue.py claude/hooks/tests/test_validate_no_shirking.py -q"
```

### What the watermark CLOSES that the v2 manifest left open
- **FN-3 (zero-claim session)** and **G-1 (never-claim easy stop)** are now **closed**, not
  residual: the watermark filters the live queue by `created_at`, so it needs no claim/create
  command and is not gameable by avoiding the matched verb.

### Deferred / residual (filed as follow-up beads if accepted)
- **Prior-session in-scope miss (the watermark's accepted under-block).** A bead created in
  session N-1 but worked in session N has `created_at < watermark` ⇒ read as backlog ⇒ not blocked
  on. Accepted failure direction (under-nagging on backlog is the bug being fixed). **Mitigation if
  it proves real:** Option D (explicit manifest) becomes the fallback — re-claiming/touching such a
  bead this session would re-scope it. Build only on evidence. *(New attack surface for the
  adversary: is there a class of legitimately-resumed prior-session work where this under-block is
  NOT acceptable? e.g. a long molecule spanning sessions.)*
- **Watermark granularity vs molecule resumption.** A multi-session molecule's later steps may have
  been *created* before this session's watermark even though they are this session's real work. The
  task-mode path (root-walk, not watermark) covers a *claimed* molecule correctly; the gap is a
  molecule worked **without** a claim that spans the watermark. Flagged for the adversary.
- **E-2 — subagent-claim propagation** (export `HARNESS_THREAD_DIR=<parent thread dir>` into the
  subagent env). Less critical now: the watermark covers subagent-*created* beads (created_at is
  session-fresh regardless of which thread created them, as long as the subagent shares the parent
  thread dir or the bead is created after the watermark). Still listed for the claim-attribution case.
- **E-3 — session_id source split-brain.** Verify `SessionStart`/Stop payload `session_id` ==
  `CLAUDE_CODE_SESSION_ID` (init_contract). The watermark MUST key the same thread dir the Stop hook
  reads; if they diverge, key all off `HARNESS_THREAD_DIR` when set. **Now load-bearing** (Step 1
  risk) — a split here silently disables the watermark.
- **DAG molecules** — the transitive root-walk (Step 2b) picks one path when a bead has multiple
  parents. The implicit watermark path is immune (no walk); the parent-scope path carries the risk.
- **Scope-override (`scope_release.json`) — REJECTED (bureaucracy verdict).** An agent-authored
  free-text reason file that releases the gate is mock-bureaucracy by construction: the agent
  grades its own homework, with *maximal* incentive to game (it writes the file specifically to
  stop). The gate can only presence-check the file, not judge whether the reason is genuine ⇒
  fails gate-design Rule 3. It is also unnecessary: the **state-only waiver analogue already
  exists** — `ScheduleWakeup` (concrete, future-date-validated, re-invokes the agent) covers the
  "real in-scope work, must pause" case, and manifest/queue-drain (beads close ⇒ live re-check
  passes ⇒ allow) covers the "genuinely done" case. No legitimate case remains. Removed, not
  deferred.
- **Option D (explicit manifest)** — fully designed above as the fallback if the watermark's
  prior-session miss proves problematic; not built in the skeleton.
