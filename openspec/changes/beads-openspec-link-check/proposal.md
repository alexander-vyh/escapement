## Why

Escapement already turns OpenSpec intent into Beads execution work. The remaining
read-side gap is answering, for a given change: which Beads exist, what state they
report, what is blocked, and — the part no single tool can answer — whether the
*links between the authorities are honest* (does each Bead's `spec_id` actually
resolve to a live OpenSpec anchor, or is it lying?).

Most of that question is already answered by a command that ships today:
`bd list --spec <change> --status blocked --json`. The genuinely novel residue is
the **cross-authority link-integrity check** Beads structurally cannot perform,
because it requires reading OpenSpec anchors that Beads has no knowledge of. That
residue — and only that residue — justifies new code.

Crucially, the value must be delivered **without manufacturing a second source of
truth**. A committed status artifact placed beside an OpenSpec change occupies the
structural position of "a reviewed artifact the team agreed to," and is therefore
trusted as authority regardless of any filename suffix or disclaimer header. The act
of committing such a file *creates* the staleness-and-second-source-of-truth risk
that a freshness checker would then exist to police. This change avoids the problem
at its root: the check is **ephemeral** — recomputed on demand, printed to stdout,
never committed.

> This change was revised on 2026-06-13 after two four-lens advisor roundtables. The
> first rejected the original committed-artifact + freshness-`--check` design; the
> second assessed this redraft and returned APPROVE-WITH-CHANGES. The rationale, the
> applied changes, and the reason for the rename are recorded in `design.md`
> §§ "Why This Design Was Revised" and "Roundtable Assessment of the Redraft."

## What Changes

- Add an Escapement command that **prints** a Beads-to-OpenSpec link-integrity and
  status report to **stdout** from live Beads state. It writes no committed artifact;
  any volatile metadata (e.g. a generated-at timestamp) goes to **stderr** so stdout
  is fully deterministic.
- **Fail closed (non-zero exit) on a closed two-member set of link-integrity
  violations** — a structured `spec_id` claim that does not resolve: (1) an orphaned
  `spec_id` (target change/file/anchor missing) and (2) a present-but-unresolved
  `spec_id` (e.g. anchor renamed). Nothing else changes the exit code.
- Report **progress and silence states** as **advisory stdout** that never changes
  the exit code: blocked work, requirements with no linked Beads, and a Bead that
  merely *mentions* an OpenSpec path in prose without a `spec_id` (silence is not a
  claim, so it is not a lie).
- **Defer** the closed-without-proof check entirely from this slice: the harness
  proof field is undefined (see `design.md` Open Questions), so any check against it
  is an undefined oracle that can only false-green or perpetually-red.
- Preserve the authority boundary: OpenSpec authoritative for design intent, Beads
  authoritative for task state, harness authoritative for outcome proof, and this
  command's output holding **no authority** — a derived view with no consumer in the
  control plane, enforced by non-durability (no file to trust) rather than by a
  disclaimer string.
- Forbid the command from modifying OpenSpec intent files
  (`proposal.md`, `design.md`, `specs/*`, `tasks.md`) or Beads state.

## Capabilities

### New Capabilities

- `beads-openspec-link-check`: Print an ephemeral, deterministic Beads-to-OpenSpec
  link-integrity and status report from live Beads state, failing closed only on a
  closed set of cross-authority `spec_id` resolution failures.

### Modified Capabilities

- None.

## Impact

- Adds one small read-only Escapement command/script (target ~50–60 lines) under
  `claude/bin/`.
- Adds fixtures and tests as the load-bearing oracle: a valid link that resolves and
  counts (positive control); an orphaned `spec_id`; a present-but-unresolved
  `spec_id` (renamed anchor); a description-only mention (must be advisory — not
  counted as linked and not fail-closed); and a determinism check (stdout
  byte-stable across runs, timestamp on stderr).
- Uses live Beads CLI/Dolt state as input; `.beads/issues.jsonl` is never treated
  as authoritative.
- Writes no committed files; introduces no branch churn or merge noise.
- Does not require changes to Beads core or OpenSpec validator behavior.
