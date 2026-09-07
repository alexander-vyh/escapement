<!-- Spec: codex-stop-gate -->

## Purpose

Mechanically intercept a Codex session's wind-down via the Codex `Stop` hook
event and force continuation unless the session has proven completion (green
contract verify), been explicitly released by the user, or has a registered
wakeup — reusing the host-neutral `would_block_stop` decision core.

## Requirements

### Requirement: stop-decision-reuses-shared-core

`codex_stop_hook.py` SHALL derive its allow/block decision from
`would_block_stop(load_thread_state(...))` in `harness/bin/would_block_stop.py`,
keyed by the payload `session_id` via `thread_dir_for_session`. It SHALL NOT
reimplement the verification-freshness, wakeup, or user-release logic.

#### Scenario: green-contract-allows-stop

- **WHEN** the session's thread dir contains a contract whose last verify run
  exited 0 within the freshness window, and a Stop payload arrives
- **THEN** the hook exits 0 with no block output (the session may stop)

#### Scenario: declared-but-unverified-contract-blocks

- **WHEN** the thread dir contains a declared contract with no fresh passing
  verify run, and a Stop payload arrives
- **THEN** the hook prints `{"decision": "block", "reason": ...}` where the
  reason text names the verify command as the way forward

### Requirement: user-release-is-unconditional

A user release phrase (as recognized by the shared core's `_user_released`)
recorded for the session SHALL allow the stop regardless of contract or
residue state.

#### Scenario: recorded-stop-releases-gate

- **WHEN** the session's recorded last user message is "stop" (via the
  UserPromptSubmit recorder) and a Stop payload arrives with a dirty cwd and
  a completion-claim assistant message
- **THEN** the hook exits 0 with no block output

### Requirement: prompt-recorder-persists-last-user-message

`codex_prompt_recorder.py` SHALL, on each Codex `UserPromptSubmit` event,
write the prompt text and a timestamp into the session's thread dir so the
Stop adapter can evaluate user release without parsing any transcript format.

#### Scenario: prompt-recorded-per-session

- **WHEN** a UserPromptSubmit payload with `session_id` S and prompt text P
  is delivered
- **THEN** the thread dir for S contains P as the most recent recorded user
  message

### Requirement: conversational-winddown-rung

When the shared core returns `("allow", "conversational")` (no contract), the
hook SHALL block iff BOTH hold: (a) `last_assistant_message` matches a
completion-claim / wind-down shape, and (b) deterministic git residue exists
in the payload `cwd` (dirty tracked files, unpushed commits, or a checked-out
branch whose upstream is gone). Otherwise it SHALL allow.

#### Scenario: incident-replay-blocks

- **WHEN** a Stop payload has no contract, `last_assistant_message` beginning
  "Shipped." and a `cwd` on a branch with upstream gone plus a modified
  tracked file (the 2026-07-07 cro-reporting incident shape)
- **THEN** the hook prints `{"decision": "block", "reason": ...}` and the
  reason names the residue and the paths forward (verify / finish residue /
  user "stop")

#### Scenario: conversational-clean-repo-allows

- **WHEN** a Stop payload has no contract, a non-completion-claim assistant
  message, and a clean `cwd` with no unpushed commits
- **THEN** the hook exits 0 with no block output

#### Scenario: dirty-repo-plain-answer-allows

- **WHEN** a Stop payload has no contract and a `cwd` with dirty files, but
  `last_assistant_message` is an ordinary answer with no completion claim or
  stop offer
- **THEN** the hook exits 0 with no block output (double-key: residue alone
  must not fire the rung)

### Requirement: loop-guard-honored

The hook SHALL exit 0 without evaluation when the payload has
`stop_hook_active: true`.

#### Scenario: second-stop-passes

- **WHEN** a Stop payload arrives with `stop_hook_active: true`
- **THEN** the hook exits 0 with no block output

### Requirement: fail-open-with-signal

Any internal error (malformed payload, missing harness state, git failure)
SHALL result in an allow (exit 0, no block output) AND an incident-log record,
never a block and never a crash that Codex reports as a failed hook.

#### Scenario: malformed-payload-fails-open

- **WHEN** the hook receives non-JSON or field-incomplete stdin
- **THEN** it exits 0 with no block output and appends an incident record

### Requirement: block-output-contract

Block responses SHALL be a single JSON object on stdout of the form
`{"decision": "block", "reason": "<constructive resumption prompt>"}`, with
the reason naming at least one agent-invokable way forward (run the verify,
finish the named residue, or ask the user to release with "stop").

#### Scenario: block-reason-names-escape-path

- **WHEN** the hook blocks for any reason
- **THEN** the emitted reason text contains a concrete next action, not only
  a prohibition

## Deferred (pending skeleton validation)

[DEFERRED: pending skeleton validation] Wakeup authoring from Codex, task-mode
queue gating, wind-down LLM judge parity, INSTALL.sh registration, manifest
status flip to `ready`.
