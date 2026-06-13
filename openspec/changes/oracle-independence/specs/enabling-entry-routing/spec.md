<!-- Spec: enabling-entry-routing -->

## Purpose

Route non-trivial work into a molecule from the user's opening description via an
*enabling default* (auto-pour / offer), so work reaches the human boundary without the
implementing agent having to remember to — never a blocking byte-zero gate. (Future
increment — gated on the riskiest assumption surviving and on the Risk-A classifier
spike showing a tolerable fire-rate.)

## Requirements

### Requirement: Enabling routing, not blocking

Routing into a molecule MUST be an enabling default (auto-pour or offer), MUST NOT be a
blocking gate on the first edit, and MUST keep its interrupt/false-positive rate
materially below the dismissal threshold the existing gates breach.

#### Scenario: non-trivial work described at session start

- **WHEN** the user describes feature-scale work at session start
- **THEN** a molecule is auto-poured (or offered) so the work reaches the human design
  gate, without the agent being blocked or required to remember to route

#### Scenario: trivial work

- **WHEN** the user describes a one-line fix or chore
- **THEN** routing does not fire (or fires far below the tdd-gate ~74% rate), so the
  signal is not trained into dismissal

### Requirement: Classifier viability is a precondition (Risk A)

This capability MUST NOT be built until a classifier spike demonstrates work-type can be
inferred from the opening description at a fire-rate/error-rate the dismissal threshold
tolerates.
