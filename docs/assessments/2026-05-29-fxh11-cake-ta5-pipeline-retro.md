# fxh.11 — Pipeline retro: the apparatus on real, non-meta work (cake-ta5)

**Date:** 2026-05-29
**Spike:** escapement-fxh.11 — "Prove the whole system end-to-end on one
real, non-meta task." Closes the assessment's deepest finding: *100% of completed work
is meta; the system has only ever built itself.*
**Target (chosen by the user):** `cake-ta5` — Python God-module decomposition in the
`cake` repo (real product refactoring, in progress). Verified **read-only** while the
user works it live; no cake state was modified.

## What "non-meta" buys us
cake-ta5 is genuine product work: decomposing `cake/cli.py` (~5165 LOC, 7 semantic
seams) and two processors into a `cake/operations/` package. It has nothing to do with
the workflow tooling — so exercising the apparatus on it is the first evidence the system
delivers value beyond its own maintenance.

## Verification: is the pipeline actually exercised end-to-end?

| Stage | Evidence (read-only, real) | Verdict |
|-------|----------------------------|---------|
| **Discovery** | `docs/analysis/god-modules-2026-05-23.md` (9.4 KB seam analysis) + openspec change `decompose-cake-cli/` with `problem-framing.md`, `design.md`, `callers.md`, `handler-audit.md`, `decisions/`, `specs/`, `tasks.md` | ✅ genuine |
| **OpenSpec design** | full `decompose-cake-cli` change authored from discovery | ✅ |
| **Walking skeleton** | `cake-ta5.1.3` literally *"hoist ONE handler end-to-end (riskiest-assumption verdict)"* — closed | ✅ textbook |
| **Beads breakdown** | epic → `cake-ta5.1` → 14 children in dependency-ordered Waves 1–7; real blocked dep (`.1.11` on a Confluence merge); P1/P2 | ✅ |
| **Oracle / TDD gate** | `cake-ta5.1.6` *"characterization-test gate for cake/operations/"*; commits: "BQ dry-run integration oracle", "positive-control tests to catch broken NetSuite sources", "3-surface gate" | ✅ strong |
| **Shipped** | 11 of 14 `cake-ta5.1` children closed; bead IDs in every commit (`cake-ta5.1.3`, `.1.7`, …) | ✅ |
| **Contract → verify** | *indirect:* heavy oracle-gate activity + oracle-quality commits; harness `contract.json`/`verify` runs not directly attributed to cake-ta5 (gate-signal isn't bead-tagged — see below) | ⚠️ indirectly evidenced |

**Gate-signal corpus** (`cake/.beads/.gate-signal.jsonl`, 635 entries) — the apparatus
firing on real work:
- decisions: **allow 503 · deny 102 · ask 13 · nudge 11 · override-applied 6**
- top gates: `test_oracle_brief_gate` 276 · `tdd_gate` 134 · `serena_preference_gate` 95
  · `implementation_echo_test_gate` 51 · `oracle_downgrade_warning_gate` 48 ·
  `enforce_named_agents` 22 · `context_burn_detector` 7 · `validate_no_shirking` 2

## Helped vs hindered (the honest retro)

### Helped
- **Walking-skeleton discipline on a 5165-LOC monster.** The decomposition led with
  "hoist ONE handler end-to-end, riskiest-assumption first" (`.1.3`) before the 14-wave
  breakdown — exactly the planning-discipline rule, and it structured an intimidating
  refactor into shippable slices.
- **Gates are NOT inert on real work.** 126 interventions (102 deny / 13 ask / 11 nudge)
  out of 635 — this is the data point the assessment's "gates mostly inert" worry lacked.
  On real work the oracle gates bite hard.
- **Oracle quality propagated to the product.** `test_oracle_brief_gate` (276) and
  `tdd_gate` (134) dominate; the commit log shows the *result* — real oracle upgrades
  ("DDL string-echo test → BQ dry-run integration oracle", positive-control tests).
- **OpenSpec discovery produced a usable design**, not checkbox docs (problem-framing →
  design → handler-audit → specs → tasks).

### Hindered / friction (each maps to an existing backlog finding)
- **Gate volume is heavy.** 276 oracle-brief + 134 tdd fires + 102 denies on one epic is
  real friction-per-edit. → reinforces `fxh.12` (lean-pass gate friction).
- **The documented waiver convention isn't deployed.** Acceptance asked for "≥1 waiver in
  the corpus"; `.gate-waivers.jsonl` does not exist in cake. Escapes are recorded as
  `override-applied` (6×) in the unified `.gate-signal.jsonl` instead. The escape path IS
  exercised — but not via the `--<gate>-waiver` file convention in `gate-design.md`. →
  self-consistency gap; the waiver-file standard is aspirational, not live.
- **Gate signal isn't bead-attributed.** Only 2 of 635 entries mention `ta5`, so gate
  activity cannot be sliced by task — you can't ask "how much did the gates cost *this*
  epic." → reinforces `c3i` (sources of truth don't reconcile).
- **Three "done" surfaces, unreconciled.** The migration's state lives across beads
  (cake-ta5 waves), openspec (`decompose-cake-cli`), and harness contracts — observed
  exactly the `fxh.10`/`c3i` triplicate-tracking tension on live work.

## Acceptance reconciliation (honest)
- discovery → openspec → beads → (walking skeleton) → ship: **met**, with real artifacts.
- contract → verify: **indirectly** evidenced (oracle-gate activity + oracle commits); not
  directly tied to cake-ta5 because the signal log isn't bead-tagged.
- "≥1 waiver lands in the corpus": **not met as literally worded** (no `.gate-waivers.jsonl`).
  Substituted by 6 `override-applied` escape-signal entries. **Not manufactured** — doing so
  would be the gaming the spike exists to catch. Recommend amending the criterion to
  "≥1 escape/override recorded" and filing the waiver-file-not-deployed gap.

## Verdict
The apparatus is genuinely, heavily, and *usefully* exercised on real non-meta work — the
"only ever builds itself" finding is **disproven**. The friction it generates is real and
already tracked (`fxh.12`, `c3i`, `fxh.10`). The one integrity snag (waiver-file convention
not deployed) is recorded honestly rather than papered over.
