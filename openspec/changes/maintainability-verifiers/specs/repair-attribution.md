# Spec: repair-attribution

### Requirement: Repair is attributed to the landing it followed
The system SHALL attribute each repair of a source file to the most recent prior change
to that file, and SHALL report how many repairs each landing induced.

#### Scenario: A repair shortly after a landing names that landing
- **WHEN** a repair commit touches a file changed by an earlier commit inside the window
- **THEN** the earlier commit is named as the inducing landing for that repair

#### Scenario: A repair that creates the file blames nothing
- **WHEN** a repair commit introduces a file that has no prior change
- **THEN** no landing is blamed, and the file is not credited with an attributed repair

### Requirement: Repair is distinguished from churn
The system SHALL rank files by repair, not by how often they change, and SHALL NOT rank
a file that has never been repaired.

#### Scenario: A frequently changed but never repaired file is absent
- **WHEN** a file is touched repeatedly and no repair commit follows any of those touches
- **THEN** the file does not appear in the ranking

### Requirement: The time window is load-bearing
The system SHALL count a repair as in-window only when it lands within the configured
number of days of the change it repairs.

#### Scenario: A long-delayed repair is counted but not in-window
- **WHEN** a repair lands 40 days after the change to the same file, with a 7-day window
- **THEN** the file's repair count includes it and its in-window count does not

### Requirement: Findings persist beyond the session
The system SHALL append its findings to the repository's gate-signal store so the
existing recurrence analysis can read them.

#### Scenario: Findings reach the signal store
- **WHEN** the ledger runs with signal emission enabled
- **THEN** one record per ranked file is appended, carrying the path, touch count,
  repair counts, and the inducing landings

### Requirement: The ledger measures; it does not gate
The system SHALL NOT block or question any action based on repair attribution until
recurrence in the captured corpus justifies a gate.

#### Scenario: A high-repair file is not blocked
- **WHEN** a landing changes the most-repaired file in the repository
- **THEN** no decision is emitted on that basis
