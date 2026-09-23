## ADDED Requirements

### Requirement: A pin declares a target, not a description

A pin SHALL declare what a named artifact must become: the set of paths that must
exist once the decomposition is complete. A pin SHALL NOT be satisfied by recording
the artifact's current structure.

#### Scenario: Pin is unsatisfied until the target exists

- **WHEN** a pin names target paths and one or more of them do not exist
- **THEN** the pin reports as unsatisfied
- **AND** the report names the missing paths

#### Scenario: Pin is satisfied when the decomposition exists

- **WHEN** every target path named by a pin exists
- **THEN** the pin reports as satisfied

#### Scenario: A pin that merely restates the present is rejected

- **WHEN** a pin's target path set is identical to the artifact's current path set
- **THEN** the pin is rejected as declaring no change
- **AND** the message distinguishes a target decomposition from a current-state
  catalog

### Requirement: Satisfying a pin tightens the ratchet without recording a number

A satisfied pin's reduction SHALL be held by history rather than by a recorded
number: the merged state becomes the base against which later changes are measured.
No re-recording step SHALL be required, and no stored value SHALL be the thing that
holds it.

#### Scenario: Reduction is held by history, not by a file

- **WHEN** a pin becomes satisfied and the measured complexity of its paths has
  fallen
- **THEN** the reduced value is what later candidates are compared against
- **AND** a later increase above it fails the check
- **AND** no artifact of measured values was written to hold the reduction

#### Scenario: Regression after satisfaction is caught

- **WHEN** a path whose pin was previously satisfied exceeds the value measured at
  the base commit
- **THEN** the check fails and names the path and both values

#### Scenario: The reduction cannot be returned by editing a file

- **WHEN** a later change would raise the measured value of a satisfied pin's paths
- **THEN** the only repairs are to lower the value or to record a justified
  exclusion
- **AND** there is no stored number that could be adjusted to make the check pass

### Requirement: Widening is distinguishable from meeting

Amending a pin's declared target SHALL be reported as a distinct outcome from
satisfying it, and SHALL never be the quieter of the two.

#### Scenario: Amending a target is surfaced

- **WHEN** a change modifies a pin's declared target paths
- **THEN** the amendment is reported as its own reviewable item, separate from any
  pass or fail of the pin
- **AND** the report states the previous target and the new one

#### Scenario: Amendment inside a feature change is still surfaced

- **WHEN** a pin's target is amended in the same change as the code it constrains
- **THEN** the amendment is still reported separately rather than absorbed into the
  change's other results

### Requirement: Pin verification contains no model judgment

Pin verification SHALL be decided by the presence or absence of declared paths and
by recorded numeric comparison. It SHALL NOT consult a model.

#### Scenario: Verification is reproducible

- **WHEN** pin verification runs twice against identical repository state
- **THEN** it produces identical results
