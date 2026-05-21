<!-- Spec: durable-wakeup-registry -->

## Purpose

Filesystem store at `~/GitHub/claude-workflow-setup/harness/threads/{team_id}/{agent_name}/scheduled.json` containing wakeup entries that survive session termination. In skeleton scope, the schema is defined and used by the verification gate; the live waker (the launchd-driven process that fires at `wake_at`) is DEFERRED until skeleton validation.

## Requirements

### Requirement: Schema-valid wakeup entries

Each entry in `scheduled.json` MUST conform to the schema, containing:

- `wake_at` — ISO-8601 timestamp, must be in the future at creation time (string, required)
- `prompt` — text to inject as the first user message on resume (string, required)
- `thread_id` — the thread to resume (string, required)
- `created_by` — tool name that registered the entry (e.g., `"ScheduleWakeup"`, `"adapter-fallback"`) (string, required)
- `crash_count` — integer (default 0); incremented if the wakeup fires while a prior re-spawn for this thread is still active

#### Scenario: Valid wakeup is accepted

- **WHEN** a tool call writes a JSON document with all required fields and a future `wake_at` to `scheduled.json`
- **THEN** JSON Schema validation passes; the entry is readable by `would_block_stop`; the verification gate counts it as "wakeup_registered"

#### Scenario: Invalid wakeup is rejected

- **WHEN** a write produces a JSON document missing `wake_at`, malformed timestamp, or `wake_at` in the past
- **THEN** schema validation fails; the file is treated as if no wakeup were registered; `would_block_stop` does not count the malformed entry

#### Scenario: Multiple wakeups can coexist

- **WHEN** two separate tool calls each register wakeups for the same thread at different times
- **THEN** both entries are persisted; the gate treats any future-dated entry as sufficient proof of scheduled resumption

### Requirement: Live waker [DEFERRED: pending skeleton validation]

A launchd-managed process that fires at `wake_at`, removes the consumed entry from `scheduled.json`, and respawns the thread with `prompt` injected as the first user message. Behavior on respawn conflicts, crash budget, and retry semantics are specified post-skeleton.

#### Scenario: Reserved for post-skeleton scope

- **WHEN** the skeleton's one-week shadow run completes and validates the riskiest assumption
- **THEN** this requirement is promoted from DEFERRED to ACTIVE and the live waker behavior is fully specified
