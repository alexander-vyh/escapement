## Context

Escapement's OpenSpec and Beads flow is primarily forward-directed: OpenSpec
captures design intent, `/work-breakdown` creates executable Beads with `spec_id`
links, and agents execute against the Beads task graph. OpenSpec is authoritative
for design intent, Beads is authoritative for task state, and the continuation
harness is authoritative for outcome proof.

The missing read-side surface is a fast, honest answer to: for this OpenSpec change,
which Beads exist, what execution state do they report, what is blocked, and — the
part no single tool answers — are the `spec_id` links *honest* (do they resolve to
live anchors, or do they lie)? `bd list --spec <change> --status blocked --json`
already answers the first three. The novel residue is the cross-authority
link-integrity check Beads cannot do, because it requires reading OpenSpec anchors
Beads has no knowledge of.

This change adds an Escapement command that prints that answer. It is not a new
source of truth, not a sync engine, and not a committed artifact. It is an
ephemeral, recomputed-on-demand link-integrity-and-status check over live Beads
state and the live OpenSpec anchor set.

## Why This Design Was Revised

A Jixia-style advisor roundtable (2026-06-13) reviewed the original 20-task plan from
four independent lenses (oracle rigor, utility/minimalism, bureaucracy-decay,
authority/naming) and unanimously voted to revise it. The original would have shipped
a committed `beads-map.generated.json` + `beads-status.generated.md` plus a `--check`
freshness mode. Four findings, each surviving adversarial challenge from the other
lenses, drove the redesign:

1. **The freshness `--check` was a circular oracle.** "Recompute and byte-diff
   against the committed file" proves only `generator(inputs) == generator(inputs)` —
   it certifies its own output, never reality. A generator bug passes because both
   sides run the same buggy generator. The circularity exists *only because a file
   was committed to diff against*.

2. **Authority is read from location, not label.** A committed file in a PR diff
   occupies the structural slot of an authoritative reviewed artifact; a suffix and a
   header are prose a hurried reviewer does not act on. Committing the output
   manufactures the design's own #1 risk ("generated status becomes a second source
   of truth").

3. **The #1 risk lives in a path no guard can reach.** It is realized by a human
   *non-action* — a reviewer trusting the convenient screen instead of re-running
   `bd`. A guard's exit code fires on an action; it cannot fire on a non-action. The
   only cure that reaches a human eye is **non-durability**: a view recomputed to
   stdout has no persisted stale state to over-trust.

4. **The closed-without-proof check was an undefined oracle.** It was specced to
   compare against "harness evidence used by the schema," but the proof field does
   not exist (Open Question #3) and the cross-session proof source is unlocated (Open
   Question #1). A comparison with no right-hand side can only false-green or
   perpetually-red — worse than no check. It is deferred until the proof referent is
   defined.

The mohist lens also established empirically (verified 2026-06-13 against the live
`bd` binary) that `bd list --spec <change> --status blocked --json` already answers
~3/4 of the original review question, so most of the original schema/renderer surface
duplicated tracker output.

## Roundtable Assessment of the Redraft

A second four-lens roundtable (2026-06-13) assessed this redraft for *fidelity* to
the verdict and for *new* defects. It returned **APPROVE-WITH-CHANGES** unanimously,
confirming the redraft did the radical reduction (not a relabel) and rectified the
originally-hollow authority names — and catching defects the redraft itself
introduced. All applied:

- **The lie/silence discriminator (HIGH).** The redraft wrongly fail-closed on a
  Bead that only *mentions* an OpenSpec path in prose. A prose mention makes no claim
  in the structured channel (`spec_id`); only a *present* `spec_id` that fails to
  resolve is a lie. Fail-closed is now a **closed two-member set** — orphaned and
  present-but-unresolved `spec_id` — and a description-only mention is **advisory,
  exit zero**. (Decision 2, 3.)
- **The determinism exclusion hatch.** The redraft excluded "an optional generated-at
  header" from byte-identity — the unbounded volatile-field hole reborn. The
  timestamp now goes to **stderr**; stdout is fully deterministic with no exclusion
  clause. (Decision 5.)
- **The disclaimer echo-oracle.** A SHALL "identifies as non-authoritative" clause is
  a header-by-another-name testable only by grepping its own output — and the
  redraft's own finding #3 proved disclaimers do not stop over-trust. Dropped; the
  load-bearing control is the **no-file** assertion. An authority map may still be
  printed, informationally. (Decision 1.)
- **Materialization gravity (three-lens convergence).** The name "projection" (a term
  of art for a persisted, materialized view), the `--json` re-introduction roadmap,
  and premature waiver/signal ceremony all pull the rejected design back. Fixes: the
  change is **renamed** `beads-openspec-projection` → `beads-openspec-link-check`;
  the roadmap is bound (below); the ceremony is relocated (below).
- **Premature gate ceremony.** `--<name>-waiver` + `_gate_signal` have no actor and
  no consumer in an unhooked slice-1 CLI (the only actor is the human who runs it and
  can fix the link faster than typing a waiver) — building them now is
  mock-bureaucracy by construction. They are **relocated** to a triggered deferral
  that attaches when the command is wired into a hook (Decision 8). Slice 1 keeps the
  cheap, enabling affordance: each failure names the command that clears it.
- **Task reorder.** The close-time-reconciliation inspection blocks *hook wiring*,
  not the stdout skeleton; the skeleton ships first so the riskiest assumption (does
  anyone read it?) is testable cheaply.
- **Time-bound deferrals.** The deferred proof check and the open questions carry a
  review trigger rather than an open-ended "later" (Decision 7).

## Goals / Non-Goals

**Goals:**

- Print a deterministic link-integrity-and-status report for a change from live Beads
  state to **stdout**, with volatile metadata on **stderr**.
- **Fail closed (non-zero exit) only on the closed two-member set of link-integrity
  violations**: orphaned `spec_id` and present-but-unresolved `spec_id`.
- Report progress and silence states (blocked, missing coverage, prose-only mentions)
  advisory-only; they never change the exit code.
- Count a Bead toward requirement coverage only when its `spec_id` **resolves** to a
  live anchor — presence is not resolution.
- Hold no authority, enforced by **non-durability** (no file written), not by a
  disclaimer string.
- Keep slice 1 small enough to test the real riskiest assumption (does anyone read
  this instead of running `bd`?) on one live change.

**Non-Goals:**

- No committed artifacts of any kind.
- No freshness/staleness `--check` mode (there is no durable file to check).
- No closed-without-proof check until the proof referent is defined (Open Q #1, #3).
- No waiver flag or `_gate_signal` ceremony in slice 1 (relocated to hook
  integration — Decision 8).
- No mutation of `proposal.md`, `design.md`, `specs/*`, `tasks.md`, or Beads state.
- No OpenSpec-specific logic in Beads core; no live-tracker dependency in
  `openspec validate`.
- No `schema_version`, provenance fields, JSON↔Markdown split, or renderer in slice 1.
- No failing the exit code on progress or silence states. Failing on "not done yet"
  or on free prose makes a nag that gets disabled with `|| true`.

## Decisions

### 1. Ephemeral stdout, never committed; no authority by non-durability

The command prints to stdout and writes nothing. This is the single highest-leverage
decision: it neutralizes the design's own #1 risk at the structural level (no file =
no location that confers authority = nothing to grow stale = nothing for a hurried
reviewer to over-trust). It also dissolves the freshness-`--check` subsystem, the
volatile-field-exclusion problem, and all branch churn. The command's lack of
authority is enforced by this absence of a durable artifact — **not** by printing a
"non-authoritative" disclaimer (a disclaimer is prose no reviewer acts on; the
redraft's own finding #3 says so). An authority map (who owns intent/state/proof) may
be printed for orientation, but it is informational, not the control.

### 2. Fail closed only on the closed set of link-integrity violations

The exit code is the gate, and it fails closed **iff a structured link claim does not
resolve**. The complete, *closed* set is: (a) orphaned `spec_id` (target missing) and
(b) present-but-unresolved `spec_id` (e.g. anchor renamed). Both are claims in the
`spec_id` channel that fail to resolve — lies. Progress states (blocked, missing
coverage) and silence (a prose path mention with no `spec_id`) are advisory and exit
zero. Test: *is the clearing action the same as the truth-changing action?* For a
non-resolving `spec_id` it is (you fix the link or you don't; there is no
"regenerate-to-green" escape), so the gate is immune to mock-bureaucracy decay.

### 3. `spec_id` must RESOLVE, not merely be present; prose mention is silence

A Bead counts toward a requirement's coverage only when its `spec_id` resolves to an
anchor that exists in the change's current OpenSpec specs. A renamed/normalized anchor
is *present-but-dead* and produces a false-green strictly worse than an orphan, so it
fails closed. A Bead that only *mentions* an OpenSpec path in its description makes no
claim in the structured channel — it is silence, reported as advisory unlinked /
missing-coverage, never fail-closed. (Grep-as-link is rejected by a negative-control
*test* — the implementation must not count a mention as coverage — not by a runtime
gate on the mention.)

### 4. Read live Beads state; never `issues.jsonl`

The command reads `bd` command output (or an equivalent live Beads API resolving
against the Dolt-backed tracker). `.beads/issues.jsonl` is a passive export and is
never treated as authoritative task state.

### 5. Determinism as sort-by-bead-id discipline; volatile metadata to stderr

`bd list --json` ordering is not guaranteed stable, so the command sorts join inputs
by Bead id, making the stdout report body byte-stable across runs on identical live
state. Any volatile metadata (a generated-at timestamp, tool versions) is written to
**stderr**, so stdout carries no exclusion clause — there is no "optional excluded
field" hatch through which the determinism oracle could be weakened.

### 6. Slice-1 escape path is the clearing command; waiver + signal deferred to hooks

Each fail-closed exit prints the command that clears it (e.g.
`bd update <id> --spec-id <valid-anchor>`, or correcting the OpenSpec anchor) — an
enabling affordance that is cheap and useful immediately. The fuller `gate-design`
obligations — a `--<name>-waiver "<reason>"` override and `_gate_signal.record` on
every failure/waiver — attach **when the command is wired into a hook** (Decision 8),
because only then is it a gate with an enforcement actor. Building them for an
unhooked CLI the human runs ad-hoc would be mock-bureaucracy by construction. This is
a recorded triggered deferral, not a silent drop: the obligation is named in tasks.md
so it cannot evaporate.

### 7. Defer closed-without-proof to a follow-up, time-bound on Open Questions

The harness proof field is undefined (Open Q #3) and the cross-session proof source
is unlocated (Open Q #1). Until both are resolved, the command makes no proof claim
and does not gate on proof. It will not assert that a closed Bead means the
requirement is delivered (that principle is preserved), but neither will it fail
closed on an undefined field. The deferral is **time-bound**: a tracking Bead carries
Open Q #1/#3 with a review trigger so the gap has a half-life clock rather than living
as an open-ended "later."

### 8. Reconcile the adjacent close-time control before any hook integration

There is adjacent close-time reconciliation work around linked Beads and OpenSpec
`tasks.md` state. Before this command is invoked from any close/stop hook, its
relationship to that existing control must be inspected on local and `origin/main`
and written down (complements / replaces / independent). Two controls claiming one
station is a name collision that must be resolved first. This blocks **hook wiring**,
not the slice-1 stdout skeleton — the skeleton ships first so the adoption bet is
testable cheaply.

## Risks / Trade-offs

- **An ephemeral view still gets trusted as truth** → nothing is persisted to trust;
  the report is recomputed each run from live state and exists only as transient
  stdout. A human *can* redirect stdout to a file, but the command neither creates
  nor blesses such a file, and nothing in the workflow reads one.
- **`bd` already does most of it** → only the link-integrity check is new code. If the
  report is not read, the cost was an afternoon, not an epic — which is why slice 1 is
  sized to test the adoption bet first.
- **The check becomes a nag** → fail-closed is reserved for non-resolving link claims,
  never for progress or silence; and because clearing == truth-change, it cannot be
  regenerate-silenced.
- **The deferred `--json` mode reintroduces the second-source-of-truth risk** →
  out of scope for slice 1, and treated as a *deferred re-introduction that re-opens
  authority-by-location*, not a free add. Before any persisted mode ships it must,
  as a fail-closed precondition, carry: (a) a closed volatile-field enumeration,
  (b) a pinned-snapshot determinism test, and (c) a consumer-side lint forbidding any
  control-plane script under `claude/`/`harness/` from reading the persisted file as
  input. The *adoption* judgment that would motivate it stays an explicit human call
  (mechanizing "was adoption real?" would be a false oracle); the *technical*
  guardrails above are bound.

## Migration Plan

1. Add the ephemeral command (the stdout skeleton) + the five fixtures.
2. Run it against the one current change that has live `spec_id`-linked Beads.
3. Observe adoption — does a reviewer use it unprompted? (Human-observed; this
   validates the riskiest assumption.)
4. Only after adoption is observed *and* the bound guardrails above are in place:
   consider a persisted `--json` mode, hook invocation at phase boundaries (gated on
   Decision 8), and (gated on Open Q #1/#3) the closed-without-proof check.

Rollback is deleting the script. Because the command mutates nothing and persists
nothing, rollback requires no data migration.

## Open Questions

Scoped as **time-bound blockers for the deferred closed-without-proof work** (tracked
on a follow-up Bead with a review trigger), not slice-1 questions:

- **OQ #1** — Where should outcome-proof evidence be read from for historical Beads
  whose harness sessions are not the active session?
- **OQ #3** — What exact Beads field represents proof or waiver metadata when the
  close reason is not structured enough?
- OQ #2 (commit vs ephemeral) is **resolved**: ephemeral by default. If a persisted
  `--json` mode is ever added, the three guardrails in Risks/Trade-offs become
  required before it ships.
