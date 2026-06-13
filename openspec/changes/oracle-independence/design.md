## Problem Statement

Every quality signal in an agent workflow is self-authored by the implementing agent
(its own test, `verify` command, oracle), so QA discipline is unenforceable and
verification gaps reach `main` — demonstrated by the cake incident, where 4 verbatim
seam-extraction PRs merged with self-authored characterization tests that could not have
caught a transcription error in the moved code. When this ships, a verbatim-refactor
transcription error can no longer reach `main` unblocked, and non-trivial work is routed
to a boundary independent of the implementing agent rather than judged by an oracle that
agent wrote.

## Non-Goals

1. **No blocking intake gate (a first-edit "is this routed?" gate).** Locks in:
   enforcement lives at *landing* (a self-validating check) and at *entry* (enabling
   routing), never as a byte-zero block. Rejected because it is a category error (a hook
   sees tool metadata, never oracle provenance) and inherits the 74%-false-positive
   dismissal death measured this session from `.beads/.gate-signal.jsonl` (tdd_gate: 461
   `ask` / 164 `allow` ≈ 74%; `validate_no_shirking`: 766 `deny` / 39 `waiver` ≈ 95%).
2. **No "process-commitment" fields on the contract** (e.g. "test-first: yes",
   "QA-owner: …"). Locks in: the contract stays a pure exit-code outcome oracle,
   preserving outcome-bias-over-action-bias. Rejected because such fields are
   self-attestation no decision function can verify.
3. **No hook that verifies QA-agent independence** ("an independent QA agent signed
   off"). Locks in: independence comes only from a self-validating oracle or an
   out-of-session human boundary — never from hook-observable dispatch metadata.
   Rejected as the same category error. **A live instance already ships:**
   `review_gate.py` reads subagent type/name/prompt to decide "a review agent was
   dispatched" and lets `bd close` through on that basis — exactly dispatch-metadata
   standing in for independence. This change does NOT extend it; it stays a soft
   in-session nudge, is *not* the out-of-session boundary escape-(b) relies on, and its
   existing `allow` signal is the baseline against which Success Criterion #5 (no *new*
   self-attested green) is measured.
4. **No mutation testing as a per-commit gate.** Locks in: mutation, if used at all, is
   an async-CI signal only. Rejected as a gate on cost (minutes–hours/commit) and
   non-determinism (equivalent-mutant unreachability).
5. **No mechanical guarantee for the non-verbatim-refactor-with-hidden-behavior-change
   class.** Locks in: that narrow class is named human residue, not pretended-covered.
   Conceding it honestly is the alternative to a checkable-looking gate that isn't.

## Capabilities

### New Capabilities
- `human-gate-independence` — present the design/review gate with a reference
  *independent of the agent's diff* (prior behavior / spec), so the human boundary
  yields real independence rather than rubber-stamping the agent's framing. (The
  walking skeleton tests this capability's premise before it is built out.)
- `landing-relocation-proof` — a self-validating landing check: AST body-identity +
  call-site-arity proof over a relocation diff, fail-closed on verbatim-refactor
  transcription errors (copy-not-move, `>`→`>=`, wrong-arity). Needs no spec, no human,
  no trusted author.
- `enabling-entry-routing` — auto-route non-trivial work into a molecule from the
  opening description (enabling default, not a block), so work reaches the human
  boundary without the agent having to remember to. (Second-order; gated on the
  riskiest assumption surviving.)

### Modified Capabilities
- The mol-feature design/review gate (currently human-resolved) gains the independent
  reference required by `human-gate-independence`.

## Impact

- `claude/hooks/` — a new landing check (PreToolUse on commit/push, reusing the landing
  surface already present in `test_oracle_brief_gate.py`); possibly a UserPromptSubmit
  routing nudge for `enabling-entry-routing`.
- The human design/review boundary — the **mol-feature beads gate** resolved by a human
  via `bd gate resolve` (per `molecule-awareness.md`), NOT `review_gate.py` — gains the
  independent reference. (`review_gate.py` is a separate in-session `bd close` nudge, a
  live instance of the Non-Goal #3 pattern, and explicitly not the boundary here.)
- `.beads/.gate-signal.jsonl` — the landing check self-instruments here (no standalone
  detector); the bypass rate is read off its own deny/allow signal, labeled honestly.

## Riskiest Assumption

We believe **the human design gate produces genuine independence — it catches what the
agent's self-framing of a diff hides — at least when handed a reference independent of
that diff.** We will know this is true when a *blinded* probe shows the reviewer catches
a planted refactor-transcription error *with* the independent reference that they *miss*
without it. If false, we abandon the route-to-human-boundary half entirely and rely on
self-validating oracles only (the relocation proof + discriminating tests for behavior-
change), explicitly ceding the non-verbatim refactor class to acknowledged human residue.

This outranks classifiability (Risk A): routing only decides auto-vs-manual; the human
gate decides whether the destination is real at all. If it rubber-stamps, escape-(b)
does not exist and half the architecture dies — a far larger blast radius than routing
degrading to manual.

## Walking Skeleton

Tests the riskiest assumption (B) — *not* the relocation proof, which is near-certain.

1. **Assemble a blinded probe set** (30–60 min): collect ~5–8 real, already-merged
   refactor diffs the reviewer has not closely reviewed; inject ≥1 planted transcription
   error (e.g. `>`→`>=` in a moved body) the reviewer has not seen. Record which is
   planted, out of the reviewer's view.
2. **Run the gate review in two conditions** (30–60 min): present each diff (a) with the
   agent's framing only ("verbatim extraction, tests pass"), then (b) additionally with
   an independent reference (the pre-move behavior / spec). Record catch vs. miss in each
   condition.

Done (matching Proof of Delivery, not merely "a number recorded"): the premise is
recorded TRUE iff the with-reference condition catches a planted error the framing-only
condition missed; recorded FALSE (→ abandon escape-(b)) if the reference changes nothing.
Caught-in-both and missed-in-both are explicit FALSE/inconclusive outcomes — not "done."

## Proof of Delivery

This is worth continuing when the reviewer, handed the independent reference, catches a
planted transcription error that they missed from the agent's framing alone — i.e. the
independent reference demonstrably converts a rubber-stamp into a real check.

## Anti-Metrics

1. **Landing-check interrupt rate approaching tdd-gate's ~74%.** If the relocation proof
   fires on a large fraction of normal commits, it has failed even when "correct" — it
   will train the dismissal reflex and be disabled.
2. **Any increase in self-attested "QA happened" green records.** If the system starts
   emitting confidence-inflating signals (the net-negative failure mode), it has failed
   even if it also catches some errors.
3. **The solo user bypassing or disabling enabling-entry-routing.** If routing adds
   friction the owner routes around, it has failed — routing must be the path of least
   resistance, not a toll.

## Decisions

- **Verify at landing, route at entry — never block at the first edit.** A hook cannot
  observe oracle provenance, and byte-zero "non-trivial?" classification is unanswerable;
  landing fires on a sizeable diff where the question is answerable and the oracle is
  inspectable.
- **Self-validating oracle (relocation+AST proof) as the escape-(a) core**, chosen over
  an agent-signoff artifact (spoofable — a hook sees *that* a QA agent ran, never *what*
  it was shown).
- **Independent-reference presentation at the *existing* human gate as escape-(b)**,
  chosen over building a new independence mechanism — independence is a privilege
  boundary an agent lacks against itself, so it cannot be manufactured in-session; the
  out-of-session human boundary mol-feature already has is reached by routing, not built.

## Risks & Trade-offs

- **Risk B is hard to test cleanly**, and the contamination is deeper than vigilance:
  for a solo owner, **author == probe-author == reviewer** — the person who planted the
  `>`→`>=` is the one tested on catching it. Blinding (real already-merged diffs the
  reviewer didn't author) blunts vigilance but cannot survive author==subject over a
  single trial. → A single self-administered trial is therefore **suggestive, not
  validating**: it can only *falsify* (a miss-with-reference kills escape-(b)) cheaply; a
  positive does NOT purchase build-out. The real confirmation is the deferred forward
  natural experiment, which must use a **different planter** than the reviewer. This
  difficulty is *itself* why B is riskiest: hard-to-falsify risk bites late.
- **Relocation proof may exceed the ~40-LOC estimate** (reference-resolution
  normalization for move-correlated reference fixups is scope analysis, not token
  canonicalization). → Ship first as a *sound but noisy* async tripwire (over-flags in the
  safe direction, never silently green); promote to a live per-commit gate only after
  normalization lands.
- **Routing (Risk A) deferred behind B.** Accepted: the relocation proof covers cake's
  class regardless of routing, so deferring A strands nothing on the critical incident.

## Future Increments

[PLACEHOLDER] — purchased by validating the riskiest assumption:
- Productionize `landing-relocation-proof`: reference-resolution normalization →
  promote from async tripwire to live per-commit gate; characterization suite for the
  dynamic-reachability residue (dead-code path / shadow-dispatch).
- `enabling-entry-routing` (the Risk A classifier spike) — run only if B survives.
- Discriminating-oracle landing check for the behavior-change class (fails-pre/passes-
  post), with the spec→oracle freeze (content-hash) that makes the human-approved
  requirement tamper-evident.

## Open Questions

- **[DEFERRABLE]** What does the real human gate — the **mol-feature design/review beads
  gate** resolved via `bd gate resolve` (per `molecule-awareness.md`), *not*
  `review_gate.py` — currently present to the reviewer? The skeleton defines its own two
  conditions regardless, but the *production* `human-gate-independence` capability must
  match that gate's surface before build-out.
- **[DEFERRABLE]** The skeleton tests whether a human *uses* a reference when handed one
  — NOT whether the system can *generate* a trustworthy reference. For refactors the
  reference is a pre-move behavior snapshot, itself coverage-floored. Reference
  *generation* is a separate bet the build-out hits immediately; surviving the probe does
  not de-risk it.
- **[DEFERRABLE]** For refactors, the "independent reference" is a pre-move behavior
  snapshot, which is itself coverage-floored. Resolve when designing the production
  reference, not for the skeleton.
