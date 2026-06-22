<!-- Spec: adapter-claude-code -->

## Purpose

Translation layer between Claude Code's session events and the canonical harness journal. In skeleton scope, runs only as a shadow-mode Stop hook — invokes `would_block_stop`, logs the decision to a shadow log, but always exits 0. Coexists with the existing `validate_no_shirking.py` regex Stop hook without interference.

## Requirements

### Requirement: Shadow-mode Stop hook

A Python script registered under the `Stop` matcher in `~/.claude/settings.json` MUST:

1. Invoke `would_block_stop(thread_state)` on every Stop event
2. Append a structured decision record to `~/GitHub/escapement/harness/shadow.jsonl`
3. Exit 0 unconditionally (skeleton scope — does not block)

#### Scenario: Stop event triggers shadow logging

- **WHEN** a Claude Code session reaches a Stop event
- **THEN** the shadow script reads the thread's `contract.json`, `scheduled.json`, and recent journal entries; calls `would_block_stop`; appends a record to `shadow.jsonl`; and exits 0

#### Scenario: Existing regex hook is unaffected

- **WHEN** both `validate_no_shirking.py` and the new shadow script are registered for Stop
- **THEN** both run independently; the regex hook's exit-code decision is authoritative (skeleton scope); the shadow script's logged decision is informational only

### Requirement: Structured decision log

Each entry in `shadow.jsonl` MUST contain:

- `timestamp` — ISO-8601 (string)
- `thread_id` — full `(team_id, agent_name)` identifier (string)
- `decision` — `"allow"` or `"block"` (string)
- `reason` — verbatim reason string from `would_block_stop` (string)
- `would_have_blocked` — boolean equivalent of `decision == "block"`
- `inputs` — JSON object containing: `last_tool_call` (string or null), `wakeup_count` (int), `verification_state` ({passed: bool, exit_code: int|null, timestamp: string|null}), `user_release_detected` (bool)

#### Scenario: Decision record is complete and parseable

- **WHEN** a Stop event has been logged
- **THEN** the resulting JSON record contains all required fields with correct types; running `jq .decision shadow.jsonl | sort | uniq -c` produces a valid count breakdown

### Requirement: No interference with parent process

The shadow hook MUST execute within a bounded time budget (≤ 500 ms wall-clock per invocation) and MUST NOT modify any files outside `harness/shadow.jsonl` and the thread's own directory.

#### Scenario: Hook completes within time budget

- **WHEN** the shadow hook is invoked on a typical Stop event
- **THEN** it completes in under 500 ms wall-clock and produces exactly one entry in `shadow.jsonl`

#### Scenario: Hook handles malformed thread state gracefully

- **WHEN** the thread directory is missing files or contains unparseable JSON
- **THEN** the hook logs a decision record with `reason: "thread_state_unparseable"`, exits 0, and does not raise an exception that would propagate to Claude Code
