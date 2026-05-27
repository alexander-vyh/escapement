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

### Audit finding (2026-05-26)

The integrator panel's cross-cutting finding: every gate in the repo
currently violates this rule. No gate writes to beads, no gate
appends to a log, no gate calls `bd audit record`. The repo-wide
remediation is tracked separately.

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
