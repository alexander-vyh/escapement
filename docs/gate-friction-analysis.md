# Gate Friction Analysis — Lean Pass (2026-05-29)

Tracking bead: `claude-workflow-setup-fxh.12` (epic `fxh`: remediate the 2026-05-28
critical assessment). This document is the lean-pass decision record for every
**confirmed** gate-friction item surfaced by (a) the 2026-05-28 critical assessment
(`docs/assessments/2026-05-28-critical-assessment.md` §§ 🟡 Bloat / Integration seams /
Attention) and (b) the per-agent friction notes collected across the `fxh` remediation
run.

It is governed by `claude/rules/delicate-art-of-bureaucracy.md` (the four Adler & Borys
design tests) and `claude/rules/gate-design.md` (escape path / persistent signal /
value-not-presence). The lean rule from the bureaucracy principle: *a rule that produces
more friction than the risk it manages is bloat and should be reduced or retired.*

For each item the decision is one of:

- **RESOLVED** — a concrete reduction was applied (named below, with the diff location).
- **KEEP (waived)** — the friction is real but the risk it manages justifies it; a
  waiver-style rationale is recorded so the decision is auditable at the next half-life
  review rather than silently re-litigated.
- **DEFERRED (bead filed)** — reduction is warranted but is out of this docs bead's
  file-scope; a follow-up is named.

The standard against which "keep" is judged: per the half-life operating rule, a kept
gate must still produce signal and still have a first-class escape path. A kept gate with
neither is bloat, not a keep.

---

## Item 1 — Test Oracle Brief: 9 sections is the highest friction-per-value gate

**Source:** assessment § Bloat ("the 9-section Test Oracle Brief is the highest
friction-per-value gate"); `claude/rules/tdd-enforcement.md` § "Test Oracle Brief
Required".

**Confirmed friction:** every non-trivial change must author 9 enumerated sections before
implementation. For a one-line guard-scoping fix (cf. `fxh.5`, `3lq`, `x2o` — narrow,
well-signposted changes) the full 9-section brief is heavier than the risk it manages: the
business invariant, the negative control, and the final-outcome verification carry almost
all the oracle value; the remaining six sections are frequently restatements for a
small-blast-radius change.

**Decision: RESOLVED (light reduction applied to `tdd-enforcement.md`).**
Added a **Rapid form** carve-out to the Test Oracle Brief section: for low-blast-radius
changes the author may collapse to the three load-bearing sections (business invariant,
negative control, final-outcome verification) **provided the named-fragile-implementation
challenge still passes against those three**. This is a *Flexibility* affordance (a
documented second path), not an oracle downgrade — the never-suppress floor is preserved by
keeping the fragile-implementation challenge mandatory in both forms. The full 9-section
brief remains the default and is still required whenever a fragile implementation could
slip the 3-section subset. The carve-out names *when* the short form is illegitimate, so it
cannot be used to dodge a genuine oracle.

**Why not weaker:** dropping any of the three retained sections would remove the negative
control or the outcome check — exactly the oracle-downgrade `never-suppress.md` forbids.
Dropping the fragile-implementation challenge would let the short form rubber-stamp an echo
test. Neither is done.

---

## Item 2 — The continuation-harness blocks 41.6% of Stop events

**Source:** assessment § Bloat ("the harness blocks 41.6% of Stop events — its own
anti-metric was *zero* false positives, violated"); `claude/rules/continuation-harness.md`.

**Confirmed friction:** the harness's own design target was zero false-positive Stop
blocks; in practice it blocked ~41.6% of Stop events. A block is described in the rule as
"noise, not work-halting" (the turn ends, the user sees a prompt, the conversation
continues), but a 41.6% block rate means the gate is firing far more often than its own
anti-metric sanctions.

**Decision: KEEP (waived) — reduction DEFERRED to a harness-code bead (out of file-scope).**

Waiver rationale: the harness Stop gate is the repo's flagship outcome-bias mechanism and
the assessment's own verdict (§ "What genuinely works") is that the outcome-over-action
bias is the system's core value. The fix for an over-firing rate is **not** to loosen the
Stop-permission paths (that would re-open the largest measured stall class —
prose-as-polling — which is the precise failure the gate exists to prevent), but to make
the three legitimate release paths cheaper to satisfy and better surfaced in the denial
message so a correctly-finished agent is not blocked. That is a change to the harness
*code* (`~/.claude/harness/bin/`, the `verify`/contract logic and the denial copy), which
is outside this docs bead's two-file scope (`docs/gate-friction-analysis.md`,
`claude/rules/tdd-enforcement.md`).

Recorded decision: keep the gate; do **not** weaken its release paths; track the
false-positive-rate reduction as harness-code work. The 41.6% figure is the baseline the
follow-up must drive down without loosening the paths. A *measured* block rate is itself
the signal the half-life review needs — the gate is already instrumented, satisfying the
persistent-signal rule.

**Follow-up:** file a harness-code bead under `fxh` to (a) reattribute the false-positive
share to its cause (most likely: agents that *did* finish but did not run `verify` within
the 5-minute window) and (b) tighten the denial message so the cheapest legitimate release
path is the obvious next action. Not closed by this doc.

---

## Item 3 — Three rules repeat the same anti-stopping prose in full

**Source:** assessment § Attention ("three rules repeat the same anti-stopping
instructions in full prose"). The three: `claude/rules/agent-teams-default.md` (§
Continuation Discipline), `claude/rules/outcome-ownership.md` (Wind-Down Anti-Patterns /
Prime Directive), and `claude/rules/continuation-harness.md` (outcome-bias).

**Confirmed friction:** the same "do not wind down / summarizing is not finishing / keep
going" instruction is authored three times in full prose. This is attention-cost bloat:
the reader pays for the same lesson three times, and three copies drift independently at
the next edit.

**Decision: KEEP (waived) — do not de-duplicate by extraction in this pass.**

Waiver rationale: the three copies are **not** redundant restatements of one rule; they are
the same principle applied at three different *enforcement layers*, and each copy is
load-bearing in its own layer:

- `continuation-harness.md` states it as the **mechanical Stop-gate contract** (the three
  release paths; what the hook checks).
- `outcome-ownership.md` states it as the **definition of "done"** (outcome vs.
  intermediate artifact; the verification test).
- `agent-teams-default.md` states it as **subagent-prompt boilerplate** (the exact
  paragraph to paste into a dispatched agent's prompt).

Collapsing them to one canonical source with cross-references would *save* prose but would
break Global Transparency: a subagent prompt needs the literal paragraph inline (a
cross-reference to another rule file is not in the subagent's context window), and the
harness gate needs its contract co-located with the hook it documents. The duplication is a
deliberate redundancy across layers, not accidental copy-paste. The cost (drift at edit
time) is real but small and is the cheaper side of the trade vs. losing the inline
subagent-prompt copy.

Recorded decision: keep all three. At the next half-life review, if the three copies have
*diverged in substance* (not just wording), that divergence is the signal to reconcile —
not the mere fact of triplication. No extraction performed.

---

## Item 4 — discovery-nudge fires with no session dedup

**Source:** assessment § Attention ("discovery-nudge fires on every implementation-intent
prompt with no session dedup"); the planning-discovery nudge hook.

**Confirmed friction:** the nudge re-fires on *every* implementation-intent prompt within a
session, even after the user has already been nudged (or has explicitly declined / chosen
"proceed without discovery") earlier in the same session. Repeated identical nudges in one
session are pure attention cost with zero marginal signal after the first fire.

**Decision: KEEP the nudge, RESOLUTION DEFERRED (hook-code bead) for the dedup.**

The nudge itself is correct and enabling — it routes new feature work into the planning
pipeline per `planning-discipline.md`. The friction is *only* the missing
once-per-session-per-topic dedup. That fix is a change to the nudge **hook code** (track a
per-session "already nudged / user opted out" flag keyed by `CLAUDE_CODE_SESSION_ID`,
mirroring how the harness keys its thread state), which is outside this docs bead's
file-scope.

Recorded decision: keep the nudge; add session dedup as hook work. Until then the nudge is
advisory (it does not block), so the cost is bounded — this is why it is a KEEP-with-pending
reduction, not a blocker.

**Follow-up:** file a hook-code bead to add `CLAUDE_CODE_SESSION_ID`-keyed dedup (suppress
re-fire after first nudge or after an explicit "proceed without discovery" in the same
session). Not closed by this doc.

---

## Item 5 — openspec-staleness ML classifier is over-engineered

**Source:** assessment § Bloat ("the openspec-staleness ML classifier is over-engineered
for the problem size").

**Confirmed friction:** an ML classifier is heavier machinery than the staleness-detection
problem warrants at this repo's scale. Over-engineering is a bloat smell (more mechanism
than the risk justifies) and carries an ongoing maintenance and comprehension cost.

**Decision: KEEP (waived) — no change in this pass; reduction is a code-simplification
bead.**

Waiver rationale: replacing the classifier with a simpler heuristic is a *behavioral* code
change (it changes which specs get flagged stale), so per `tdd-enforcement.md` it needs a
failing-test-first cycle and a positive/negative control proving the simpler heuristic
catches the same staleness the classifier did. That is implementation work outside this
docs bead's two-file scope, and doing it blind (without measuring the classifier's current
precision/recall on real specs) risks regressing detection — a worse outcome than the
over-engineering it removes.

Recorded decision: keep the classifier until a simplification bead can (a) measure its
current hit/miss rate as the baseline oracle and (b) prove a simpler rule meets or beats it
with a negative control. "Over-engineered" is a real but low-severity bloat finding; it is
not urgent because the classifier is not in any agent's hot path.

**Follow-up:** file a code-simplification bead under `fxh` (measure-then-simplify, with the
baseline detection rate as the regression oracle). Not closed by this doc.

---

## Item 6 — mol-feature's 10-step pipeline is heavy for small features

**Source:** assessment § Bloat ("`mol-feature`'s 10-step pipeline is heavy for most
features").

**Confirmed friction:** `mol-feature` runs the full brainstorm → discovery → review →
breakdown → skeleton → validation → build → ceremony retro → outcome pipeline. For a small
feature this is more ceremony than the risk warrants.

**Decision: KEEP (waived) — the lighter path already exists; the friction is routing, not
weight.**

Waiver rationale: the repo **already** ships `mol-rapid` (2 steps, no gates) as the
first-class lighter path for bug fixes, chores, and one-off tasks, and
`planning-discipline.md` already documents the dispatch rule (bug/chore → `mol-rapid`;
feature → `mol-feature`). The heavy 10-step pipeline is *intended* to be heavy — it is the
full-rigor path for genuine cross-cutting feature work, where the ceremony is the risk
control. There is no bloat to remove from `mol-feature` itself; making it lighter would
defeat its purpose and duplicate `mol-rapid`.

The only residual friction is **misrouting** — pouring `mol-feature` for work that should
have been `mol-rapid`. That is a routing-discipline issue (covered by the existing
detection-and-dispatch rule in `planning-discipline.md`), not a weight issue in the
molecule itself.

Recorded decision: keep `mol-feature` at full weight; keep `mol-rapid` as the documented
escape for small work. This item is a confirmed-but-already-mitigated finding: the
lighter-weight path is a first-class, documented alternative — exactly the Flexibility the
gate-design rule requires. No change needed.

---

## Cross-cutting friction from this run (agent notes) — recorded, mostly out of scope

The per-agent notes surfaced several real friction items that are **not** gate-rule bloat
(this bead's subject) but are worth recording so they are not lost. None is resolved here
(all are code/orchestration scope); each is noted as a KEEP-and-track decision:

- **Re-dispatch of already-CLOSED beads** (`s8o`, `g0u`, `c3i`): the orchestrator
  dispatched agents for work whose done-oracle already passed, wasting a full turn each
  time. **Decision:** track a pre-dispatch oracle/status check in the orchestrator. The
  fix is in dispatch logic, not a rule.
- **No uniform block contract across gates** (`fxh.8`, the 12-hook cross-cutting note):
  some gates block via `sys.exit(2)` + deny JSON, others via exit 0 + `permissionDecision`
  JSON. A shared deny helper would make gate tests uniform. **Decision:** track as a
  hook-refactor bead; do not touch gate behavior in this docs pass.
- **`_resolve_signal_path()` duplicated four times** (`cas`): the signal-path resolver is
  copy-pasted across `bin/` and `hooks/`. **Decision:** track an extract-to-shared-module
  bead. Code scope.
- **Symlinked hook code but copied test files** (`fxh.6`): editing the repo's hook is
  picked up via symlink, but the installed test copy under `~/.claude/hooks/tests/` is a
  separate file — a latent footgun. **Decision:** track a reconcile-the-split bead (symlink
  the tests dir or document the split).
- **`pytest <file>` oracle is skip-as-green vulnerable** (`ao0`): a module-level
  `pytest.skip` would make a `pytest <file>` done-oracle pass without the implementation
  existing. **Decision:** track hardening of oracle-command authoring (`--strict-markers`
  / assert-collected>0) in the work-breakdown / oracle-authoring path.
- **Mutation testing via `git checkout` on uncommitted working tree is destructive** (the
  `_gate_signal.py` note): reverting a mutation with `git checkout` wiped the agent's whole
  uncommitted implementation. **Decision:** record as a known hazard for any agent doing
  mutation testing in an orchestrator-owned (uncommitted) working tree — back up to a temp
  file, never `git checkout`. This is operational guidance, captured here.

These are listed so the half-life review has the full friction corpus; they are
deliberately **not** closed by this bead because each lives in code or orchestration scope,
not in the two files this bead owns.

---

## Summary table

| # | Item | Decision | Where reduced / why kept |
|---|------|----------|--------------------------|
| 1 | 9-section Test Oracle Brief | **RESOLVED** | Rapid 3-section form added to `tdd-enforcement.md`; fragile-impl challenge stays mandatory |
| 2 | Harness blocks 41.6% of Stops | **KEEP (waived)** + DEFER | Do not loosen release paths; tighten denial / verify-window via harness-code bead |
| 3 | Three rules repeat anti-stopping prose | **KEEP (waived)** | Deliberate cross-layer redundancy; inline subagent-prompt copy is load-bearing |
| 4 | discovery-nudge no session dedup | **KEEP** + DEFER | Nudge is correct; add `SESSION_ID`-keyed dedup via hook-code bead |
| 5 | openspec-staleness ML classifier over-engineered | **KEEP (waived)** + DEFER | Simplify only after measuring current detection rate as regression oracle |
| 6 | mol-feature 10-step pipeline heavy | **KEEP (waived)** | `mol-rapid` is the documented lighter path; weight is intentional |

Every item is either reduced or carries a recorded keep/waiver rationale — satisfying the
bead's acceptance criterion and the gate-design half-life requirement that no kept gate is
left without an auditable reason.
