## Problem

The 14-gate audit (2026-05-26) revealed that **no gate in this repo
writes its decisions to a durable store**. All signal — denials, asks,
allow-with-warnings, waivers — lives in conversation context and dies
with the session. This violates `claude/rules/gate-design.md` Rule 2
("Every gate must produce persistent signal") universally.

Concretely: there is no way to answer "which gate fires most? for
what? did behavior change after revision?" because the data does not
exist. Operating Rule 1 from the bureaucracy principle file ("every
rule has a half-life") is mechanically unenforceable today.

This change ships the shared infrastructure. Both the
`openspec-beads-staleness` change's learning loop AND the 9 other
gate-audit revisions in epic `escapement-3ky` consume it.
Without this foundation, each gate would invent its own signal sink.

## Riskiest Assumption

We believe a single helper module `claude/hooks/_gate_signal.py`
exposing a `record(gate_name, decision, reason, extras)` function
that appends to `.beads/.gate-signal.jsonl` is enough to capture
every relevant gate decision across the 14+ existing hooks. If wrong,
we discover quickly: either the JSONL shape is too narrow for some
gates (need extra fields) or the location-per-repo is wrong (need
per-session, per-user, or a different store).

## Walking Skeleton

Three concrete tasks in one ~60-minute pass:

1. **Write `claude/hooks/_gate_signal.py`** exposing one function:
   `record(gate_name: str, decision: str, reason: str = "", **extras)`
   that appends a JSON line to `.beads/.gate-signal.jsonl` containing
   `{timestamp, gate, decision, reason, extras, session_id (if
   present)}`. Failures (no `.beads/` dir, disk full) are silent —
   the gate's primary job is enforcement, not logging.

2. **Migrate `spec_id_enforcement.py`** to call `_gate_signal.record()`
   at every decision point (allow, deny, the rare bypass path).
   This is the freshest-edited gate, easiest to validate. After:
   running a few `bd create` commands and inspecting the resulting
   `.beads/.gate-signal.jsonl` should show one entry per gate decision.

3. **Write a query script** `claude/bin/gate_signal_query.py` that
   answers, against `.beads/.gate-signal.jsonl`:
   - "How many times did each gate fire in the last N days?"
   - "What were the reason texts captured for waivers?"
   - "Are any gates whose decisions look uniformly 'allow' (likely
     bloat — never blocks anyone)?"

   **Verify:** `python3 claude/bin/gate_signal_query.py --since 1d`
   produces output naming `spec_id_enforcement` and at least one
   decision recorded.

## Done When

`.beads/.gate-signal.jsonl` exists in this repo after a real
`bd create` operation, `python3 claude/bin/gate_signal_query.py
--since 1d` returns the corresponding entry with the gate name and
decision visible, AND `_gate_signal.record()` has a documented API
that future gate revisions (the 9 in epic escapement-3ky)
can adopt by one-line import.

This change supersedes bead `escapement-3ky.2` as the
implementation surface. The bead will be closed pointing here when
this change ships.
