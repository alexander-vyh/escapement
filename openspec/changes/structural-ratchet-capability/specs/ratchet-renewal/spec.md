## ADDED Requirements

### Requirement: An idle ratchet is distinguishable from a finished one

The system SHALL report when every pin is satisfied and no new pin has been created
for a configured interval, so that a ratchet which has stopped driving reduction is
visible rather than silent.

#### Scenario: All pins satisfied and no new targets proposed

- **WHEN** every pin in a repository is satisfied and no pin has been created within
  the configured interval
- **THEN** the system reports the ratchet as idle
- **AND** the report states the date of the most recent pin creation, not the most
  recent pin satisfaction

#### Scenario: An active ratchet is not reported as idle

- **WHEN** at least one pin is unsatisfied, or a pin was created within the interval
- **THEN** the ratchet is not reported as idle

### Requirement: Choke points are identified by exact measures

Candidate targets SHALL be identified from measures computable exactly from
repository state and history: the number of distinct work items that touched a
file, its size, and its share of rework. Candidate identification SHALL NOT depend
on a model.

#### Scenario: Candidates are ranked and reproducible

- **WHEN** candidate identification runs against a repository
- **THEN** it emits a ranked list of paths with the measured values that ranked them
- **AND** a second run against identical state produces an identical list

#### Scenario: Automated churn cannot create a candidate

- **WHEN** a file's history consists predominantly of commits matching the
  automation exclusion rule
- **THEN** that file does not appear as a candidate on the strength of those commits
- **AND** the excluded commit count is reported alongside the candidate list

#### Scenario: Files outside the declared scope are still measured

- **WHEN** candidate identification runs
- **THEN** eligible source files outside the declared measurement scope are included in
  the ranking
- **AND** their out-of-scope status is reported, because an exclusion is where a
  choke point is most likely to have formed

### Requirement: Renewal proposes, a human accepts

When a ratchet is idle and candidates exceed their thresholds, the system SHALL
emit candidate pins as tracked work items for human acceptance. It SHALL NOT create
or amend a pin without that acceptance.

#### Scenario: Candidates become tracked work

- **WHEN** the ratchet is idle and at least one candidate exceeds its threshold
- **THEN** the system creates a tracked work item per accepted candidate containing
  the measured values that justified it

#### Scenario: Proposal does not become enforcement

- **WHEN** a candidate has been proposed but not accepted
- **THEN** no pin is created and no check fails on account of that candidate

#### Scenario: Model-assisted triage stays outside the gate

- **WHEN** model effort is used to draft or rank candidate decompositions
- **THEN** its output is recorded as a proposal for human acceptance
- **AND** no check consumes that output as a pass or fail condition
