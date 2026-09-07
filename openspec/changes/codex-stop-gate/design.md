# codex-stop-gate — Design

## Problem Statement

Codex sessions can declare "done" and stop with no mechanical check — no outcome
verification, residue narrated instead of resolved (2026-07-07: Codex merged
simplifi/cro-reporting PR #329, said "Shipped", and stopped on a deleted-upstream
branch with unshipped local edits). When this ships, a Codex session that tries
to wind down without proof of completion or an explicit user release gets its
final answer intercepted and is forced to continue with a constructive
resumption prompt — the same outcome-or-resumption contract Claude Code sessions
already live under.

The enabling fact (verified against developers.openai.com/codex/hooks,
2026-07-07): Codex hooks are GA with a `Stop` lifecycle event whose payload
carries `session_id`, `cwd`, `stop_hook_active`, and `last_assistant_message`,
and whose block response is the same `{"decision": "block", "reason": ...}`
contract the Claude Stop hook already emits. Hooks load from a user-level
`~/.codex/` layer, covering every repo at once. The manifest's
"Codex has no Stop lifecycle event" reason is stale.

## Non-Goals

1. **No full continuation-harness parity port.** `schedule_wakeup_bridge`,
   `task_mode_entry`, `session_watermark`, `reconcile_incidents`, and the
   LLM wind-down judge stay Claude-only in this change. Locks in: Codex
   sessions get the universal stop paths (verify / release) but not task-mode
   queue gating or judged wind-down detection.
2. **No wakeup path for Codex.** Codex has no `ScheduleWakeup` tool; the
   `scheduled.json` check runs but nothing on Codex can populate it. Locks in:
   a Codex session genuinely waiting on an external event has only two clean
   exits — a green verify or a user release. Accepted for the skeleton; a
   file-based wakeup-authoring command is a named future increment.
3. **~~User-layer registration~~ — superseded on 2026-09-07.** This decision
   predates the system-wide Codex hook fanout. `scripts/codex-plugin-update.sh`
   now asserts the repo-local `.codex/hooks.json` is empty and *prunes*
   user-layer entries the plugin owns, so registering in `~/.codex/hooks.json`
   would install into the layer the installer strips. The gate ships through
   `plugins/escapement/hooks/hooks.json` instead, which is generated from the
   manifest: `hosts.codex.status: "ready"` is also the switch that vendors the
   hook and its `would_block_stop` siblings into the Codex package, so any
   status short of `ready` lands a file Codex can never run. New machines are
   self-serve via the existing plugin update.
4. **No modification of Claude's `stop_hook.py`.** The Codex adapter is a new
   file over the shared `would_block_stop` core. Locks in: the two hosts can
   drift in rung coverage until a later consolidation — accepted to keep the
   blast radius of a skeleton at zero for the Claude path.

## Strategic Alternatives

- **Do nothing / keep the prose notice.** Rejected: `codex_final_response_gap.py`
  is exactly this, and the 2026-07-07 incident is the compliance tier failing in
  production.
- **Wrapper binary around `codex` that re-invokes on unverified exit.** Rejected:
  this was the only option before hooks GA; it duplicates what the native Stop
  event now does, adds a process-supervision layer to maintain, and does not
  work cleanly for interactive TUI sessions.
- **Side-channel alerting (`notify` / `agent-turn-complete` → ping the human).**
  Rejected: an alert makes the human the gate; it observes laziness instead of
  preventing it, and at 2am nobody is watching the toast.

## Capabilities

### New Capabilities

- `codex-stop-gate` — Codex Stop-event adapter over the shared stop-decision
  core, plus the user-prompt recorder that enables the release path.

### Modified Capabilities

- `agent-surface-parity` — manifest `unsupported_reason` strings for
  `stop_hook` / `validate_no_shirking` must stop asserting "Codex has no Stop
  lifecycle event"; `codex_final_response_gap`'s injected notice must stop
  claiming no Stop hook exists once the gate is installed.

## Impact

- **New:** `harness/bin/codex_stop_hook.py` (Stop adapter),
  `harness/bin/codex_prompt_recorder.py` (UserPromptSubmit recorder writing
  `last_user_message.json` into the session's thread dir).
- **Reused unchanged:** `harness/bin/would_block_stop.py` (`would_block_stop`,
  `load_thread_state`, `thread_dir_for_session`), `~/.claude/harness/` state
  layout (contract.json, threads/{session_id}/). Codex sessions share the same
  harness root; thread dirs are keyed by Codex `session_id`, so no collision
  with Claude sessions.
- **Config (outside repo):** `~/.codex/hooks.json` gains Stop +
  UserPromptSubmit entries; one-time trust approval via Codex `/hooks`.
- **Docs/manifest:** `agent-surfaces/manifest.json` reason strings;
  `claude/hooks/codex_final_response_gap.py` message text.
- **Deliberately untouched:** `harness/bin/stop_hook.py`,
  `claude/settings.template.json`, rendered `.codex/hooks.json` (repo-local
  surface), `plugins/escapement-claude/`.

## Riskiest Assumption

We believe a user-layer `~/.codex/hooks.json` Stop hook, once trusted, actually
intercepts a live Codex wind-down and forces a continuation prompt with our
`reason` text. We will know this is true when a scripted probe session in a
scratch repo — instructed to make a change, claim "Shipped" with dirty state,
and stop — visibly receives the resumption prompt and keeps working. If false
(hook not invoked, trust silently withheld, block output ignored, or payload
shape diverges from the docs), we will fall back to the wrapper-binary
alternative and record the divergence against the docs revision.

Liveness: if this is false and undiscovered for two weeks, we carry a false
sense of coverage while Codex keeps laziness-stopping daily — strictly worse
than the status quo. The skeleton exists to close exactly that window.

## Walking Skeleton

1. **Build the adapter pair with replay fixtures (TDD).**
   `codex_stop_hook.py`: read Stop payload → honor `stop_hook_active` → key
   thread dir by payload `session_id` → `load_thread_state` (with
   `recent_user_message` from `last_user_message.json`) → `would_block_stop` →
   on `("allow", "conversational")`, apply the deterministic wind-down rung:
   completion-claim shape in `last_assistant_message` (e.g. "Shipped",
   "Done", "complete", an offer to stop) AND git-work-remains in payload `cwd`
   (dirty tracked files, unpushed commits, upstream-gone branch) → block with
   resumption prompt; every exception fails open (allow) and logs an incident.
   `codex_prompt_recorder.py`: UserPromptSubmit → write prompt text +
   timestamp to the thread dir. Fixtures: (a) cro-reporting incident replay
   ("Shipped" + dirty/upstream-gone cwd, no contract) → block; (b) same +
   recorded "stop" from user → allow; (c) fresh green contract → allow;
   (d) `stop_hook_active: true` → allow; (e) conversational turn, clean repo →
   allow; (f) malformed payload → allow (fail-open) with incident logged.
2. **Register, trust, and live-probe.** Add both hooks to `~/.codex/hooks.json`,
   complete the trust flow, then run the probe from the Riskiest Assumption in
   a scratch repo. Log the raw payload received (one debug line into the thread
   dir) and diff it against the documented fields. Observable outcome: the
   probe session is blocked and continues; payload matches or divergences are
   recorded.
3. **Retire the stale premise.** Update `codex_final_response_gap.py`'s
   message (Stop gating now exists; keep the notice for wakeup/task-mode gaps
   only) and the manifest `unsupported_reason` strings for
   `stop_hook`/`validate_no_shirking` to name the true remaining gap
   ("Claude-payload-shaped; Codex uses codex_stop_hook.py adapter") — then
   re-render/`--check` the generated surfaces.

## Proof of Delivery

This is done when a live Codex session in a scratch repo that claims completion
with a dirty working tree and no green verify is visibly forced to continue by
the gate's resumption prompt — and a session the user releases with "stop" ends
normally.

## Anti-Metrics

1. **Empty-fire rate on conversational turns.** If plain Q&A Codex turns in a
   dirty repo routinely require the user to type "stop" to escape, the
   wind-down rung is over-triggering — the gate has failed even though it
   "works". (Signal: incident-log block entries on turns with no
   completion-claim shape.)
2. **Gate removal within two weeks.** If the hook gets untrusted/disabled
   because it is noise, the design was coercive, not enabling.
3. **Claude-path regressions.** Any behavior change in Claude sessions' Stop
   gating — this change must not touch that path at all.

## Decisions

- **User-layer (`~/.codex`) over per-repo `.codex/`.** Confirmed with user.
  One install covers all repos (the incident repo had no escapement surface at
  all); per-repo rendering remains available for repo-specific gates later.
- **New thin adapter over reusing `stop_hook.py`.** The Claude hook carries
  transcript parsing, the LLM judge, task-mode, session-isolation and beads
  rungs — all Claude-shaped. The shared core (`would_block_stop`) is already
  host-neutral; the adapter stays small and the Claude path stays untouched.
- **Deterministic wind-down rung instead of the judge.** `last_assistant_message`
  arrives in the payload, so a completion-claim shape check plus
  git-work-remains covers the motivating incident class without porting the
  judge. Scoping the rung to completion-claim-shaped messages is the
  false-positive control.
- **UserPromptSubmit recorder for the release path.** Codex `transcript_path`
  is nullable and its format is undocumented; recording the user's own prompt
  at submit time is host-format-independent and makes `_user_released` work
  unmodified. Without this, "stop" could not release the gate — an
  unacceptable coercive failure.
- **Fail-open everywhere.** A gate bug must degrade to today's behavior
  (no gate), never to a hard-stuck session. Every failure logs an incident so
  fail-open is observable, not silent (never-suppress).

## Risks & Trade-offs

- **Trust flow silently withholds hooks** → probe task explicitly verifies via
  `/hooks` listing + observed block; registration is not "done" until the
  probe fires.
- **Infinite block loop** → `stop_hook_active` honored first, same as Claude;
  user release is unconditional.
- **Phrase heuristic gamed or drifts** → accepted for skeleton; incident log
  accumulates labeled fires for tuning; the contract path (when Codex sessions
  declare contracts via AGENTS.md instruction) is the real teeth long-term.
- **Codex payload/output contract changes upstream** → adapter parses
  defensively, fails open, logs; probe re-run is the detection.
- **Shared harness root across hosts confuses ownership** → accepted; thread
  dirs are session-keyed and the layout is already multi-session-safe.

## Future Increments

[PLACEHOLDER] — options purchased by validating the riskiest assumption:

- **Codex wakeup path** (`escapement-u7aq`, blocked on skeleton): file-based
  `scheduled.json` authoring command callable from Codex via shell, plus the
  launchd waker. Done when a Codex session waiting on CI can register a
  wakeup and stop cleanly, not when the file merely exists.
- **INSTALL.sh `--target=codex`** (`escapement-drk`): render/verify user-layer
  registration. Done when a fresh machine reaches a firing probe from one
  command, not when files are copied.
- **Task-mode + watermark port; wind-down judge port; manifest status flips
  to `ready` with Codex fixtures** (`escapement-vjv2`, blocked on skeleton),
  per the parity rule (fixture-backed blocking only). Done when the Codex
  incident log shows the same rung coverage as Claude's, not when files
  exist.

## Open Questions

- ~~Exact common payload fields~~ — resolved 2026-07-07 from the hooks docs:
  `session_id`, `transcript_path` (nullable), `cwd`, `hook_event_name`,
  `model`, `permission_mode`; Stop adds `turn_id`, `stop_hook_active`,
  `last_assistant_message`.
- **[DEFERRABLE]** Does Codex populate `transcript_path` in practice, and in
  what format? The recorder makes the answer non-blocking; probe task logs it
  for the judge-port increment.
- **[DEFERRABLE]** Should Codex sessions be nudged (via AGENTS.md) to declare
  contracts with `init_contract.py` so the verify path gains teeth beyond the
  wind-down rung? Belongs to the parity increment; note the
  `init-contract-clobbers-parent-in-subagent` hazard when it lands.

## Section Status

All sections `[PENDING SKELETON]` except Problem Statement and the resolved
payload-fields question, which are `[VALIDATED]` against the fetched docs.
