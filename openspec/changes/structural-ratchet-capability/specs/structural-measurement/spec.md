## ADDED Requirements

### Requirement: Measured values are derived, never stored

The capability SHALL compute every measured value from repository state at the time
of the check, measuring both the base commit and the candidate in the same run with
the same adapter. It SHALL NOT persist measured values to a tracked artifact.

Declarations are the exception and the distinction is deliberate: scope patterns,
exclusions with their justifications, and pins express *intent*, are decided by a
human, and SHALL be stored, versioned and reviewable. Measured complexity values are
*observations* and SHALL NOT be.

#### Scenario: No measurement artifact is required to run a check

- **WHEN** a check runs in a repository that has never produced one
- **THEN** it measures the base commit and the candidate and reports the comparison
- **AND** it requires no stored file of previous values

#### Scenario: A reduction is held without being recorded

- **WHEN** a decomposition reduces a path's measured value and that change merges
- **THEN** the reduced value is the comparison point for every later change, because
  the base is measured from history
- **AND** no re-recording step is required for the reduction to be held

#### Scenario: A measurement artifact cannot be hand-edited into agreement

- **WHEN** a contributor wishes to make a check pass
- **THEN** no tracked file of measured values exists to edit
- **AND** the only passing repairs are to change the code or to record a justified
  exclusion

### Requirement: Declared measurement scope

The capability SHALL record the scope it measures as an explicit set of path
patterns, and SHALL report the set of eligible source paths it did not measure.
Scope SHALL NOT be implicit in a script's internal path list.

#### Scenario: Coverage is reported as a fact

- **WHEN** a check runs for a repository
- **THEN** it reports the count of measured files, the count of eligible source
  files, and the resulting coverage fraction
- **AND** a reader can determine from the report alone which eligible paths are
  outside scope

#### Scenario: Coverage may rise and may not fall

- **WHEN** the coverage fraction of the candidate is lower than that of the base
- **THEN** the check fails and names the paths that caused the reduction

#### Scenario: Coverage regression is detected

- **WHEN** source files are added under a path that matches no scope pattern and no
  recorded exclusion
- **THEN** the check reports the new unmeasured paths and fails
- **AND** the failure message names the exact paths and both repairs: widen the
  scope, or record an exclusion with a justification

### Requirement: Exclusions carry justifications

Every path excluded from an otherwise eligible scope SHALL carry a recorded
justification. An exclusion without a justification SHALL fail the check.

#### Scenario: Unjustified exclusion is rejected

- **WHEN** a scope excludes an eligible source path and no justification is recorded
  for it
- **THEN** the check fails and names the path
- **AND** the message states that an exclusion is a prediction about where the next
  god object will form

#### Scenario: Justified exclusion is accepted and remains visible

- **WHEN** an exclusion carries a justification
- **THEN** the check passes
- **AND** the excluded paths and their justifications remain listed in the declared
  scope so they are reviewable rather than invisible

### Requirement: Metric is a per-repository adapter

The capability SHALL obtain its measure through a named, replaceable adapter, and
SHALL record which adapter produced a reported value. It SHALL NOT hard-code a
single metric.

#### Scenario: A repository selects a metric its language supports

- **WHEN** a repository declares a metric adapter appropriate to its sources
- **THEN** the check is performed using that adapter
- **AND** the report records the adapter name and version alongside the values

#### Scenario: Both sides of a comparison use one adapter

- **WHEN** a check compares a base commit against a candidate
- **THEN** both sides are measured by the same adapter in the same run
- **AND** a mismatch between the two is impossible by construction rather than by
  detection

#### Scenario: Reports from different adapters are not trended together

- **WHEN** two reports produced at different times record different adapters or
  adapter versions
- **THEN** a trend across them is refused and reported as a series break, rather
  than presented as an improvement or a regression

### Requirement: Independent implementations are cross-checked

The capability SHALL run both implementations where two independent implementations
of a measure are available, and SHALL report a divergence beyond a configured band,
so that a change in what an instrument counts is visible when it happens.

#### Scenario: A counting change is surfaced immediately

- **WHEN** one implementation's values diverge from the other's beyond the band
- **THEN** the check reports the divergence and names both values
- **AND** the report states that a metric-definition change is the most likely cause

#### Scenario: Agreement is quiet

- **WHEN** two implementations agree within the band
- **THEN** no divergence is reported

### Requirement: Measurement excludes automated commits

Any history-derived measurement the capability reports SHALL exclude commits
identified as automated, and SHALL record how many commits were excluded.

#### Scenario: Automated churn does not dominate

- **WHEN** history-derived figures are computed for a repository whose automation
  bumps a version constant on most releases
- **THEN** those commits are excluded from the figures
- **AND** the count and matching rule of excluded commits are recorded so the
  exclusion is auditable
