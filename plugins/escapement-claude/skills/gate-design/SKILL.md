---
name: gate-design
description: Use when adding or modifying a hook, gate, denial/permission message, or waiver/exemption/override path; when deciding whether to keep, revise, or retire a rule or gate; or when auditing a gate or triaging a complaint that a gate causes friction. The implementation manual for building gates that are enabling not coercive — escape paths, persistent signal, value-not-presence validation, with audit-validated reference designs and anti-patterns.
---

> This is the full gate-design manual, loaded on demand. The always-on stub
> (`~/.claude/rules/gate-design.md`) carries just the 3-rule checklist; load
> this skill when you are actually authoring or auditing a gate.

# Gate Design — Global Rule

This rule is the operational complement to
`claude/rules/delicate-art-of-bureaucracy.md`. The principle file
states *what good bureaucracy looks like* (lean, learning, enabling
along four design features). This rule states *how to actually build a
gate that satisfies those features*.

Three operating rules below, derived from auditing the existing gates
in this repo (2026-05-26) against the bureaucracy principle. Each rule
includes the reference designs and anti-patterns the audit surfaced.

## Rule 1: Every gate must have a first-class escape path

A gate whose only outcomes are "comply" or "fail" is on the coercive
axis. To stay enabling, every gate MUST offer at least one escape path
that meets all four of these conditions:

- **Documented in the denial message itself.** The escape is the path
  forward; if the agent has to read source code to find it, the gate
  has failed Internal Transparency.
- **Agent-invokable without escalating to the user.** "Run `bd close
  --spec-waiver '<reason>'`" is invokable. "Ask the user for
  permission" is not.
- **Captures a reason as signal.** Per Rule 2, the escape's reason
  text becomes labeled training data for future revisions of the gate.
  A checkbox waiver produces no learning.
- **Does not require disabling the gate.** "Add `# noqa`" or "comment
  out the hook" are not escapes; they are the gate failing the
  never-suppress rule.

### Standard waiver convention

When a gate's escape path takes the shape of a waiver — the agent
asserts a reasoned exception — every gate in this repo uses the same
convention so the waiver corpus is uniform and the user can grep one
file instead of N:

- **Flag shape:** `--<gate-name>-waiver "<reason>"` on the relevant
  command (e.g., `--spec-waiver`, `--brief-waiver`,
  `--echo-test-waiver`). Per-gate naming so a single command can
  satisfy or fail to satisfy multiple gates without ambiguity.
- **Reason is required free-text, not a checkbox.** Minimum 20
  characters. Null patterns rejected: `tbd`, `n/a`, `todo`, `wip`,
  `?`, `??`, `???`, whitespace-only, and reasons that echo the
  source artifact verbatim (bead title, file path).
- **Reason persists to the signal store** (`.beads/.gate-signal.jsonl`
  via `claude/hooks/_gate_signal.py` per Rule 2). The persisted
  record carries the gate name, the decision (waiver-accepted), the
  reason text, and the command excerpt. The corpus is the labeled
  training data for future revisions of the gate.
- **Reasons accumulate, not evaporate.** A waiver entry never expires
  from the log. The half-life review (Operating Rule 1 from the
  bureaucracy principle) looks at *which reasons recur* to decide
  whether the gate's heuristic should be updated or the rule itself
  revised.

If a gate cannot use the standard convention (e.g., it fires on a
context where additional flags can't be parsed), the design.md or
commit message MUST state the reason and document the alternative
escape — the gate cannot silently omit a waiver path.

### Reference designs (audit-validated 2026-05-26)

- **`discovery_input_gate.py`** — `schema: rapid` is a first-class
  exemption; `none — <reason>` is accepted as a filled value for
  fields that genuinely don't apply.
- **`tdd-gate.py`** — denial says `say 'proceed' to skip TDD for this
  change`. Agent-invokable, zero-friction, no source-reading required.
- **`serena_preference_gate.py`** — denial enumerates four alternative
  Serena calls with the correct parameters injected for *this specific
  file path*. The "escape" IS the correct path; the gate is a redirect
  with affordance.
- **`no_direct_send_guard.py`** — redirects `slack_send_message` to
  `slack_send_message_draft`. The escape is the correct tool.

### Anti-patterns

- **Hard deny with no contest path.** `test_oracle_brief_gate.py` and
  `implementation_echo_test_gate.py` (pre-revision) had no override
  for cases where the gate's heuristic was wrong. Result: agents
  either restructure work to pass the heuristic (mock compliance) or
  escalate to the user (friction).
- **Absolutism ("NEVER", "ALWAYS").** `enforce_named_agents.py` says
  "There is NEVER a reason to dispatch an anonymous agent." The audit
  found two legitimate cases (one-line lookup, user-requested probe)
  the absolutism couldn't accommodate. Soften to "almost never, and
  here is the escape."

## Rule 2: Every gate must produce persistent signal

A gate whose decisions live only in the conversation context produces
no learning data. The operating rule from the principle file ("every
gate produces signal") requires that gate decisions — denials, asks,
allow-with-warnings, and especially waivers — write to a durable store
that survives the session.

Minimum acceptable persistence shapes:

- **Beads issue** — for gate findings that are actionable (the agent
  should fix something later). Example: a drift-doctor audit files one
  remediation bead per audit run.
- **Append-only log file** — for high-frequency gate decisions where
  per-event beads would be noisy. Example: `.beads/.gate-decisions.jsonl`
  with `{gate, timestamp, decision, reason, command_excerpt}`.
- **`bd audit record`** — for events that fit the audit subsystem.
- **Waivers file** — `.beads/.gate-waivers.jsonl` for waiver reasons,
  keyed by gate and decision. Becomes the labeled corpus for revising
  the gate's heuristic.

A gate whose only output is a conversation-level `systemMessage`,
`ask` reason, or `deny` reason produces no learning data and cannot
be evaluated for half-life review (Operating Rule 1 from the
principle file). You cannot prune what you cannot count.

### Audit finding (2026-05-26) and remediation (resolved)

The integrator panel's original cross-cutting finding (2026-05-26)
was that no gate in the repo persisted signal: none wrote to a log,
none called `bd audit record`. That finding has since been
remediated — `claude/hooks/_gate_signal.py` now provides a shared
`record()` helper that appends to `.beads/.gate-signal.jsonl`, and
the corpus has accumulated real decisions across many sessions.

**Current state (as of 2026-05-29):** 15 gates emit persistent
signal via `_gate_signal.record()`:

- `context_burn_detector.py`
- `discovery_input_gate.py`
- `discovery-close-gate.py`
- `discovery-gate.py`
- `enforce_named_agents.py`
- `implementation_echo_test_gate.py`
- `no_direct_send_guard.py`
- `oracle_downgrade_warning_gate.py`
- `outcome_assertion_gate.py`
- `review_gate.py`
- `serena_preference_gate.py`
- `spec_id_enforcement.py`
- `tdd-gate.py`
- `test_oracle_brief_gate.py`
- `validate_no_shirking.py`

**Still not emitting signal** — these hooks fire on every matching
event and are advisory nudges, status reporters, or redirect-only
guards where per-event signal would be pure noise; the design
question for each is whether it should escalate to signal-worthy
decisions, not whether it is currently in violation:

- `design_doc_location_guard.py`
- `discovery-nudge.py`
- `mol_status_check.py`
- `openspec_init_guard.py`
- `review_nudge.py`
- `serena_preference_injection.py`
- `session_cleanup.py`
- `session_status.py`
- `test_reminder.py`

The lesson the original finding now illustrates is the **petrified**
failure mode (see `delicate-art-of-bureaucracy.md`): a finding that
outlived the condition it described, left un-reconciled in the rule
text after the infrastructure shipped. Half-life review caught it.

## Rule 3: Validate the value, not just the presence

When a gate requires the user to supply a value — `--spec-id`,
oracle-brief file, waiver reason, design-doc path — the gate MUST
check that the value resolves to a real artifact OR meets a substance
threshold. A gate that checks only presence produces mock bureaucracy
by construction: an agent under pressure learns the shortest passing
string (`--spec-id none`, `--waiver "tbd"`, an empty oracle brief
file).

### What "value validation" means

For paths to files:
- The path must resolve to an existing file
- The file must be readable
- If the spec-id format includes an anchor (`path#anchor`), the
  anchor must match a real heading in the file

For free-text reasons:
- Reject placeholder strings: `none`, `tbd`, `todo`, `wip`, `n/a`,
  `fixme`, `?`, `??`, `???`, etc.
- Enforce a minimum substance threshold — e.g., ≥20 characters for a
  waiver reason
- Reject reasons that echo the source artifact (bead title verbatim,
  hook name, etc.)

For "exists" assertions:
- Existence of a file is not the same as the file being non-empty
- Existence of required sections is not the same as the section
  containing meaningful content (gates cannot judge meaning, but the
  human reviewer should see the waiver-reason log)

### Reference (audit-fix 2026-05-26)

`spec_id_enforcement.py` (commit `f85164c`) implements value
validation: rejects placeholders, requires path resolution, requires
anchor match against `### Requirement: ...` headings in the resolved
file. Deny messages include the specific failure category and (for
anchor mismatches) the available headings — Internal Transparency
applied to the failure path.

### Wiesche et al. (2013) named this failure

The bureaucracy principle file cites Wiesche, Schermann & Krcmar
(2013) on *mock bureaucracy*: "rules promulgated for symbolic value
but ignored in practice." A presence-only gate is the architectural
shape that produces this failure mode. The principle file warned
about it by name; this rule operationalizes the warning into a
mechanical check.

## When this rule applies

When you are about to:

- Add a new hook, gate, or rule that denies, asks, or warns
- Modify the denial-message language or escape-path logic of an
  existing gate
- Audit an existing gate against the bureaucracy principle
- Design a waiver / exemption / override mechanism

…walk these three rules. Each new gate's design.md (or commit
message, if there is no design doc) should explicitly name:

- The escape path and how the agent invokes it (Rule 1)
- Where the gate's signal persists (Rule 2)
- What the gate validates beyond presence (Rule 3, if it requires a
  value)

If any of the three answers is "TBD" or "none", the gate is not ready
to ship.

---

## For deeper context

### Relation to the bureaucracy principle

This rule is the implementation guide for
`delicate-art-of-bureaucracy.md`. The principle file's four design
features (repair, internal transparency, global transparency,
flexibility) are *what* a good gate has. The three rules here are
*how* to build a gate that has them:

- Rule 1 (first-class escape) is how Flexibility actually manifests
- Rule 2 (persistent signal) is how the *learning* trait actually
  happens — a bureaucracy that doesn't accumulate signal cannot learn
- Rule 3 (validate value) is how to avoid mock bureaucracy as a
  failure mode

### Audit-validated patterns

The reference designs and anti-patterns in this rule are not
theoretical. They come from the 14-gate audit performed 2026-05-26
against the bureaucracy principle, with three independent reviewers
(adversary, friction-analyst, integrator) reaching convergent
verdicts. Five gates passed all four bureaucracy features and are
named here as reference designs. Two gates were found in active
mock-bureaucracy mode and have been or will be revised.

### Lineage

Rule 1 derives from Adler & Borys (1996) on *enabling formalization*
— procedures that provide users with discretion within multiple
documented paths. Rule 2 derives from the broader learning-organization
literature (Adler 1992 on NUMMI's suggestion system as a designed
learning loop; Kelman 2019 on bureaucracies as learning organizations).
Rule 3 derives from Wiesche et al. (2013) on *mock bureaucracy* as a
failure mode that even enabling-by-design can produce when
implementation conditions are wrong.

## Bureaucracy principle — deeper context (relocated from `delicate-art-of-bureaucracy.md`)

The always-on `claude/rules/delicate-art-of-bureaucracy.md` rule carries the
operative core (the four design features, the four failure modes, the operating
rules) and points here for the *why*. That non-operative deep-context tail was
relocated into this skill to keep the always-on rule lean; it is preserved in
full below.

### The operative thesis (Schwartz, 2020)

Schwartz names the operative frame directly: *"We bureaucratize as a way to
turn our problem-solving successes into problem-solved routines."* The
routines are how we don't re-solve the same problem twice. Whether they
remain useful depends on whether they stay enabling or drift coercive.

### Bureaucracy lineage (full)

The framework is not Schwartz's invention. He popularized it for a
practitioner audience; the operative content traces back through Adler:

- **Gouldner (1954)** — first denounced the "metaphysical pathos" around
  the term *bureaucracy* and argued that bureaucracy could deliver
  efficiency without enslavement. The original challenge.
- **Adler & Borys (1996)** — answered Gouldner's challenge by
  distinguishing enabling from coercive formalization along the four
  dimensions (repair, internal transparency, global transparency,
  flexibility) and showing empirically that the difference matters.
  *The* operative source.
- **Adler (1992) / Shook (2010)** — empirical anchor in the NUMMI plant:
  standardized work as the *foundation* of learning, not the enemy of it.
- **Schwartz (2020)** — popularized the framework for IT practitioners and
  added the three "ways" (Monkey, Razor, Sumo Wrestler) and 25+ named
  plays as a practitioner playbook.
- **Wiesche, Schermann & Krcmar (2013)** — named "mock bureaucracy" and
  showed that enabling design is not a guaranteed cure.

### What this lineage doesn't cover

Two practitioner traditions are absent from Schwartz's bibliography but
belong in this lineage:

- **The management-thinker tradition** — Grove (*High Output Management*,
  1983), Lencioni (*Five Dysfunctions of a Team*, 2002), Kim Scott
  (*Radical Candor*, 2017), Brown (*Daring to Lead*, 2018). These give
  operative vocabulary for *how* enabling rules work in practice: leverage
  ratios, trust before accountability, care-personally-challenge-directly
  feedback, clear-is-kind specificity.
- **The individual-lean tradition** — Allen (*Getting Things Done*, 2001),
  Benson & Barry (*Personal Kanban*, 2011), Newport (*Deep Work*, 2016),
  Torres (*Continuous Discovery Habits*, 2021). These give the
  scale-of-one lean techniques Schwartz's executive-audience bibliography
  skips. WIP limits for one, capture-clarify-organize, attention-cost
  analysis of interruption — directly applicable to a personal
  workflow-tooling repo.

### Citations

- Adler, P. S., & Borys, B. (1996). Two Types of Bureaucracy: Enabling and
  Coercive. *Administrative Science Quarterly*, 41(1), 61–89.
- Adler, P. S. (1992). The "Learning Bureaucracy": New United Motor
  Manufacturing, Inc. In *Research in Organizational Behavior*, Vol. 15.
- Gouldner, A. W. (1954). *Patterns of Industrial Bureaucracy*. The Free
  Press.
- Schwartz, M. (2020). *The (Delicate) Art of Bureaucracy: Digital
  Transformation with the Monkey, the Razor, and the Sumo Wrestler.* IT
  Revolution Press.
- Shook, J. (2010). How to Change a Culture: Lessons from NUMMI. *MIT
  Sloan Management Review*, 51(2), 63–68.
- Wiesche, M., Schermann, M., & Krcmar, H. (2013). When IT Risk
  Management Produces More Harm than Good: The Phenomenon of "Mock
  Bureaucracy." *46th Hawaii International Conference on System
  Sciences*.
