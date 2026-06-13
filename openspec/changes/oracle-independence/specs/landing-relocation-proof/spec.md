<!-- Spec: landing-relocation-proof -->

## Purpose

A self-validating landing check (escape-a) that fails closed on verbatim-refactor
transcription errors by proving a moved code body arrived structurally identical, without
needing a spec, a human, or a trusted author. This is the spec-free mechanical catch for
the cake incident class. (Future increment — specified now because it is well-understood;
built after the skeleton validates the riskiest assumption.)

## Requirements

### Requirement: Relocation identity proof

A relocation landing check MUST fail closed when a code body departs file A and no body
AST-identical to it (modulo alpha-renaming of locals) arrives in file B.

#### Scenario: transcription error in a moved body

- **WHEN** a function body is relocated with an altered operator (e.g. `>`→`>=`)
- **THEN** the check fails closed — no AST-identical body arrived, so the move is not
  certified verbatim

#### Scenario: faithful relocation

- **WHEN** a function body is moved byte-faithfully (only locals/whitespace differ)
- **THEN** the check passes silently — the move is certified, no interrupt

#### Scenario: call-site arity mismatch

- **WHEN** the extraction's new call site passes arguments whose count/names do not match
  the extracted function's parameters
- **THEN** the check fails closed

### Requirement: Non-blocking first, promoted later

The check MUST ship first as a sound-but-noisy async tripwire (over-flagging only in the
safe direction, never silently green) and be promoted to a live per-commit gate only
after reference-resolution normalization is implemented.

#### Scenario: mass-move before normalization

- **WHEN** a multi-seam move triggers move-correlated reference fixups before
  normalization exists
- **THEN** the check over-flags (safe direction) rather than blocking, and does not run
  as a per-commit blocker
