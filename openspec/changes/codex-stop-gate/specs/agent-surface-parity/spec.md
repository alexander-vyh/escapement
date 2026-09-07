<!-- Spec: agent-surface-parity (delta) -->

## ADDED Requirements

### Requirement: Unsupported reasons must state true current constraints

Each manifest `unsupported_reason` SHALL describe a constraint that is true of
the host platform at the time the manifest is committed. When a platform gains
a capability that falsifies a recorded reason (e.g. Codex shipping a `Stop`
lifecycle event), the reason SHALL be updated to name the actual remaining gap
rather than the retired one.

#### Scenario: stale-no-stop-event-reason-retired

- **WHEN** the manifest entries for `stop_hook` and `validate_no_shirking`
  are read after this change lands
- **THEN** neither `unsupported_reason` claims Codex lacks a Stop lifecycle
  event; each names the true remaining gap (Claude-payload-shaped
  implementation; Codex is served by the `codex_stop_hook.py` adapter)

#### Scenario: final-response-gap-notice-updated

- **WHEN** `codex_final_response_gap.py` injects its SessionStart notice after
  the Codex stop gate is installed
- **THEN** the notice no longer asserts that no Stop/final-response hook is
  available; it names only the still-missing rungs (wakeup authoring,
  task-mode gating, wind-down judge)
