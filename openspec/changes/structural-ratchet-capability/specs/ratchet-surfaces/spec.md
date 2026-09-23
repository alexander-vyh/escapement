## ADDED Requirements

### Requirement: Every check offers a repair path

Each failure reported by the capability SHALL name the concrete repairs available,
and SHALL do so in the failure message rather than in documentation the reader must
go and find.

#### Scenario: A coverage failure names both repairs

- **WHEN** the coverage check fails because eligible source landed outside scope
- **THEN** the message names the exact paths
- **AND** names both repairs: widen the scope, or record an exclusion with a
  justification

#### Scenario: A pin failure names what is missing

- **WHEN** a pin is unsatisfied
- **THEN** the message names the target paths that do not yet exist

### Requirement: One repair path and one escape across all checks

The capability SHALL present its checks as a single loop with one shared escape,
and SHALL NOT introduce a separate gate, waiver format, or suppression mechanism
per metric.

#### Scenario: The escape is a reviewed declaration

- **WHEN** a repository needs to exempt a path from measurement
- **THEN** the exemption is a recorded exclusion with a justification, visible in
  the declared scope
- **AND** no suppression comment, inline directive, or per-metric waiver format is
  accepted

#### Scenario: Adding a metric does not add a gate

- **WHEN** a repository configures an additional measure through the adapter
  interface
- **THEN** it is reported through the existing checks
- **AND** no new gate, failure class, or escape mechanism is introduced

### Requirement: The rule states the laws the estate evidence established

The rule surface SHALL state, as durable policy, that scope coverage is a tracked
number, that an exclusion is a prediction about where the next god object will form,
that a pin declares what an artifact must become, that the loop is owned centrally
while metrics and thresholds are per-repository, and that a satisfied ratchet is
indistinguishable from an abandoned one without a renewal signal.

#### Scenario: The rule is reachable from the agent surfaces

- **WHEN** an agent works in a repository that has adopted the capability
- **THEN** the rule is present in the generated agent surfaces
- **AND** `tools/render_agent_surfaces.py --check` reports the mirrors as current

### Requirement: The skill describes institution and renewal end to end

The skill surface SHALL describe the full loop — declare and justify scope, identify
targets, write pins, decompose, tighten, renew — including what to do when every pin
is satisfied.

#### Scenario: A repository with no declared scope can be onboarded from the skill alone

- **WHEN** an agent follows the skill in a repository that has never declared a scope
- **THEN** the steps carry it from nothing declared to a recorded scope with
  justified exclusions and at least one pin

#### Scenario: The idle case is covered

- **WHEN** every pin in a repository is satisfied
- **THEN** the skill states how the next targets are identified and proposed, rather
  than leaving the ratchet silently finished
