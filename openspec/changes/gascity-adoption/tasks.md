# Tasks — gascity Adoption (Walking Skeleton)

> **Execution status (2026-06-07):** Skeleton steps **1 (stand up gascity) and 2 (adopt
> `unified_order_intake` rig + smoke test) are DONE and validated** — codex spawns/routes/sleeps
> on demand, hands-free (see `execution-log.md`). The **dependency-bearing blocker is RESOLVED**
> (bead `claude-workflow-setup-85t`): root cause was bd 1.0.4 vs gascity's post-0043 schema; fix
> was activating **bd 1.0.5** (single-machine-safe). Verified: `bd dep add`/`list` + `gc sling`
> auto-convoy dependency-linking work on rig + hq. **Remaining = step 3 (run real work ~2 weeks,
> the proof-of-delivery observation).** Forward constraint: stay on 1.0.5, no second-machine /
> cross-machine beads sync until bd 1.0.6 (see `beads-version-gating` memory).


The skeleton is **one real rig, run for real, measured ~2 weeks**. It tests the riskiest
assumption: that gascity orchestration removes more coordination toil than it adds, with token
spend bounded.

**First rig: `io-validator`. Primary provider: `codex`** (pivot 2026-06-05; the user's cloud
`gpt-5.5` config in `~/.codex`, which gascity launches as a first-class provider). io-validator is a
calmer first target than a busy cake repo. Its beads/git state was not locatable this session, so
task 2 branches on it: `--adopt` if it already has `.beads/`, plain `gc rig add` (inits beads) if not.

## 1. Stand up gascity persistently

- [ ] 1.1 Install `gc` via **pinned direct-download** (NOT `brew install gascity` — it pulls the
  `beads` formula and can upgrade pinned bd 1.0.4 → corrupting 1.0.5) + `brew install flock`
  (spec: bounded-session-spawn / general prereq)
- [ ] 1.2 Create one city; verify `gc status` shows the supervisor running with **0 agents at rest**
  (spec: bounded-session-spawn / Zero sessions at rest)
- [ ] 1.3 Configure bounded spawn in the city: `min_active_sessions=0`, a finite idle timeout, and a
  finite max-sessions cap (start conservative, 2–3); confirm via the city config
  (spec: bounded-session-spawn / Bounded-spawn config is present at adoption)
- [ ] 1.4 Set the default provider to `codex` (`[workspace] provider = "codex"`); verify `gc doctor`
  reports codex provider-parity and that codex launches with the existing `~/.codex` (gpt-5.5) config
  (design: Decisions / Default provider = codex)

## 2. Adopt one real project as a rig

- [ ] 2.1 Locate the `io-validator` repo; confirm it's a git repo. Check for `.beads/`: if present,
  record its bead counts/IDs via `bd` BEFORE adoption (baseline for the no-loss check)
  (spec: gascity-supervised-rig / Adoption preserves existing beads)
- [ ] 2.2 Register the rig — **if `.beads/` exists:** `gc rig add --adopt <io-validator path>` and
  verify bead counts/IDs are identical AFTER (no loss/dup) + prefix-collision surfaced if it occurs;
  **if no `.beads/`:** plain `gc rig add <io-validator path>` (inits beads)
  (spec: gascity-supervised-rig / Adoption preserves existing beads, Prefix collision surfaced)
- [ ] 2.3 Test sling via codex: `gc sling` one trivial task with zero live sessions; verify the
  supervisor spawns a codex session, routes the work, executes it, and the session sleeps after the
  idle timeout (spec: gascity-supervised-rig / Work routes to a demand-spawned session, Idle sessions sleep)

## 3. Run real work through it (proof of delivery)

- [ ] 3.1 For ~1–2 weeks, route `io-validator`'s actual work via `gc sling` (codex sessions) instead
  of hand-launching; observe demand-driven spawn/sleep and correct routing
  (spec: gascity-supervised-rig)
- [ ] 3.2 Record the proof-of-delivery + anti-metrics check: did the user stop hand-launching
  sessions? did token spend stay within the pre-adoption range (no spawn balloon)? did babysitting
  time stay below the coordination time saved? (design: Proof of Delivery, Anti-Metrics) — if any
  anti-metric tripped, revert (`gc unregister` + remove the launchd plist) and capture why
