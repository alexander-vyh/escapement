## ADDED Requirements

### Requirement: Acceptance paths are constructible
The existing oracle-quality review MUST trace every claimed acceptance outcome from a literal fixture or input through a public entry point to the final observable assertion, and MUST reject a plan when that path cannot be constructed.

#### Scenario: Constructible acceptance path
- **WHEN** a test plan names a literal input, the public behavior exercised, and the final observed result
- **THEN** the reviewer evaluates its positive control, negative control, and fragile-implementation challenge without requiring another artifact

#### Scenario: Unconstructible acceptance path
- **WHEN** a claimed acceptance outcome cannot be reached by its named fixture or public entry point
- **THEN** the oracle-quality review rejects the plan before production implementation begins

### Requirement: Spec review is reference-first
The existing spec-review flow MUST record an initial verdict from the requested behavior and repository evidence before it receives the implementer's report, and MUST compare that report only after the initial verdict.

#### Scenario: Initial review is not primed by author claims
- **WHEN** an implementation reaches spec review
- **THEN** the reviewer first receives the requested behavior and repository location, independently inspects the implementation, and records a verdict without the implementer's report

#### Scenario: Claims are checked after the verdict
- **WHEN** the initial verdict has been recorded
- **THEN** the same reviewer receives the implementer's report and identifies any discrepancy without replacing its evidence-based verdict

#### Scenario: No independent reference exists
- **WHEN** the requirement or prior behavior was authored only by the implementing context
- **THEN** the review does not claim independently authored authority even if the reviewer context is isolated

### Requirement: Preserved worktree evidence remains visible
The existing worktree finish operation MUST retain the cleanup decision fields already computed when safe removal returns `disposition: preserve`, while keeping the current pending receipt and successful completion behavior.

#### Scenario: Unsafe worktree is preserved
- **WHEN** safe-removal inspection returns a preserve decision
- **THEN** finish returns that decision's repository, worktree, branch, candidate SHA, disposition, health, and reason together with `status: pending`

#### Scenario: Safely landed worktree completes
- **WHEN** the existing safe-removal conditions are satisfied
- **THEN** finish removes the worktree and branch, deletes its lifecycle receipt, and returns the existing completed result

### Requirement: Existing owners remain authoritative
The change MUST NOT add a gate, ledger, schema, CLI, agent role, classifier, or persistent state type.

#### Scenario: Change is inspected for new machinery
- **WHEN** the implementation diff is reviewed
- **THEN** each behavior is implemented in the existing oracle-review, execution-review, or worktree-finish owner with no parallel authority
