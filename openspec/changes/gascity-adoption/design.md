# Design — gascity Adoption

## Problem Statement

Today the user hand-coordinates ~6 concurrent agent sessions: launching each, tracking which
session owns which work, routing tasks, and holding "what's in flight where" in their head. After
this change, a gascity supervisor owns session lifecycle and work routing for the user's real
projects (registered as rigs). The observable change: the user *slings* work and gascity spawns,
routes, and sleeps sessions on demand — coordination state moves out of the user's head and into a
running system.

## Non-Goals

1. **Not moving agentic coding onto the local MLX model.** This session's trial proved it
   impractical (claude code sends ~383 KB/turn; the 27B 4-bit model takes 230s+/turn and times
   out). Cloud models stay the agentic brain. *Locks in: continued cloud token spend for coding.*
2. **Not building a per-role local/cloud provider matrix in this increment.** The user will iterate
   on that later. Initial adoption uses the default `claude` provider everywhere. *Locks in:
   no cost optimization from local models yet; that value is deferred.*
3. **Not a big-bang migration of all ~6 projects.** The skeleton adopts exactly ONE real project as
   a rig. *Locks in: most work stays hand-coordinated during the trial; adoption is incremental.*
4. **Not replacing beads or the continuation-harness.** gascity orchestrates *sessions*; beads still
   tracks work and the harness still gates. *Locks in: gascity layers on top — a third moving part,
   not a consolidation.*

## Capabilities

### New Capabilities
- `gascity-supervised-rig` — one real project registered as a gascity rig with demand-driven
  session lifecycle and work routing.
- `bounded-session-spawn` — spawn guardrails (min_active_sessions=0, idle-sleep, a max-sessions
  cap) that keep session count and token spend bounded under real load.

### Modified Capabilities
- None. gascity is additive; no existing `openspec/specs/` capability changes.

## Impact

- **New standing processes:** one `gc supervisor` launchd daemon + one per-city Dolt sql-server
  (the user already runs several dolt sql-servers, so this is marginal, not a new class).
- **Adopted project:** `gc rig add --adopt` installs gascity hooks into the project dir and folds
  its existing beads into the city store by `issue_prefix` (no init, no data conflict).
- **Dependencies:** `gc`, `tmux`, `jq`, `dolt ≥2.1`, `bd`, `flock`. This machine clears all floors
  (dolt 2.1.2, bd 1.0.4).
- **No repository code changes.** Adoption is configuration + a running supervisor.

## Riskiest Assumption

We believe **routing real work through gascity removes more hand-coordination toil than the
operational complexity (a standing supervisor + cities/rigs/packs to learn and maintain) and token
cost it adds — and that demand-driven spawning keeps token spend bounded in real use, not just at
rest.** We will know this is true when, after ~2 weeks running one real project as a rig, the user
is slinging work and *not* manually launching/tracking sessions, with token spend flat against the
pre-adoption baseline. If false — the user spends more time babysitting gascity than it saved, or
token spend climbs — we will revert the rig (`gc unregister` + remove the launchd plist) and keep
hand-coordination.

**Embedded alternative (rejected):** *build-thin* — a small spawn-on-ready waker on top of `bd gate`
plus the existing wind-down monitor, instead of adopting gascity. Rejected because it reproduces
gascity's controller (demand-driven spawn + idle-sleep + min-active) from scratch — the single
riskiest unbuilt piece, high blast radius — for one user, whereas gascity's controller is
battle-tested and (this session) the footprint/cost objections against adopting it dissolved.

**Liveness:** if this assumption is false and undiscovered for two weeks, the user will have
restructured daily work around gascity and must unwind it — significant rework. The assumption is
genuinely risky; the skeleton tests it first.

## Walking Skeleton

The minimum system that tests the riskiest assumption: one real rig, run for real, measured.

1. **Stand up gascity persistently.** Install `gc` (pinned direct-download to protect the pinned
   bd 1.0.4 — see Decisions) + `flock`; create one city; verify the supervisor starts and sits at
   0 running agents; set `bounded-session-spawn` config (min_active_sessions=0, idle timeout, a
   max-sessions cap). *(~45 min)*
2. **Adopt `io-validator` as a rig.** `gc rig add --adopt <io-validator>` if it has `.beads/`, else
   plain `gc rig add` (inits beads); verify beads are intact (before/after `bd` count, when adopting),
   that a test `gc sling` routes work to a demand-spawned **codex** session, and that the session
   sleeps after idle. *(~45 min)*
3. **Run real work through it (observation, ~1–2 weeks).** Sling the user's actual tasks for that
   project via gascity instead of hand-launching; observe demand-driven spawn/sleep, correct
   routing, and token spend. *(elapsed observation, not desk-time — this IS the proof of delivery)*

**Cutting test:** everything beyond "one real rig, demand-spawned, measured for two weeks" is cut
to future increments. The first rig is the smallest thing that can fail informatively.

## Proof of Delivery

This is done when, after ~2 weeks, the user routes work to the adopted rig **through gascity**
(having stopped hand-launching sessions for that project), gascity spawns and sleeps sessions on
demand, and token spend over the period is within the normal pre-adoption range — *not* when "the
city is configured" or "a session ran once."

## Anti-Metrics

Even if it works perfectly, this has failed if:
1. **Session count / token spend climbs materially** above the pre-adoption baseline — demand-driven
   spawn ballooned. (The user cannot afford to swarm; bounded spawn is load-bearing.)
2. **Babysitting time exceeds coordination time saved** — debugging the supervisor or fixing
   rig/routing config costs more than the hand-coordination it replaced.
3. **The user works around gascity** — keeps hand-launching sessions because the orchestration is in
   the way. Technically running ≠ adopted.

## Strategic Alternatives

- **Do nothing / keep hand-coordinating** — rejected: the coordination tax recurs every session and
  grows with concurrent-session count; the user has explicitly asked to remove it.
- **Build-thin (`bd gate` + small waker + wind-down monitor)** — rejected: reproduces gascity's
  controller for one user; the unbuilt waker firing layer is high blast radius, while gascity's is
  battle-tested and its adoption cost dissolved this session. (Also the Riskiest-Assumption embedded
  alternative.)
- **A different orchestrator (gastown, or hand-rolled tmux/launchd)** — rejected: gastown is the
  heavier product gascity was extracted from; hand-rolled process management is essentially what the
  user does today. gascity is purpose-built for multi-agent *coding* orchestration and is the
  lightest fit for the need.

## Decisions

- **Install via pinned direct-download, not `brew install gascity`.** brew pulls the `beads` formula
  as a mandatory dep, which can upgrade the deliberately-pinned bd 1.0.4 → corrupting 1.0.5. Direct
  download fetches only the `gc` binary. (Revisit once bd 1.0.6 lands.)
- **`gc rig add --adopt`** for the existing-beads project — skips init, adopts beads in place, with
  prefix-collision detection. No data migration.
- **Default provider = `codex` (the user's normal cloud `gpt-5.5` config in `~/.codex`).** codex is
  a gascity-recognized provider (`gc doctor` shows codex-parity + hooks tracking). Local/MLX
  providers — and a per-role provider matrix — are a future increment.
- **Bounded spawn config is mandatory at setup**, not deferred: min_active_sessions=0, idle timeout,
  explicit max-sessions cap. This is the guardrail the cost anti-metric depends on.
- **gascity layers on top of beads + the continuation-harness** — it orchestrates sessions; it does
  not replace work-tracking or Stop-gating.

## Risks & Trade-offs

- **Standing supervisor daemon + city Dolt server footprint** → accepted (the user already runs
  several dolt sql-servers; one supervisor daemon is marginal). Revert: `gc unregister` + remove the
  launchd plist.
- **gascity is young software** → mitigate by adopting ONE rig first and keeping hand-coordination as
  a live fallback during the trial; full revert is cheap.
- **Direct-download misses `brew upgrade`** → accepted to protect pinned bd; track gascity releases
  manually until bd 1.0.6.
- **Adopted project's beads fold into the city store topology (prefix-isolated)** → mitigate: verify
  bead counts before/after `--adopt`; the topology change is the one thing to watch on day one.

## Future Increments

`[PLACEHOLDER]` — purchased by validating the riskiest assumption on the first rig:
- **Local/cloud provider split per role.** MLX (via the normalizing proxy from this session's trial)
  for cheap small-context aux roles; cloud for agentic coding. *Done when cheap roles run on MLX with
  token spend measurably down — not when it is "configured."*
- **Adopt `cake` as the second rig (immediate fast-follow, not distant).** The io-validator skeleton
  proves gascity's mechanics + bounded cost on a calm repo; it does NOT exercise the multi-session
  coordination toil that actually motivated this (that lives in cake). The "removes coordination
  toil" half of the riskiest assumption is only truly tested once cake — the busy repo — is a rig.
  *Done when cake's concurrent work is slung through gascity and the user has stopped hand-juggling
  cake sessions — not when cake is merely registered.*
- **Expand to the remaining projects as rigs.** *Done when all active projects are rigs and
  hand-coordination is retired — not when N rigs exist.*
- **Custom formulas/agents for recurring workflows.** *Done when a recurring multi-step workflow runs
  as a slung formula end-to-end — not when a formula file exists.*

## Open Questions

- **[RESOLVED]** First rig = **`io-validator`**; primary provider = **`codex`** (pivot 2026-06-05).
  io-validator is a calmer first target than a busy cake repo — fits the "not so critical an early
  wobble hurts" criterion. Its beads/git state was not locatable from this session, so task 2.1
  branches: if `io-validator/.beads` exists → `gc rig add --adopt`; if not → plain `gc rig add`
  (which inits beads). If adopting, the before/after bead-count check is the day-one watch item.
- **[DEFERRABLE]** Exact `max-sessions` cap value — tune during the observation window; start
  conservative (e.g. 2–3).
- **[DEFERRABLE]** Whether to keep `gc` on direct-download or move to brew once bd 1.0.6 ships.
