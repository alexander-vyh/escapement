# Spec: prepatch-failure-verification

### Requirement: A changed test must be shown to detect the change
The system SHALL determine, for a change, whether any test the change touched fails or
errors when the change's production files are restored to their pre-change content, and
SHALL treat a test that still passes as carrying no evidence about the change.

#### Scenario: A test that passes without the production change is questioned
- **WHEN** every test a landing changed passes with the landing's production files
  reverted to the base revision
- **THEN** the landing is questioned, and the message names the reproduction command,
  the waiver path, and the zero-friction escape

#### Scenario: A test that fails without the production change is not questioned
- **WHEN** at least one test a landing changed fails or errors with the production files
  reverted
- **THEN** the landing proceeds without a prompt

#### Scenario: Production changed with no test changed
- **WHEN** a landing changes production Python and changes no test file
- **THEN** the landing is questioned and the message says so specifically

#### Scenario: A change with no production code is not questioned
- **WHEN** a landing changes only documentation, generated surfaces, or test files
- **THEN** the landing proceeds, because there is no production change to detect

### Requirement: The tests remain at their post-change content
The system SHALL restore only production files to the base revision and SHALL NOT check
out the base revision wholesale.

#### Scenario: A newly added test is still runnable
- **WHEN** the change adds a test file that does not exist at the base revision
- **THEN** that test file is present and executed during verification

### Requirement: An unrunnable verification never blocks a landing
The system SHALL allow the landing when the repository, base revision, verifier, or
scratch worktree cannot be resolved, and SHALL record the reason as signal.

#### Scenario: The verifier is unavailable
- **WHEN** `prepatch_verify` cannot be imported from any known location
- **THEN** the landing proceeds and an `allow` record naming the cause is written

### Requirement: The escape is a validated reason, not a file's presence
The system SHALL accept a waiver only when its reason clears the repository's shared
substance bar, and SHALL reject a reason that is too short, a placeholder, or names
nothing beyond the files it excuses.

#### Scenario: A placeholder waiver is rejected
- **WHEN** the waiver file contains `tbd`, `n/a`, or a reason under the length floor
- **THEN** the landing is still questioned and the message says the waiver was not accepted

#### Scenario: A waiver that only echoes the changed files is rejected
- **WHEN** the waiver reason's only content words are tokens of the changed file paths
- **THEN** the landing is still questioned

#### Scenario: A substantive waiver is honored
- **WHEN** the waiver reason clears the substance bar
- **THEN** the landing proceeds and the reason is appended to the waiver corpus

### Requirement: Severity is earned by replay, not asserted
The system SHALL emit an advisory decision rather than a denial until replay evidence
over real history supports blocking.

#### Scenario: Evidence does not support blocking
- **WHEN** replay shows a weak oracle does not predict subsequent repair
- **THEN** the gate asks rather than denies, and the design records the evidence
