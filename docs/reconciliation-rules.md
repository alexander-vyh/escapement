# Reconciliation Rules — Three Done-Trackers, One Truth

This repo records "what is done" in **three** places. They overlap, and they can
disagree. This document is the **read-side source-of-truth map**: when you need to
*read* a fact (not author it), which tracker is **authoritative** for that fact, and
what the **reconciliation rule** is when two of them disagree.

> This is the companion to the write-side work that collapsed triplicate *authoring*
> (`escapement-fxh.10` — the bead declares its oracle once, and the harness
> contract is *derived* from it). That work reduced how often the trackers can drift.
> This document covers the case that remains: reading a fact when drift has already
> happened.

The canonical definitions of the three trackers live in
[`VOCABULARY.md`](VOCABULARY.md) (§ OpenSpec, § beads, § continuation-harness). This
file is the **authority-and-conflict** layer on top of those definitions. If the two
disagree, VOCABULARY.md wins on *what a term means*; this file wins on *which tracker
is authoritative for which fact*.

---

## The three trackers and what each owns

| Tracker | Lives in | The fact it is authoritative for |
|---------|----------|----------------------------------|
| **OpenSpec** | `openspec/changes/{name}/design.md`, `specs/`, `problem-framing.md` | **Design intent** — *why* we are building this, the riskiest assumption, what "correct" means at the spec level, non-goals, the walking skeleton. |
| **beads** | local Dolt DB (`.beads/`); `bd ready`, `bd show`, `bd close` | **Task state** — *what* tasks exist, which are open/blocked/closed, dependencies, ownership, acceptance criteria text. |
| **continuation-harness** | `~/.claude/harness/threads/{session_id}/contract.json` (`verify` / `verification_command` / `last_run`) | **Outcome proof** — *whether* the done-oracle for this session's work has mechanically passed (exit 0) within the current-turn window. |

One sentence each: **OpenSpec says what should be true. beads says which work items track making it true. The harness says whether it actually became true.** They answer three different questions; none is a substitute for another.

---

## The source-of-truth map (read-side)

When you need to read a fact, go to the authoritative tracker for that fact — do
**not** infer it from a different tracker that happens to mention it.

| Question you are asking | **Authoritative** source | Do NOT read it from |
|-------------------------|---------------------------|---------------------|
| Why are we building this? What is the riskiest assumption? | `openspec/changes/{name}/design.md` | a bead title (titles compress, they are not the spec) |
| What does component X do in state Y? | `openspec/changes/{name}/specs/` | the implementation, or a bead's acceptance text |
| What tasks exist? Which are unblocked? | beads (`bd ready`, `bd show`) | `tasks.md` (a derived snapshot, see below) |
| Is this task open / blocked / closed? | beads (`bd show <id>`) | the harness `last_run`, or a checkbox in `tasks.md` |
| What is this task's acceptance / oracle? | the bead's `acceptance_criteria` (the fenced ` ```verify ` block) | the harness `contract.json` (it is *derived* from the bead, not the origin) |
| Did the work for this session actually pass its oracle? | the harness (`~/.claude/harness/bin/verify`, exit 0 + `last_run`) | "all child beads are closed" — that is an intermediate artifact, not outcome proof |
| Is the *epic* delivered? | the epic's own acceptance oracle, verified directly | child-bead closure count (see § Child-closure below) |

### Derived artifacts are NOT authoritative

Two files look like trackers but are **passive exports** — reading them as truth is a
known drift trap:

- **`.beads/issues.jsonl`** — a passive export of the Dolt DB, not the source of
  truth. The DB (`bd show`) is authoritative; the JSONL can be stale between syncs.
  (See `CLAUDE.md` § Architecture, and VOCABULARY.md.)
- **`openspec/changes/{name}/tasks.md`** — a human-readable snapshot of the task
  breakdown. The live task state is in **beads**. A checked box in `tasks.md` is not
  proof a bead is closed.

The general rule: **a tracker you can only *read* from a file that another tool
*writes* is downstream — go upstream to the writer.**

---

## The reconciliation rule (when two disagree)

The trackers answer different questions, so a "disagreement" almost always means one
tracker is **stale** relative to its authoritative peer. Resolve by *layer*, not by
recency or convenience:

> **Each fact has exactly one authoritative layer. When trackers disagree on a fact,
> the authoritative layer for *that fact* wins, and the disagreement is a signal that a
> downstream tracker is stale and must be reconciled to the authority — never the
> reverse.**

Concretely:

1. **Design intent vs. task state** — `design.md` wins on *intent*; beads wins on
   *task state*. If a bead's scope contradicts the spec, the **spec is authoritative on
   what should be built**; the bead is wrong and is re-scoped (via the human-driven Spec
   Amendment flow — see `molecule-awareness.md` § Scope Change Detection). You do not
   silently edit the spec to match a bead.

2. **Task state vs. outcome proof** — beads owns whether a task is *closed*; the
   harness owns whether the *oracle passed*. These must agree at close time: **a bead
   should not be closed unless its oracle has passed.** If a bead is closed but the
   harness has no passing `last_run`, treat the **harness as authoritative on the
   outcome** — the close was premature. Re-open or re-verify; do not trust the closed
   status as proof of done.

3. **Outcome proof vs. "all children closed"** — the harness/oracle wins. Closing
   every child bead is an *intermediate artifact*, not the parent's outcome (see below).

4. **Anything vs. a derived artifact** (`issues.jsonl`, `tasks.md`) — the **upstream
   writer wins**, always. Reconcile the export, never the DB to the export.

The reconciliation direction is fixed: **stale downstream → reconcile to authoritative
upstream.** The only thing that flips an *authoritative* value is the human-driven
process that owns it (a Spec Amendment for design intent, a `bd` operation for task
state, a re-run of `verify` for outcome proof).

---

## Child-closure is not parent-completion

A parent/epic is done when its **own** stated scope is delivered and its **own** oracle
passes — **not** when its child count reaches zero-open. "All children closed" is the
task-state tracker's intermediate artifact; the *outcome* lives in the epic's own
acceptance oracle.

Two distinct failure modes, both real (see `outcome-ownership.md` § Child-Closure):

- **Coverage gap** — the child set never covered the whole parent scope; a named seam
  got no child, so it was never built, yet the parent reads as done.
- **Verification gap** — even with full coverage, "all children closed" was used as the
  close condition instead of running the parent's own oracle.

**Reconciliation:** before closing any parent, read the parent's *own* description and
acceptance criterion, confirm every named seam maps to a closed child, and run the
parent's own oracle. The `epic_coverage_gate.py` hook enforces the coverage half of
this at `bd close <epic>` time (`escapement-g0u`).

---

## Two known cross-tracker conflicts (read-side)

These are not hypothetical — they are the specific seams this bead
(`escapement-c3i`) was filed to document. Each is a place where one tracker
*structurally cannot see* a fact another tracker owns.

### Conflict 1 — the shirking gate vs. the harness's blocker-bead escape

**The tension.** `claude/rules/continuation-harness.md` sanctions a legitimate
terminal state: *"documented failure is also an outcome"* — file a blocker bead
explaining why you cannot complete the work, then stop. But `validate_no_shirking.py`
fires on *phrases* (e.g. "this is a pre-existing failure", attribution-deflection) and
blocks the Stop, **without recognizing that a blocker bead was filed.** Verified
2026-05-29: the gate has no `bd create` / blocker-bead detection; its only first-class
escape is **user release** ("yes" / "proceed" / "lgtm" / "approved" / "go ahead"),
captured to the signal log.

**Read-side resolution (what to believe today).**

- The shirking gate is authoritative on **"did the agent emit a shirking phrase this
  turn"** — a *linguistic* fact about the transcript. It is **not** authoritative on
  **"is this work genuinely blocked"** — that is a *task-state* fact owned by beads.
- A filed blocker bead (`bd create --type=bug ...` + `bd update <id> --status=blocked`)
  is the **authoritative record that the work is blocked**, even when the shirking gate
  has fired on the same turn. The two are not in real contradiction: one is about words,
  the other about task state.
- **Reconciliation:** when you have genuinely filed a blocker bead and the shirking gate
  still blocks, the resolution is the gate's documented escape — **user release** —
  *plus* the blocker bead as the durable record. The release is logged as labeled
  training data; a recurring false-positive category is pruned at half-life review. Do
  **not** rephrase the blocker to dodge the phrase matcher (that is suppression). Do
  **not** treat the gate's block as evidence the work is *not* blocked — beads owns that
  fact, not the gate.

> **Write-side fix (delivered 2026-05-29, `escapement-c3i`):**
> `validate_no_shirking.py` now recognizes a freshly-filed blocker bead as a first-class
> non-user escape. When a shirking phrase matches *and* the turn carries a **structural**
> blocker-bead filing signal — a `bd create` invocation, a filing verb collocated with
> "blocker bead", or a filing verb plus a concrete bead id with blocker framing — the
> block is released and logged as `waiver-accepted` signal (gate-design Rule 2). The bare
> word "blocker"/"blocked" in passing never triggers the escape (no blanket bypass). The
> agent no longer has to round-trip through the human for a sanctioned outcome; user
> release remains available as the fallback escape.

### Conflict 2 — gate-signal is a single point of failure in `.beads/`

**The tension (resolved 2026-05-29, `escapement-c3i`).** Every signal-emitting
gate writes to `.beads/.gate-signal.jsonl` via `claude/hooks/_gate_signal.py`. Previously,
when no `.beads/` directory was locatable (no `BEADS_DIR` env var and none found walking up
from CWD), `record()` **silently no-opped** — returning without writing and without raising,
with **no log fallback** outside `.beads/`, so any repo or worktree without beads produced
**zero signal**, silently. **Fix:** `record()` now falls back to
`~/.claude/harness/gate-signal-fallback.jsonl` (directory overridable via the
`GATE_SIGNAL_FALLBACK_DIR` env var) when the primary `.beads/` path cannot be resolved, so
signal is preserved rather than dropped. The write stays fail-soft — a failing fallback
never raises and never blocks a gate decision.

**Read-side resolution (what to believe today).**

- `.beads/.gate-signal.jsonl` is authoritative on **gate decisions** *only when
  `.beads/` exists*. Where it is absent, **absence of signal is not evidence of absence
  of gate firings** — the gates still fired and still blocked; they just left no record.
- **Reconciliation:** never read an empty or missing `.gate-signal.jsonl` as "no gates
  fired here." Read it as "this context could not persist signal." A half-life review
  (`claude/bin/gate_signal_analysis.py`, `escapement-cas`) run against a
  no-`.beads/` context will correctly print a zero-row notice and exit 0 — that zero is
  a *measurement gap*, not a measured zero.

> **Write-side follow-up (out of scope for this read-side doc):** give `_gate_signal.py`
> a fallback sink (e.g. `~/.claude/harness/.gate-signal.jsonl`) when `.beads/` is absent,
> so the loop is not a single point of failure. The acceptance criterion on this bead
> names this gap; the fix is a separate write-side change.

---

## Quick reference

- **Design intent** → OpenSpec `design.md` / `specs/`. *Authoritative on "what should be true."*
- **Task state** → beads (`bd show`, the Dolt DB). *Authoritative on "which work tracks it."*
- **Outcome proof** → continuation-harness (`verify`, `contract.json#/last_run`). *Authoritative on "did it actually become true."*
- **Reconciliation direction** → always stale-downstream → authoritative-upstream; an authoritative value flips only via its own human-driven process.
- **Derived files** (`issues.jsonl`, `tasks.md`) are never authoritative — go to the writer.
- **Child closure** ≠ parent completion — verify the parent's own oracle.
- **Empty gate-signal** ≠ no gate firings — it can be a measurement gap (no `.beads/`).
- **Shirking block** ≠ "not blocked" — beads owns blocked-state; the gate owns phrase-detection.
