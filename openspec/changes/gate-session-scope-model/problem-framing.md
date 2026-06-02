# Problem Framing — Gate Session-Scope Model

**Bead:** `claude-workflow-setup-858`. Confirmed inputs to discovery. Source: the
`scope-panel` charter from the team-lead this session, restating a live false-positive
incident in the continuation-harness Stop gate. This framing restates the handed-down
incident — it is not a fresh inference.

## Problem

The continuation-harness Stop gate (`harness/bin/stop_hook.py`) cannot distinguish a
session's own just-decided beads work from unrelated repo backlog or other sessions'
long-running epics. When `session_mode.json` is absent, the gate falls to
`_check_bd_queue_implicit(cwd)` (stop_hook.py:210), which runs `bd list --status=in_progress`
and `bd ready` **repo-wide and unscoped** and blocks Stop if either is non-empty.

Observable symptom: a session that had **completed** its actual work was Stop-blocked because
the repo had ready backlog (`uf5`, `7ki`, `385`) plus an unrelated in-progress epic (`a2n`) —
none of which were in the session's scope. The unscoped queue read as "you're not done."
*(Provenance: reported by the team-lead this session; the code path is verified by inspection.
The specific bead IDs are as reported, not independently re-queried.)*

Secondary problem (same bead): `claude/hooks/validate_no_shirking.py` keyword-matches
dismissive phrases in the agent's own prose and fires even when the agent is *discussing a
false positive of the gate itself* rather than shirking. Its existing guards
(`_strip_code_spans`, `_inside_quotes`, `_negation_guards`) cover quoting/negation but not
gate-meta discussion.

## Why now

Three harness fixes already landed this session (PRs #12 worktree false-allow, #13 Stop
messages drive continuation, #14 validate_no_shirking ignores prose/docs edits) strengthening
the harness's positive continuation signals. This scope defect is the named residual. The
harness is actively gating live sessions, so the false-positive is recurring (it just blocked
a real completed session), not hypothetical — leaving it unfixed means every session with
repo backlog risks a spurious block.

## Decision authority

`none — solo personal tooling owned by the user.` The team-lead chartered the panel; the user
owns the harness. No external stakeholder sign-off is required.

## Behavioral population

`none — single-user harness; only the user's own Claude Code (and adapter) sessions consume
the Stop gate.` The "population" affected is the set of the user's own sessions running in any
beads-tracked repo.

## Riskiest assumption

That a session's in-scope work can be captured **positively** (an explicit per-session
manifest, plus the existing contract `verify` and wakeup signals) reliably enough that the
unscoped repo-wide block can be **downgraded to advisory** without stranding real in-scope
work (a premature stop — the primary risk, weighted above false-positives).

Wrong when:
- A session does real in-scope work entirely inside **subagents** whose claims never reach the
  parent manifest, AND registers no contract — then downgrading the unscoped block could let it
  stop prematurely.
- The manifest writer races (concurrent PreToolUse fires) and drops a bead, so in-scope work is
  invisible to the gate.
- The `_is_meta_discussion` shirking guard is too broad and lets a genuine deflection through
  (a false-negative on the never-suppress axis).

Liveness: detectable by counting `scope_advisory_allow` incidents in `incidents.jsonl` after
deployment — a high rate means the blind spot is common and the downgrade is risky; a low rate
means the manifest path covers the cases and the downgrade is safe.

## Success criteria

- The reported incident replays to **`allow`**: no manifest + repo backlog (`uf5`/`7ki`/`a2n`)
  present ⇒ Stop is **not** blocked.
- A session with a **real in-scope** open bead in its manifest still **cannot** stop (negative
  control — premature-stop hole stays closed).
- Genuine shirking that merely **mentions** the gate is still **caught** (negative control —
  meta-guard is not a loophole); genuine meta-discussion of the gate is **allowed**.
- `harness/tests/` and `claude/hooks/tests/` stay green; the new behavior is covered by tests
  that reject the named fragile implementations.
- Scope decisions are observable in `incidents.jsonl` (a `scope_decision` field) so half-life
  review can measure the advisory-path rate.
