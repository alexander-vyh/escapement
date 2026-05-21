<!-- Spec: verification-gate -->

## Purpose

Stateless pure function `would_block_stop(thread_state) -> (decision, reason)` that returns a deterministic Stop decision based on filesystem state. The load-bearing primitive of the harness: in skeleton (shadow) mode it only logs; in enforcing mode (future increment) its return value is the Stop hook's verdict.

## Requirements

### Requirement: Deterministic decision

The function MUST return one of `{"allow", "block"}` based solely on observable state — never on prose pattern matching or LLM judgment. Inputs:

- the most recent verification run's exit code and timestamp
- the contents of `scheduled.json` for this thread (if any)
- the current turn's tool-use record
- whether the user typed an explicit stop signal

#### Scenario: Verification passed this turn

- **WHEN** the most recent verification run for this thread has exit code 0 and its timestamp is within the current turn
- **THEN** `would_block_stop` returns `("allow", "verification_passed")`

#### Scenario: Wakeup registered

- **WHEN** verification has not passed this turn but `scheduled.json` contains at least one future-dated entry for this thread
- **THEN** `would_block_stop` returns `("allow", "wakeup_registered")`

#### Scenario: Explicit user release

- **WHEN** the most recent user message in the thread matches an explicit-stop set (e.g., `"stop"`, `"end here"`, `"done for now"`)
- **THEN** `would_block_stop` returns `("allow", "user_released")`

#### Scenario: Neither verified nor scheduled

- **WHEN** none of `verification_passed`, `wakeup_registered`, or `user_released` apply
- **THEN** `would_block_stop` returns `("block", "no_completion_or_resumption_proof")`

#### Scenario: No contract exists

- **WHEN** no `contract.json` exists for the thread and no wakeup is registered and the user did not release
- **THEN** `would_block_stop` returns `("block", "no_contract")` — agents working a task with no contract are blocked from stopping silently

### Requirement: Replay validation on the 57-stall sample

Before any production use (even in shadow mode), the function MUST pass a regression test against the committed 57-stall transcript sample. The sample is the canonical source of truth for what the function should catch.

#### Scenario: Paper-replay regression test

- **WHEN** the function is run against the committed sample at `harness/tests/fixtures/57-stall-sample.jsonl`
- **THEN** it blocks on **at least 15 of the 17** announced-poll-then-waited cases AND allows on **at least 25 of the 30** sessions that ended on a terminating tool call

#### Scenario: Replay test runs in CI / pre-commit

- **WHEN** any change is made to `would_block_stop` or its dependencies
- **THEN** the regression test runs and the change is rejected if either threshold falls below baseline
