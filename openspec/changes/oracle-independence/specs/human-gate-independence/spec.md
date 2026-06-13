<!-- Spec: human-gate-independence -->

## Purpose

Make the human design/review gate produce *genuine independence* — catching what the
implementing agent's framing of a diff hides — by presenting the reviewer with a
reference independent of that diff (the prior behavior / the approved spec). This is the
out-of-session boundary (escape-b) the architecture relies on; the walking skeleton
validates its premise before build-out.

## Requirements

### Requirement: Independent reference at the gate

The design/review gate MUST present the reviewer with a reference authored independently
of the implementing agent's diff (prior behavior snapshot or approved spec), not only the
agent's own summary of the change.

#### Scenario: refactor reaches the gate

- **WHEN** a refactor change reaches the human design/review gate
- **THEN** the gate surfaces the pre-change behavior (or the approved requirement)
  alongside the diff, so the reviewer judges against something the agent did not author

### Requirement: Empirical validation before build-out (skeleton)

The independence premise MUST be validated by a blinded probe before the capability is
built into the live gate. The probe MUST NOT rely on the reviewer knowing which artifact
is planted.

#### Scenario: blinded independence probe

- **WHEN** the probe runs a set of real already-merged refactor diffs (≥1 carrying a
  planted transcription error) past the reviewer in two conditions — agent-framing-only,
  then with the independent reference added
- **THEN** the catch-rate is recorded for each condition, and the independent-reference
  condition catches a planted error the framing-only condition missed (or the premise is
  marked false and the route-to-human half is abandoned)

#### Scenario: contamination is acknowledged, not ignored

- **WHEN** the probe is interpreted
- **THEN** the result notes that the reviewer knew a probe was running (vigilance
  contamination, n=1), and a forward natural experiment is queued as confirmation if the
  probe result is ambiguous
