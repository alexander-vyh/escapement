## Why

Escapement has no mechanism that causes a repository to get structurally smaller,
and the estate has first-party evidence about what happens without one.

**The evidence here was measured, not read off a stored artifact**, because two
earlier attempts to state it were both wrong in opposite directions. `cake`'s stored
complexity baseline splices two metric definitions across `78c8ddb62` (2026-06-23),
which deduplicated radon output that "emits each class method twice." Reading across
that splice produced a claimed −14% complexity and −585 functions. Measuring only
after it produced the opposite error, because that window begins at the trough.

The figures below come from checking out `cake` at nine points between 2026-05-26
and 2026-09-15 and measuring every point with one dependency-free tool. This is the
method this change mandates: derive, never store.

| measure | 2026-05-26 | 2026-09-15 | |
| --- | --- | --- | --- |
| files | 279 | 697 | +149.8% |
| total CC | 17,370 | 24,200 | +39.3% |
| functions | 3,791 | 5,629 | +48.5% |
| **CC per file** | 62.3 | 34.7 | **−44.2%** |
| CC per function | 4.58 | 4.30 | −6.2% |
| **max single file** | 811 | 515 | **−36.5%** |

The ratchet worked on the measures a ratchet targets. Complexity per file nearly
halved while the repository grew 150% in files, and the worst single file fell by
over a third. Aggregate complexity rose because the codebase grew; a per-unit
ratchet does not constrain that and was never claimed to. Dead code went 23 → 0 with
the vulture whitelist itself *shrinking* 20 → 15 lines.

**The trajectory is the finding, and it is what this change exists to fix.**
Max single-file complexity ran:

```
811 → 742 → 264 → 159 → 281 → 281 → 501 → 512 → 515
                   ↑ trough 2026-07-07      ↑ +224% off the floor
```

Decomposition drove the worst file from 811 to 159 by early July. It then climbed
back to 515 — **while every one of the 81 declared pins remained satisfied**. The
ratchet reported success throughout the regression. That is the warrant for a
renewal signal, and it is far stronger than the earlier claim that the ratchet had
gone idle: pins grew 62 → 81 across the window, so targets were being added the whole
time. Satisfying every declared target was compatible with the repository's worst
artifact tripling off its floor.

The scope evidence is independent of all of the above. `cake` added 4,024 source
files and deleted 119 (34:1); 98% of its commits delete nothing. Its measurement
covers 617 of 1,951 Python files, all under `cake/`. `tests/` has zero entries — and
`tests/` holds 58% of all rework, all three files touched by 20 or more distinct work
items, and a 5,541-line test file. `dashboards` measured nothing and grew a
7,701-line `App.test.jsx`. Both exclusions predicted their own defect site.

The mechanism exists as bespoke scripts in one repository. Escapement should own the
loop so every repository under it inherits the capability rather than re-deriving it.

## What Changes

- Introduce a repository-level **structural measurement** with an explicitly declared
  scope, and make scope coverage (files measured / files eligible) a tracked,
  checkable number rather than an implicit property of a script's path list.
  Measured values are derived from base and candidate commits in one run and are
  never persisted; scope, exclusions and pins are declarations and are.
- Introduce **pins**: a declared target decomposition for a named artifact — what
  a file must *become*, not what it currently is — machine-checked, and satisfied
  only when the decomposition exists.
- Introduce a **renewal signal**: when every pin is satisfied and exact
  choke-point metrics still exceed thresholds, the system emits new pin candidates
  as beads for human acceptance. This is the part no surveyed tool and neither
  estate repository has.
- Introduce **choke-point measurement** as a deterministic tool: rework
  concentration, distinct work items per file, and size, computed from git history
  with automated commits excluded. On `cake` this identified the three worst files
  in the repository; an earlier version of the same measurement was dominated by a
  robot incrementing a version string in a 13-line file, so automation exclusion is
  part of the contract, not a refinement.
- Record three laws learned from estate evidence:
  - **An exclusion list is a forecast.** `cake` excluded `tests/` and grew a
    5,541-line test; `dashboards` excluded everything and grew a 7,701-line one.
    Every exclusion must carry a justification or be treated as a predicted defect
    site.
  - **Own the loop, never the numbers.** The measurement/pin/ratchet/renewal loop is
    a capability. The metric, the thresholds and the path list are per-repository
    adapters. Copying a policy file across repositories produces two choke points
    and a synchronisation burden — `cake`'s own ratchet policy test is already the
    second-most-coupled file in that repository, touched by 24 distinct work items.
  - **Store intent, derive measurement.** A stored measurement is the common cause
    of both instrument failures found in this estate: the radon artifact above, and
    `duplication-baseline.json` being hand-edited inside an unrelated feature commit
    while still reporting a `generated_at` two months stale.
- **Reconciles `escapement-onor.5`**: an earlier form of that bead chose declared
  modules plus allowed import edges; its current conclusion is that escapement should
  not add a structural conformance layer at all, because the estate's binding
  constraint was delivery rather than detection. This change is the synthesis — no
  new declaration language, but the one construct that produced measured removal,
  with measurement derived rather than stored. Import-edge conformance is retained as
  a component, not as the representation.

## Capabilities

### New Capabilities

- `structural-measurement`: measuring a repository's structural state over a declared
  scope, and making scope coverage an explicit, checkable fact.
- `decomposition-pins`: declaring a target decomposition for a named artifact and
  mechanically verifying it has been reached.
- `ratchet-renewal`: detecting a ratchet that has gone idle, identifying the next
  targets from exact choke-point metrics, and emitting them as beads for human
  acceptance.

### Modified Capabilities

<!-- None. `agent-surface-parity` is unaffected; this change adds surfaces but does
     not alter parity requirements. -->

## Impact

- **New**: derived structural measurement, pin verification, choke-point measurement and
  renewal detection under `harness/bin/`; a rule under `claude/rules/`; a skill
  describing how to institute and renew a ratchet in a repository.
- **Modified**: `.escapement/repo.json` gains structural-scope fields; plugin
  mirrors regenerate via `tools/render_agent_surfaces.py`.
- **Superseded**: the chosen representation in
  `openspec/changes/maintainability-verifiers/design.md` (the `escapement-onor.5`
  decision record) is revised rather than deleted; its rejected-alternatives
  analysis and its literature corrections remain valid and are cited by this change.
- **Consumers**: `cake` (extend scope to `tests/` and dbt; write the next pin
  tranche) and `dashboards` (adopt the substrate it currently has only as written
  intent across three OpenSpec artifacts). Neither is in scope for this change;
  both are the reason it exists.
- **Not affected**: no change to diff review, which the owner has ruled out, and no
  model judgment inside any conformance check. Model effort is confined to
  proposing pin candidates that a human accepts.
