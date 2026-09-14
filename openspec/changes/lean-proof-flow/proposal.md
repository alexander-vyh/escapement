## Why

Escapement already has the right owners for test-oracle review, implementation review, and worktree cleanup, but each drops a small piece of useful evidence: acceptance paths need not be shown as constructible, reviewers see the implementer's framing before forming a verdict, and pending worktree results discard cleanup evidence already computed. Restoring those signals in place improves decisions without adding workflow machinery.

## What Changes

- Require the existing oracle-quality review to trace each acceptance outcome from a literal input through a public path to its final observable assertion.
- Make the existing spec review reference-first: form an initial verdict from the requirement, independent reference, and repository evidence before comparing the implementer's report.
- Preserve the existing worktree cleanup decision fields when finish returns a pending result.
- Add no gate, ledger, schema, CLI, persistent state type, agent role, or classifier.

## Capabilities

### New Capabilities

- `lean-proof-flow`: Strengthens the three existing decision points without introducing a new workflow or source of truth.

### Modified Capabilities

None.

## Impact

- Oracle-review and Beads execution skill instructions, plus their packaged copies.
- Worktree finish output and focused lifecycle tests.
- Existing generated-surface verification; no public command or persistence-format change.
