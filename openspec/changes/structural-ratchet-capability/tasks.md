## 1. Measurement and scope

- [ ] 1.1 Define the declaration format (stored): scope patterns, exclusions with
      justifications, adapter selection, and the automation-exclusion rule. Measured
      values are NOT part of it — nothing in this file is an observation
- [ ] 1.2 Define the metric adapter interface and implement two adapters for Python:
      a stdlib `ast` counter (zero dependencies, ~15 lines of counting rules) and
      radon, with the adapter name and version recorded in every report
- [ ] 1.3 Implement `harness/bin/structure_measure.py` to measure a repository at a
      given commit and to compare base against candidate in one run, persisting
      nothing
- [ ] 1.4 Implement the coverage check: new eligible source outside scope and outside
      recorded exclusions fails, naming exact paths and both repairs; coverage
      fraction may rise and may not fall
- [ ] 1.5 Implement the unjustified-exclusion check
- [ ] 1.6 Implement the cross-implementation divergence alarm over the two Python
      adapters with a configurable band, and report a series break when two reports
      record different adapters or versions
- [ ] 1.7 Add `.escapement/repo.json` fields for structural scope and adapter
      selection, and update the schema and its validation

## 2. Pins

- [ ] 2.1 Define the pin file format (stored — a pin is a declaration): artifact
      under decomposition and declared target paths. Importable from `cake`'s
      existing `complexity-baseline-pins.json` shape without hand editing
- [ ] 2.2 Implement pin verification: unsatisfied when any target path is missing,
      satisfied when all exist, reproducible across runs with no model consulted
- [ ] 2.3 Reject a pin whose target path set equals the artifact's current path set,
      with a message distinguishing a target from a current-state catalog
- [ ] 2.4 Verify that a satisfied pin's reduction is held by the merge base with no
      re-recording step, and that no artifact of measured values is written
- [ ] 2.5 Fail when a path with a previously satisfied pin exceeds the value measured
      at the base commit, naming the path and both values
- [ ] 2.6 Report a pin-target amendment as a distinct outcome from satisfaction,
      including when the amendment lands in the same change as the code it
      constrains, showing previous and new targets

## 3. Choke-point measurement

- [ ] 3.1 Implement `harness/bin/choke_points.py`: distinct work items per file,
      size, and rework share, computed from git history
- [ ] 3.2 Implement the automation-exclusion rule; report the excluded commit count
      and the matching rule alongside every result
- [ ] 3.3 Include eligible files outside the declared scope in the ranking and mark
      their out-of-scope status
- [ ] 3.4 Verify reproducibility: two runs against identical repository state
      produce an identical ranked list

## 4. Renewal

- [ ] 4.1 Implement idleness detection from most recent pin **creation**, not most
      recent satisfaction, with a configurable interval
- [ ] 4.2 Emit candidate pins as beads when the ratchet is idle and thresholds are
      exceeded, each carrying the measured values that justified it
- [ ] 4.3 Ensure an unaccepted candidate creates no pin and fails no check
- [ ] 4.4 Record model-drafted candidate decompositions as proposals only, with no
      check consuming that output as a pass or fail condition
- [ ] 4.5 Log accept/reject per proposed candidate so triage precision becomes a
      measurable number

## 5. Rule and skill surfaces

- [ ] 5.1 Write `claude/rules/structural-ratchets.md`: store intent and derive
      measurement, scope is a number, an exclusion is a forecast, own the loop and
      never the numbers, a pin declares what a thing must become, and a satisfied
      ratchet is indistinguishable from an abandoned one without a renewal signal
- [ ] 5.2 Write the skill for instituting and renewing a ratchet in a repository:
      declare and justify scope, identify targets, write pins, decompose, tighten,
      and renew
- [ ] 5.3 Ensure both surfaces carry repair, transparency and escape per
      `claude/rules/gate-design.md`, sharing one repair path and one escape across
      all three checks rather than adding a gate per metric
- [ ] 5.4 Regenerate plugin mirrors and confirm
      `tools/render_agent_surfaces.py --check` is clean

## 6. Prove it on this repository

- [ ] 6.1 Declare escapement's own scope including `tests/`, with justified
      exclusions, and report coverage
- [ ] 6.2 Run choke-point measurement on escapement and record the ranked output
- [ ] 6.3 Write and satisfy at least one real pin in escapement, demonstrating a
      measured reduction rather than a synthetic fixture
- [ ] 6.4 Confirm the three checks fail on a deliberately introduced violation of
      each and pass on repair
- [ ] 6.5 Confirm the divergence alarm fires against a commit predating
      `cake`'s 78c8ddb62 radon dedup and is silent at HEAD — the regression test for
      the failure this capability exists to prevent

## 7. Reconcile the superseded decision

- [ ] 7.1 Revise `openspec/changes/maintainability-verifiers/design.md` to record the
      pin as the representation and the import graph as a component, preserving the
      rejected-alternatives analysis and the literature corrections
- [ ] 7.2 Update `escapement-onor.5` with the superseding finding and its evidence,
      noting that its five-layer ruleset and this capability are the same design
      reached from two directions
- [ ] 7.3 Cross-reference `.research/structural-design-layer-2026-09/` and
      `.research/automated-review-merge-2026-09/CORRECTIONS.md` from the revised
      decision record so the withdrawn claims travel with it
