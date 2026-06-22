# Completeness-Critic Stage — Demonstration (q90)

**Date:** 2026-05-29
**Bead:** `escapement-q90` — *Improve adversarial critique method: kill misstatements AND surface gaps/understatements*
**Companion:** `escapement-fxh.10` (the finding this demo surfaces unprompted)

## What q90 fixed

The 2026-05-28 critique's *verify* phase reliably killed **overreach** (refuted 5+
inflated claims) but did nothing for **underreach**: a true finding no lens was
pointed at is never *generated*, so there is nothing for an adversarial verifier to
refute. The write-side triplicate-authoring lean violation slipped that seam and was
caught only by the user.

The fix adds a **completeness-critic** stage to the review/critique pattern — a
*generative* pass (distinct from the *verifying* pass) that asks "what is missing,
understated, or mis-scoped?" and feeds gaps back as a new round. Documented in:

- `claude/skills/dispatching-parallel-agents/SKILL.md` § "Completeness Critic (the underreach pass)"
- `claude/rules/agent-teams-default.md` § "Completeness Critic"

## The demonstration

A real critic agent was dispatched on team `q90-critic-demo`
(`subagent_type: general-purpose`). **Blinding discipline:** the prompt named no
finding. It supplied only (a) the artifact (the repo's write-side workflow files),
(b) the four lenses that "ran" (escape-path / signal-persistence / value-validation
/ Adler–Borys design-features — all per-*gate* lenses), and (c) the three questions.
The acceptance bar: does the critic independently surface the triplicate-authoring
gap?

### Result: surfaced, unprompted, three times over

| Finding | Critic's words | Maps to |
|---------|----------------|---------|
| **M4** (P0, mock) | "Same facts live in three stores: OpenSpec (design intent), beads (task state), contract.json (session oracle)… no lens checks the three stay consistent." | triplicate authoring; existing bead `c3i` (read-side), re-derived from scratch |
| **M2** (P0, mock) | "Two independent oracle-authoring surfaces — the harness contract `--verify` and work-breakdown's acceptance criteria — and no lens checks they agree." | the oracle half of triplicate authoring; `fxh.10` |
| **S4** (P2, mock) | "the contract isn't a gate, it's a competing ledger." | the same redundancy, viewed from the gate side |

The critic also exercised the other two documented requirements:

- **Severity calibrated UP** (not just down): U1 escalated gate-population bloat to
  P0 ("bloated", repo-named); U3 escalated systemic mock bureaucracy to P0.
- **Gaps owned by NO lens listed**: the entire M-series (chain referential
  integrity, oracle coherence, intake/triage correctness, multi-store
  reconciliation, end-to-end outcome verification).

### Provenance of the critic's quantitative claims

Per `evidence-provenance.md`, the load-bearing counts were independently verified
(not taken on the critic's word):

| Claim | Verified |
|-------|----------|
| `.beads/.gate-signal.jsonl` ≈ 497 KB | ✓ 497,610 bytes |
| 15 distinct gates on the write path | ✓ 15 |
| `enforce_named_agents` fired 703× | ✓ 703 (of 1,977 records) |

That a *blinded* subagent produced accurate quantitative evidence — and
reconstructed an already-filed bead (`c3i`) from first principles — is the strongest
available evidence that the underreach pass works as designed.

## Bonus signal (filed, not fixed this session)

The critic surfaced genuinely-new P0/P1 gaps beyond the demonstration target. The
ones already tracked map to `c3i` (M4/M2/S4) and `fxh.12` (U1). The genuinely-new
ones were filed as follow-up beads: **`ao0`** (M1 — spec-id referential integrity
not re-checked after a discovery edit, orphaned anchors) and **`cas`** (S3 — gate
signal is written to `.gate-signal.jsonl` but never read/aggregated, an open
learning loop). Fixing them is out of scope — filing is the correct response to
discovered work; draining unrelated backlog is not.
