## Problem Statement

Nothing in escapement causes a repository to get structurally smaller. Across the
estate, `cake` added 4,024 source files and deleted 119 in five months (34:1) with
98% of commits deleting nothing, and `dashboards` ran 7:1 with 88%. Where
measurement, declared decomposition pins and a ratchet were applied, complexity
*per file* and *per function* held flat while the repository grew 36% in files, and
dead code went to zero with its exemption list shrinking — but nothing shrank in
aggregate, and that machinery is bespoke to one repository, covers 617 of its 1,951
Python files, excludes `tests/` where 58% of rework lands, and has no way to
propose the next targets once the declared ones are met.

## Context

The estate contains one working instance of the mechanism this change generalises,
and one repository that wrote down the intent three times without building it.

`cake` runs a complexity baseline (`metrics/complexity-baseline.json`), 81 declared
decomposition pins (`metrics/complexity-baseline-pins.json`), architecture tests
that verify them, and a maintained vulture whitelist. Between 2026-06-23 (the first
date on which its complexity series is internally consistent) and 2026-09-18 its
measured totals moved: complexity 19,317 → 25,793 (+33.5%), functions 4,536 → 6,109
(+1,573), worst-file complexity 271 → 545 (doubled), complexity per file 42.7 → 41.8
and per function 4.26 → 4.22 (both flat), dead-code count 23 → 0 with the whitelist
shrinking 20 → 15 lines. Figures spanning 2026-05-26 are not comparable: commit
`78c8ddb62` corrected a radon double-count mid-series, and the apparent −14%
improvement widely quoted from that window is that correction, not a code change.
Over the same period the repository added 4,024 source files and deleted 119, and
98% of its commits deleted nothing. The measurement covers 617 of 1,951 Python files
and contains zero entries under `tests/`; `tests/` holds 58% of rework, all three
files touched by 20+ distinct work items, and a 5,541-line test file.

`dashboards` holds an open change `enforce-forward-architecture-ratchets`, an
archived `003-new-file-ratchet` decision, and a TypeScript-ratchets plan — with no
measurement, no pins, and a 7,701-line `App.test.jsx`.

Constraints carried from `escapement-onor`: the owner reviews structural design and
not diffs; controls must be mechanical and must contain no model judgment inside a
conformance check; human attention is the scarce resource and is already allocated
to one page at design time.

Prior research for `escapement-onor.5` is retained at
`.research/structural-design-layer-2026-09/` and its citation audit at
`.research/automated-review-merge-2026-09/`, including `CORRECTIONS.md`, which
records eight withdrawn claims and the four extraction failure modes that produced
them. Two findings from that corpus constrain this design directly and are cited in
Decisions below.

## Goals

- Make scope an explicit, checkable fact rather than a property of a script.
- Make a target decomposition declarable and mechanically verifiable.
- Make an idle ratchet visible, and make renewal a proposal a human accepts.
- Keep the loop in escapement and the numbers in the repository.

## Non-Goals

- Choosing thresholds, metrics, or path lists for any repository. Those are adapters.
- Implementing the extension of `cake` or `dashboards`. Both are consumers; neither
  is in scope here.
- Model judgment inside any check. Model effort is confined to drafting and ranking
  candidates that a human accepts.
- Reinstating human diff review.
- A cross-language or SQL metric. The adapter interface must admit one; this change
  does not supply one.

## Riskiest Assumption

**That a pin works on a test file.**

Every one of the 81 satisfied pins in the estate names source modules. The worst
artifacts in both repositories are tests: `test_bq_compactor.py` at 5,541 lines,
`App.test.jsx` at 7,701. The measured −14% complexity reduction happened entirely
in source, and the capability's whole value proposition is extending that result to
where the burden actually is.

A source module decomposes along dependency seams. A test file may not: its cases
may share fixtures, setup, and a single subject under test, so splitting it could
duplicate fixtures rather than reduce anything, and the measured complexity could
move sideways or up. If that is what happens, the capability still guards source
but does not reach 58% of the rework, and the case for building it collapses to
"generalise what `cake` already has", which is a much weaker claim.

This is falsifiable cheaply and must be tested before anything else is built.

## Walking Skeleton

Three tasks, on escapement itself, testing only the riskiest assumption. No
adapters, no renewal, no rule surfaces, no repo.json fields.

1. **Hand-write one pin for one real test file in this repository**, in the format
   `cake` already uses, naming the target decomposition. Establish whether a target
   decomposition can even be stated for a test file, or whether the seams are
   fixtures rather than behaviour.
2. **Measure that file before, and its replacements after**, with the same measure
   applied both times.
3. **Record whether total measured complexity across the replacements fell, held,
   or rose**, and whether fixture code was duplicated to achieve it.

## Proof of Delivery

The skeleton succeeds only if the decomposition **reduces total measured complexity
across the resulting files** and does not duplicate fixtures to do it. A split that
produces four files summing to more than the original is a negative result and must
be recorded as one.

A passing test suite is not proof. Neither is "the file is now smaller" — that is
the false proxy this whole change exists to reject, since any file can be made
smaller by moving its contents somewhere unmeasured.

## Anti-Metrics

- If pin-target amendments exceed pin satisfactions over any quarter, the mechanism
  is recording change rather than constraining it, and must be redesigned rather
  than tuned.
- If measured complexity falls while the count of files outside declared scope
  rises, the capability is relocating complexity rather than removing it.
- If the capability's own files enter the top ranks of the choke-point measurement
  it produces, it has become the thing it was built to prevent — the failure
  already visible in `cake`, whose ratchet policy test is that repository's
  second-most-coupled file at 24 distinct work items.

## Decisions

**Store intent; derive measurement.** This is the principle that reconciles the two
independent analyses of this estate, and it decides the artifact question.

Declarations — scope patterns, exclusions with justifications, and pins — are
*intent*. They SHALL be stored, versioned and reviewed, because a human decided
them and a reader must be able to see and challenge them.

Measured values are *observations*. They SHALL NOT be stored. Both sides of every
comparison are measured from git in the same run, by the same adapter.

The evidence is that a stored measurement is the common cause of both instrument
failures found in this estate. `cake`'s complexity baseline absorbed a radon
double-count correction (78c8ddb62) silently across 212 revisions, turning a
+33.5% trend into an apparent −14% improvement that stood unchallenged for three
months. `duplication-baseline.json` was hand-edited inside an unrelated feature
commit (56251934b) and still reports `generated_at` of 2026-07-06 through three
later commits. Neither failure is possible when nothing is persisted.

Cost was the only argument for storing, and it does not survive measurement:
stdlib `ast` 2.05s, radon 2.2s, lizard 4.27s over `cake`'s ~700 Python files;
both sides of a diff under 20 seconds.

Two consequences follow. The adapter-mismatch refusal becomes unnecessary — a
single run cannot mix adapters — and it is retained only for comparing *reports*
across time. And a satisfied pin needs no re-recording: once the reduction is
merged, the lower value *is* the merge-base for every later change, so the
ratchet tightens automatically rather than by writing a number down.

*Alternative considered:* store values with a method block (tool version, analyzer
hash, flags) and refuse cross-method comparison. Rejected as a mitigation for a
problem that need not exist: it defends the stored artifact rather than removing
it, and it still permits hand editing.

**The pin, not the import edge, is the structural representation.** An earlier form
of the `escapement-onor.5` decision record chose declared modules plus allowed
import edges, reasoning from Murphy's reflexion triple. That record now concludes
the opposite — that escapement should not add a structural conformance layer at
all — on the grounds that the estate's binding constraint was delivery rather than
detection, and that Rosik (SPE 2011) found conformance checking *concealed* drift.
This change is the reconciliation of the two: no new declaration language, but the
one construct that produced measured removal. Import-edge conformance constrains
where imports point; the measured problem is that nothing shrinks. The import-graph
prototype survives as a component — it answers "is this module still referenced"
exactly — not as the representation.

*Alternative considered:* keep both as co-equal representations. Rejected because
two declarations are two things to widen, and the research corpus documents
declaration-widening as the dominant failure mode.

**Scope coverage is a number, not a comment.** `cake`'s tests gap was invisible for
four months because scope lived in a script's path list. Recording measured/eligible
counts turns the gap into a value that can be checked and trended.

*Alternative considered:* require full coverage. Rejected: a repository cannot
adopt the capability if step one is measuring everything, and a forced-green
exclusion list is worse than an honest one.

**An exclusion requires a justification.** Both estate repositories grew their worst
artifact inside an exclusion. Treating an exclusion as a forecast rather than a gap
is the cheapest available control, and it is a declaration a human reads once.

**Renewal proposes; a human accepts.** This is the pattern verified in Meta's ACH
(Foster et al., FSE 2025): mutants generated deterministically, an LLM writes the
tests, a deterministic run decides acceptance. The model is upstream of the
decision, never inside it. Here: deterministic choke-point ranking, optional model
drafting of the decomposition, human acceptance, deterministic pin verification.

*Alternative considered:* automatic pin creation above a threshold. Rejected until
triage precision has been measured; accepting a model's target decomposition
without review is model judgment inside the gate by another route.

**Amending a pin is reported separately from satisfying one.** Rosik et al. (SPE
2011) observed architects adding discovered divergences to the declared architecture
as "expected relationships", after which those edges accumulated hidden
relationships (9 → 18 in one case, 3 → 9 in another). Measured in `dashboards`, 89%
of commits touching its guard layer also touch source in the same commit, and the
guard layer's own churn is +7,853/−635 lines. Widening must remain available — the
same paper documents the legitimate case, where the code is right and the
declaration is wrong — but it must never be the quieter option.

**Automation exclusion is part of the measurement contract.** The first run of the
choke-point measurement on `cake` returned `cake/__init__.py` at 251 rework touches
of 259 — a 13-line file whose churn is a robot incrementing a version string. 16% of
that repository's commits are automated. A history measure that does not exclude
them measures the robot.

**One loop, three checks, no new gate per metric.** `delicate-art-of-bureaucracy.md`
requires repair, transparency, and an escape per gate. Three deterministic checks —
coverage, pin state, idleness — share one repair path (widen scope with a
justification, meet the pin, or accept a candidate) and one escape (a recorded
exclusion). Adding a gate per metric is how `cake`'s ratchet policy test became the
second-most-coupled file in that repository at 24 distinct work items.

## Risks / Trade-offs

- **The capability becomes the choke point it was built to prevent** → the loop
  lives in escapement and the numbers live in the repository; no policy file is
  copied between repositories, and `cake`'s 24-work-item policy test is the named
  evidence for why.
- **Pins are amended to fit the code rather than met** → amendment is reported as a
  distinct outcome; the anti-metric is that if amendments exceed satisfactions over
  a quarter, the mechanism is recording change rather than constraining it and must
  be redesigned rather than tuned.
- **Renewal floods the queue with candidates** → candidates are emitted only when
  the ratchet is idle and thresholds are exceeded, and acceptance is per candidate.
- **Coverage is gamed by a broad exclusion** → exclusions require justifications and
  remain listed in the declared scope; candidate ranking deliberately includes
  out-of-scope files and reports their status.
- **The evidence is first-party and from AI-built repositories** → it is outcome
  evidence with a control group inside one repository, not a design cited as
  authority. It shows the loop produced measured removal where applied and none
  where not. It does not establish that the loop is optimal, and the surveyed
  literature does not supply that either: its strongest conformance studies ran no
  significance test or measured eight student projects.
- **Single-metric adapters may not exist for SQL or polyglot repositories** → the
  adapter interface admits exact substitutes (model line count, `ref()` fan-in, CTE
  depth for dbt; ESLint complexity or ts-morph for TypeScript), and the report
  refuses to compare values across adapters rather than reporting a false trend.

## Migration Plan

1. Land the loop and its three checks with no repository adopting it.
2. Adopt in escapement itself, at a scope that includes its own tests, proving the
   capability on the repository that owns it.
3. `cake` adopts by declaring its scope in the new format, retiring its stored
   baseline in favour of derived measurement, and extending
   scope to `tests/`; its 81 satisfied pins import as satisfied history.
4. `dashboards` adopts from zero, starting with `App.test.jsx`.

Rollback is removal of the checks; scope, exclusions and pins are declarations and remain
readable.

## Open Questions

- What interval defines idle? `cake` went quiet in September with all pins met; a
  first value is a guess until one repository has run a renewal cycle.
- What is the triage acceptance rate when a model drafts candidate decompositions?
  This is the number that decides whether step 3 of renewal can ever be automated,
  and it can only be obtained by logging accept/reject against real proposals.
- Do pins transfer to test files unchanged? Every satisfied pin in the estate names
  source modules. The worst artifacts in both repositories are tests.
