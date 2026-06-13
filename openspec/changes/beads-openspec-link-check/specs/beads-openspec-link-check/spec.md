## ADDED Requirements

### Requirement: Print an ephemeral link-check to stdout

The system SHALL print a Beads-to-OpenSpec link-integrity and status report for a
specified OpenSpec change to stdout from live Beads state, and SHALL NOT write any
file. Volatile metadata SHALL be written to stderr so that stdout is deterministic.

#### Scenario: Report is printed, not persisted

- **WHEN** the user runs the command for `openspec/changes/<change>`
- **THEN** the report is written to stdout
- **AND** no file is created or modified anywhere by the command
- **AND** any volatile metadata (e.g. a generated-at timestamp, tool versions) is
  written to stderr, not stdout

#### Scenario: Stdout is deterministic

- **WHEN** the command runs twice against identical live Beads state and identical
  OpenSpec anchors
- **THEN** the stdout report body is byte-identical, with records sorted by Bead id
- **AND** there is no excluded or "optional" field within stdout (the only volatile
  output is on stderr, which is not part of this assertion)

### Requirement: Preserve source-of-truth boundaries

The system MUST NOT mutate OpenSpec intent files or Beads task state while producing
the report.

#### Scenario: Intent files are unchanged

- **WHEN** the command runs for a change
- **THEN** `proposal.md`, `design.md`, `specs/*`, and `tasks.md` are byte-identical
  before and after the run

#### Scenario: Beads state is unchanged

- **WHEN** the command runs for a change
- **THEN** no Bead is created, updated, closed, reopened, re-scoped, or re-linked
- **AND** the report only reflects task state read from the authoritative Beads
  source

### Requirement: Read live Beads state

The system SHALL derive task-state data from live Beads state rather than passive
exports or unstructured text mentions.

#### Scenario: Live Beads source is used

- **WHEN** the command reads Beads data
- **THEN** it reads from `bd` command output or an equivalent live Beads API backed
  by the tracker database
- **AND** it does not treat `.beads/issues.jsonl` as authoritative task state

### Requirement: Require spec_id resolution for coverage

The system SHALL count a Bead toward an OpenSpec requirement's coverage only when its
`spec_id` resolves to an anchor that exists in the change's current OpenSpec specs.
Mere presence of a `spec_id` string is not coverage.

#### Scenario: A valid link resolves and counts (positive control)

- **WHEN** a Bead has a `spec_id` whose anchor exists in the change's current specs
- **THEN** the Bead is counted toward that requirement's coverage
- **AND** the command does not report it as a link-integrity violation

#### Scenario: A description-only mention is advisory, not a link and not a violation

- **WHEN** a Bead's description mentions `openspec/changes/<change>` but the Bead has
  no `spec_id` link for that change
- **THEN** the Bead is NOT counted as linked execution for any requirement
- **AND** the Bead is reported as an advisory unlinked / missing-coverage item
- **AND** the command does NOT treat the mention as a link-integrity violation and
  does NOT change the exit code on its account (silence in the structured channel is
  not a lie)

### Requirement: Fail closed on the closed set of link-integrity violations

The system SHALL exit non-zero when and only when at least one link-integrity
violation exists. The set of link-integrity violations is closed and contains exactly
two members, both of which are a `spec_id` claim that does not resolve: an orphaned
`spec_id` and a present-but-unresolved `spec_id`. All other states are advisory and
SHALL NOT change the exit code.

#### Scenario: A present-but-unresolved spec_id fails closed

- **WHEN** a Bead has a `spec_id` whose anchor was renamed or no longer exists in the
  change's current specs
- **THEN** the Bead is NOT counted toward coverage
- **AND** the command reports a link-integrity violation naming the Bead and the
  unresolved `spec_id`
- **AND** the command exits non-zero

#### Scenario: An orphaned spec_id fails closed

- **WHEN** a Bead has a `spec_id` that points at a missing change, file, or anchor
- **THEN** the command reports an orphaned-link integrity violation naming the
  invalid `spec_id`
- **AND** the command exits non-zero

#### Scenario: Blocked work is advisory

- **WHEN** linked Beads for a change are blocked or depend on blocked work, but all
  `spec_id` links resolve and no link-integrity violation exists
- **THEN** the command reports the blocked work in an attention or next-action
  section of stdout
- **AND** the command exits zero
- **AND** the blocked work is not collapsed into a generic incomplete count

#### Scenario: Missing coverage is advisory

- **WHEN** an OpenSpec requirement in the change has no linked Beads
- **THEN** the command reports the requirement as missing execution coverage
- **AND** the command does not infer coverage from nearby task text or file names
- **AND** the command exits zero (missing coverage is progress, not a lie)

#### Scenario: Coverage is grouped by requirement

- **WHEN** a change contains OpenSpec requirement anchors with linked Beads
- **THEN** the report groups coverage by OpenSpec requirement or commitment, not by
  assignee
- **AND** the report does not present a percent-complete value as the primary status

### Requirement: A link-integrity failure names how to clear it

The system SHALL, on each fail-closed exit, print the action that clears the
violation, naming the command or edit rather than only the upstream layer.

#### Scenario: A failure names the clearing action

- **WHEN** the command exits non-zero on an orphaned or unresolved `spec_id`
- **THEN** the message names the clearing action (e.g.
  `bd update <id> --spec-id <valid-anchor>` for a wrong link, or correcting/restoring
  the OpenSpec anchor for a renamed one)
- **AND** the message does not merely name the upstream layer ("fix it in Beads")

> Note: the fuller gate-design obligations (a `--link-check-waiver "<reason>"`
> override and `_gate_signal` recording on every failure/waiver) are deferred until
> this command is wired into a hook, at which point it becomes an enforced gate. See
> `design.md` Decision 6 and `tasks.md` § 5.2. In slice 1 the command is an explicit,
> unhooked CLI, so the clearing-action message above is the load-bearing affordance.

### Requirement: Defer closed-without-proof until proof is defined

The system SHALL NOT gate or assert on outcome proof in this slice; closed-without-proof
handling is deferred until the harness proof referent is defined.

#### Scenario: A closed Bead is neither asserted delivered nor failed on absent proof

- **WHEN** a linked Bead is closed
- **THEN** the command does not claim the linked requirement is delivered
- **AND** the command does not fail closed on the absence of proof, because the proof
  field is undefined in this slice
- **AND** the command may report the Bead's closed task state as read from Beads
