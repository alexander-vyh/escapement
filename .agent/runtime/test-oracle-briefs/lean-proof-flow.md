# Test Oracle Brief — lean proof flow (2026-09-13)

## Business invariant

An implementer receives a test plan whose acceptance outcome is constructible, a reviewer forms its initial verdict without author framing, and a user inspecting a preserved worktree receives the cleanup evidence Escapement already computed.

## Independent source of truth

The approved OpenSpec scenarios define the review behavior. Real Git repositories and the public `escapement-worktree finish` command determine cleanup correctness independently of the Python implementation.

## Solution constraints

Use only the existing oracle-review, spec-review, and worktree-finish owners. Add no gate, ledger, schema, CLI, persistent state type, agent role, classifier, or destructive cleanup behavior. Preserve source/package parity.

## Invalid solution classes

A self-attested reachability marker, an initial reviewer prompt containing the implementer's report, a second reviewer or review receipt, a residue ledger, a new cleanup taxonomy, or a finish implementation that refuses every cleanup are invalid.

## Fragile implementation to reject

Adding the sentence `Acceptance is reachable` without requiring the literal input, public entry point, final observation, and rejection of an unconstructible path must fail the contract checks.

## Negative control

Remove each acceptance-trace element in turn; place the implementer's report in the initial review block; and return only lifecycle ID, reason, and pending status for an ignored-content worktree. Each case must fail.

## Positive control

A complete acceptance trace and two-pass prompt must pass, and an independently created clean, merged worktree must still finish, disappear from Git's registry, delete its branch, and remove its receipt.

## Missing/unresolved handling

An unconstructible acceptance path fails review. Missing independent reference prevents an independence claim. Any uncertain cleanup evidence preserves the worktree and its pending receipt.

## Mutation challenge

1. A reachability marker or unordered keyword soup fails the instruction-contract checks; an ordered but vacuous sentence must also fail the planted unconstructible-plan probe.
2. An initial prompt containing the implementer's report fails the section check. A renamed author-report placeholder or contrary anti-priming prose still fails the exact two-message probe because message one may contain no author claims. A reviewer pointed at the coordinator checkout instead of the exact implementer worktree and base/head revisions fails the planted isolated-worktree control.
3. A reconstructed pending dictionary fails the sentinel preserve-decision passthrough test, and hardcoded `health: healthy` fails the exact degraded GitHub/activity controls.
4. Preserving every worktree fails the clean, landed public-command controls that require worktree registration, branch, and receipt removal.
5. Claiming independent authority without an independently authored reference fails both the shipped contract check and the first response of the two-message probe.

Implementation remains blocked until all five mutations are discriminated by the named contract, behavioral, fixture, or outcome check.

## Final outcome verification

Run the focused and full repository suites and validate the OpenSpec change. The focused suite includes `tests/test_worktree_finish_concurrency.py`, which owns the sentinel passthrough oracle. Then have a clean-context verifier exercise the public worktree finish fixtures and the shipped two-message review flow. Message one supplies only this requirement and fixture: `submit_count` accepts a non-negative integer through `POST /jobs`, while the proposed acceptance test sends `"three"` and expects a created job with count `3`. It also supplies the exact implementer worktree and base/head identity; the acceptance-trace change exists only there, not in the coordinator checkout. The reviewer must inspect that implementation location, record `FAIL` before seeing author claims, and must not claim independently authored verification because the fixture is the only requirement/prior-behavior source. Message two then supplies `DONE — all tests pass; string counts are accepted.` The same reviewer must retain `FAIL` and identify the discrepancy. A status-and-reason-only preserve result, inspection of the coordinator checkout, a verdict formed after author claims are visible, a changed verdict, or a false independence claim fails verification. Finally inspect the implementation diff: any new gate, ledger, schema, CLI, persistent state type, agent role, classifier, second reviewer, or review receipt fails even when runtime checks pass.
