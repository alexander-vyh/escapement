## 1. Walking Skeleton: Ephemeral Link-Check Command (ship first)

This is the cheap deliverable that tests the riskiest assumption (does anyone read
this instead of running `bd`?). It is unhooked and explicit — no close/stop-hook
wiring (see § 5).

- [ ] 1.1 Implement the read-only command for one change, reading live Beads state
  via `bd` output (or an equivalent live Beads API), resolving only valid `spec_id`
  links against the change's current OpenSpec anchor set, with inputs sorted by Bead
  id.
- [ ] 1.2 Print a link-integrity-and-status report to **stdout**: link-integrity
  violations first (orphaned `spec_id`, present-but-unresolved `spec_id`), then
  advisory items (blocked work, missing coverage, prose-only path mentions), with
  requirement coverage grouped by OpenSpec requirement — not by assignee, and not as
  a percent-complete headline. Write volatile metadata (e.g. a generated-at
  timestamp) to **stderr** so stdout is fully deterministic.
- [ ] 1.3 Exit non-zero iff at least one link-integrity violation exists (the closed
  two-member set above); exit zero otherwise, including when only advisory items are
  present. Write no file and mutate no state.
- [ ] 1.4 On each non-zero exit, print the command that clears the violation (e.g.
  `bd update <id> --spec-id <valid-anchor>`, or correcting the OpenSpec anchor) — name
  the action, not just the upstream layer.

## 2. Oracle And Fixtures (the product)

- [ ] 2.1 Write a Test Oracle Brief (rapid form acceptable). Business invariant: a
  Bead counted as linked has a `spec_id` that **resolves** to a live anchor; a
  non-resolving structured link claim fails the command closed; progress and silence
  states never change the exit code. Include the named fragile implementation to
  reject (see 2.3) and the final outcome verification.
- [ ] 2.2 Add fixtures: (a) a valid `spec_id` that resolves and counts (positive
  control); (b) an orphaned `spec_id` (target change/file/anchor missing — fail
  closed); (c) a present-but-unresolved `spec_id` (anchor renamed — must NOT count,
  must fail closed); (d) a Bead that only mentions an OpenSpec path in its description
  with no `spec_id` (must NOT count as linked AND must NOT change the exit code —
  advisory); (e) a blocked Bead with a resolving link (advisory — exit zero).
- [ ] 2.3 Run a mutation-challenger against the brief and fixtures. Strengthen tests
  until they reject at least: grep-mention-counted-as-link (implementation must not
  count a prose mention as coverage), `.beads/issues.jsonl`-as-authority,
  **present-but-unresolved `spec_id` counted as green** (the shortcut the original
  plan missed), and **prose-mention-gating** (failing the exit on a `spec_id`-less
  path mention — the redraft's own introduced bug; silence must stay advisory).

## 3. Determinism And Boundary Guardrails

- [ ] 3.1 Determinism test: the stdout report body is byte-identical across two runs
  on identical live Beads state and identical OpenSpec anchors (records sorted by Bead
  id). No exclusion clause — the only volatile output is on stderr.
- [ ] 3.2 Boundary test: running the command does not modify `proposal.md`,
  `design.md`, `specs/*`, `tasks.md`, or Beads state. Assert **byte-equality** of the
  intent files before/after, not merely a zero exit.
- [ ] 3.3 Tests proving `.beads/issues.jsonl` is not used as authoritative input and
  a description-only OpenSpec mention is not counted as linked execution.

## 4. Verification

- [ ] 4.1 Run the command against a real current change with live `spec_id`-linked
  Beads; inspect stdout for accurate link-integrity findings and requirement
  coverage; confirm stdout is identical on a second run (stderr may differ).
- [ ] 4.2 Run the focused test suite for the command plus existing `spec_id`
  integrity/preflight tests.
- [ ] 4.3 Final outcome verification: construct a fixture with a renamed anchor,
  confirm the command exits non-zero naming the Bead and unresolved `spec_id`; fix
  the link; confirm it exits zero. Separately confirm a prose-only path mention
  leaves the exit at zero (advisory).

## 5. Deferred (out of slice 1 — each carries a trigger so the obligation cannot evaporate)

- [ ] 5.1 **Close-time-control reconciliation (blocks hook wiring).** Before this
  command is invoked from any close/stop hook, inspect the local and `origin/main`
  state of any existing close-time reconciliation control over linked Beads /
  OpenSpec `tasks.md` and write a verdict: complements / replaces / independent.
  *Trigger: any hook-integration task.*
- [ ] 5.2 **Gate-design ceremony (attaches at hook integration).** When the command
  becomes a hook-invoked gate, add a `--link-check-waiver "<reason>"` override
  (substance-checked, not presence-checked) and `_gate_signal.record(gate=
  'beads-link-check', ...)` on every failure and waiver. *Trigger: § 5.1 hook
  wiring.*
- [ ] 5.3 **Closed-without-proof check (blocked on Open Q #1 and #3).** The proof
  referent is undefined; gating an undefined field can only false-green or
  perpetually-red. File a tracking Bead carrying Open Q #1/#3 with a review trigger so
  the gap is time-bound. *Trigger: resolution of Open Q #1 and #3.*
- [ ] 5.4 **Persisted `--json` mode / renderer (re-introduces authority-by-location).**
  Only after adoption is observed (human judgment). Before it ships it must carry, as
  fail-closed preconditions: a closed volatile-field set, a pinned-snapshot
  determinism test, and a consumer-side lint forbidding control-plane scripts under
  `claude/`/`harness/` from reading the persisted file as input. *Trigger: observed
  adoption + the three guardrails.*
