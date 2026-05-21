<!-- Spec: outcome-contract -->

## Purpose

A per-task declaration of the outcome the agent must verify before stopping. Stored as `contract.json` in the thread directory. The agent declares (or derives from a bead) what "done" means; the harness enforces it via the verification gate.

## Requirements

### Requirement: Contract structure

A contract file MUST be a JSON document conforming to the contract schema, containing at minimum:

- `goal` — one-sentence statement of the outcome (string, required)
- `verification_command` — shell command whose exit code is the oracle (string, required)
- `expected_exit` — integer (default 0)
- `source` — one of `"bead-derived"`, `"agent-declared"`, `"user-authored"` (string, required)
- `thread_id` — identifier of the thread this contract belongs to (string, required)
- `created_at` — ISO-8601 timestamp (string, required)

#### Scenario: Schema validation succeeds for valid contract

- **WHEN** a `contract.json` with all required fields is written and passes JSON Schema validation
- **THEN** the harness accepts it and the verification gate may invoke `verification_command`

#### Scenario: Schema validation fails for malformed contract

- **WHEN** a `contract.json` is missing `verification_command` or has wrong field types
- **THEN** the harness rejects the file and treats the thread as having no contract; the verification gate returns `"no contract"` as the reason

### Requirement: Bead-derived contracts where possible

If the thread is working a bead with acceptance criteria, the `verification_command` SHOULD be derived from `bd show <id> --acceptance-criteria` rather than agent-authored. Agent-declared contracts SHOULD be flagged for first-run human review.

#### Scenario: Bead with acceptance criteria

- **WHEN** a thread is working a bead that has acceptance criteria defined
- **THEN** the contract's `verification_command` is generated from those criteria and `source` is set to `"bead-derived"`

#### Scenario: No bead context (novel contract)

- **WHEN** a thread is working a one-off task with no associated bead
- **THEN** the agent declares the contract, `source` is `"agent-declared"`, and the harness emits a first-run review signal in the next Stop event's log entry
