# codex-stop-gate — Walking Skeleton Tasks

## 1. Adapter pair with replay fixtures

- [ ] 1.1 Build `harness/bin/codex_stop_hook.py` and
  `harness/bin/codex_prompt_recorder.py` TDD-first against
  `harness/tests/test_codex_stop_hook.py` fixtures: (a) cro-reporting
  incident replay ("Shipped." + upstream-gone branch + dirty tracked file, no
  contract) → block; (b) same + recorded user "stop" → allow; (c) fresh green
  contract → allow; (d) `stop_hook_active: true` → allow; (e) conversational
  clean repo → allow; (f) dirty repo + plain non-completion answer → allow
  (double-key negative control); (g) malformed payload → allow + incident
  record. Decision must come from `would_block_stop` /
  `load_thread_state` — no reimplementation. (spec:
  stop-decision-reuses-shared-core, user-release-is-unconditional,
  prompt-recorder-persists-last-user-message, conversational-winddown-rung,
  loop-guard-honored, fail-open-with-signal, block-output-contract) Verify:
  the fixture suite passes and each scenario name maps to a test.

## 2. Register, trust, live probe

- [ ] 2.1 Register both hooks through the Codex plugin surface (manifest
  `hosts.codex.status: "ready"`, rendered into
  `plugins/escapement/hooks/hooks.json`; see design decision 3, superseded)
  and run the live probe: a Codex session in a
  scratch repo instructed to edit a file, claim "Shipped", and stop with the
  tree dirty. Capture the raw Stop payload (debug line into the thread dir)
  and diff against the documented fields. Done when the probe session is
  visibly blocked and continues, AND a second probe released with "stop" ends
  normally. (spec: incident-replay-blocks, recorded-stop-releases-gate)
  Verify: probe transcript + recorded payload archived in the change dir.

## 3. Retire the stale premise

- [ ] 3.1 Update `codex_final_response_gap.py`'s injected notice (Stop gating
  now exists; keep only the wakeup/task-mode/judge gaps) and the manifest
  `unsupported_reason` strings for `stop_hook` / `validate_no_shirking`.
  The Claude-shaped `stop_hook` / `validate_no_shirking` entries stay
  `unsupported` as scoped; the gate ships as new Codex-native manifest entries
  (`codex_stop_hook`, `codex_prompt_recorder`) instead, so porting those two
  remains escapement-vjv2's scope.
  Renderer constraints (from tools/render_agent_surfaces.py): the manifest is
  the source of truth and `.codex/hooks.json` is fully generated — never
  hand-edit it; keep `hosts.codex.status: "unsupported"` in this change
  (validation at `_validate_host_entry` requires a non-empty reason for
  unsupported, and flipping to `ready` demands `events` plus a fixture whose
  selector contains "codex" AND fans the hook into the plugin surface — that
  flip is escapement-vjv2's scope, not the skeleton's). Run
  `python3 tools/render_agent_surfaces.py --check` and the agent-surfaces
  tests. (spec: stale-no-stop-event-reason-retired,
  final-response-gap-notice-updated) Verify: grep finds no "no Stop lifecycle
  event" / "no Stop/final-response hook" claims; render check green.
