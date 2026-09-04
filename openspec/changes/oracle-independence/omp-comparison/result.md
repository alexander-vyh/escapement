# Pi versus Oh My Pi Dashboard replay

Status: pilot completed; the observed outcomes are valid, but all paired
efficiency comparisons remain inconclusive.

## Frozen setup

- Date: 2026-09-03
- Experiment: `b50ba884-a7b4-4bc9-a954-ed64bb63a2ba`
- Installed Pi: `@earendil-works/pi-coding-agent` 0.84.2
- Oh My Pi: `@oh-my-pi/pi-coding-agent` 18.1.4
- Bun: 1.4.0
- Provider/model: `anthropic/claude-haiku-4-5`
- Thinking: off
- Both arms used the same OMP-managed Anthropic bearer, captured only in process
  memory.
- The harness froze six distinct arm run IDs before obtaining that bearer.
- OMP used an in-memory session, fresh empty cwd, no tools, no spawns, no context,
  no extensions, no MCP/LSP/IRC, no advisor, no retry/fallback, and no compaction.
- Completion authority remained `verified_outcome_loop.py` plus each frozen
  external verifier. Model assessments and telemetry could not produce
  `COMPLETE`.
- Arm order alternated: Seller Pi/OMP, Source OMP/Pi, Launch Pi/OMP.

## Observed results

| Replay | Installed Pi | Oh My Pi | Paired efficiency |
|---|---|---|---|
| Seller Cents v2 | `UNRESOLVED`; 1 call, 1,484 tokens, $0.006244, 10.878 s | `UNRESOLVED`; 1 call, 826 tokens, $0.002994, 6.660 s | `INCONCLUSIVE` |
| Source Gaps v6 | `COMPLETE`; 2 calls, 2,004 tokens, $0.004972, 11.349 s | `COMPLETE`; 2 calls, 2,102 tokens, $0.005334, 10.680 s | `INCONCLUSIVE` |
| Launch Pacing v1 | `COMPLETE`; 2 calls, 972 tokens, $0.001816, 5.016 s | `COMPLETE`; 2 calls, 928 tokens, $0.001676, 5.347 s | `INCONCLUSIVE` |

These are raw arm totals, not runtime efficiency deltas. The harness emitted null
token, cost, and duration deltas because the execution contracts differ: Pi runs
roles in the fixture directory while OMP runs them in a fresh empty directory.
The effective provider-boundary input is also not independently observable. The
two completed pairs therefore show delivery capability, not causal superiority.

Seller failed before assessment because both generators violated the exact outer
`{"candidate":"..."}` response contract. OMP returned only a SQL fence; Pi
returned a SQL fence followed by JSON. Independently extracting the SQL did not
turn either response into a valid outcome: Pi divided mills by `100.0` instead of
`10.0`, while OMP lost deterministic residual allocation on the large-integer
precision case.

## Independent verification

- All ten persisted raw-event artifacts match their recorded byte lengths and
  SHA-256 digests, and each measured receipt contains exactly one finalized
  assistant message.
- Every provider/model identity, response ID, token field, cost field, and stop
  reason matches the raw provider event.
- The report and manifest agree on the experiment ID and all six unique arm run
  IDs.
- Seller has no completion receipt. Both Source and both Launch arms bind their
  completion to the exact run, candidate, frozen spec, invariant, and external
  verifier evidence.
- Fresh certification accepted all three required positives, rejected all 16
  named negatives, and accepted the materially different Source alternate
  positive.
- Source v6 preserves the generic 1,000,001-byte file-size ceiling and the Deno
  permission sandbox while using an invocation-local cache. Three repeated full
  certifications passed, and an infinite-loop candidate returned `FAIL` in
  4.684 seconds.
- The final harness suite passed 673 tests with 27 expected skips. The full-repo
  sweep passed 3,272 tests with 30 skips and found one stale assertion that still
  required OMP under runtime dependencies; after preserving the exact pin under
  development-only dependencies, the sole last-failed rerun passed. Ruff,
  generated-surface drift, frozen Bun install, and diff checks also passed.

## Binding evidence

- OMP adapter SHA-256:
  `262ef20bcdf6356c29fcb109af03d3b150fad2c674633c4d41c1986473d0757b`
- Source verifier artifact SHA-256:
  `8baca35712df17d7c1c2789d8deb5be2390d6fd71ee4e595c2f9e30e5cca3bbc`
- Source verifier binding:
  `1348bcb8797de69854eba498ce2ef58c5b7f8e8264f1452401e280606be0b02c`
- Launch verifier binding:
  `ed45abdb18930a9d698428be79b505af3305d34443a265785a2c2e3998e30bdd`
- Launch candidate in both arms:
  `7cc490bb1ed7dee4fdd1ffeee2c7559d0afc522806f58e8f5d1e31ac43f0aa31`
- Report SHA-256:
  `444a0395cfbbf4884a71eceaf80be7a9bf4a6187d0edbf11a3a51d9e7a1f0b2b`
- Manifest SHA-256:
  `814915bbd460df33f4b51f3f46bfaf4f86f1af045495865b585a73ff4526788a`

The report is `/private/tmp/pi-omp-dashboard-comparison-v9.json`. Raw provider
events and the pre-auth manifest are under
`/private/tmp/pi-omp-dashboard-events-v9/`; transport streams are under
`/private/tmp/pi-omp-dashboard-configs-v9/`. The runner exits 2 when any paired
comparison is inconclusive, so exit 2 is the expected fail-closed result here.

## Scope boundary

These are three reduced, frozen contract replays. They demonstrate externally
verified completion, repair-loop behavior, honest call accounting, and runtime
reliability for this sample. They do not establish equivalence to normal
Escapement delivery, repository integration, CI, deployment, or published
Dashboard behavior, and they do not support a general token-efficiency winner.
