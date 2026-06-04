# Gate Design — Resident Checklist

The full manual (reference designs, anti-patterns, audit findings, validation
mechanics, waiver convention, lineage) lives in the on-demand **`gate-design`
skill**. This stub is the always-on checklist. A `PreToolUse` nudge
(`gate_design_nudge.py`) also reminds you to load the skill when you edit a
gate-ish file.

When adding or modifying any gate, hook, denial/permission message, or
waiver/exemption — or deciding to keep/revise/retire a rule — **load the
`gate-design` skill** and satisfy all three rules:

1. **Escape path IN the denial.** Every deny must name an agent-invokable way
   forward — a redirect to the correct tool, or `--<gate-name>-waiver
   "<reason>"` — written into the denial text itself. Never "ask the user" or
   "disable the gate". (Adler & Borys: enabling, not coercive.)

2. **Persistent signal.** Emit the decision via `_gate_signal.record(...)` so
   denials and waivers accumulate as a labeled corpus for half-life review —
   not just a one-off conversation message.

3. **Validate value, not presence.** If the gate requires a value (spec-id,
   waiver reason, path), check it RESOLVES to a real artifact or clears a
   substance bar — reject placeholders (`tbd`, `n/a`, `<20 chars`, reasons that
   echo the source artifact). A presence-only check produces mock bureaucracy
   by construction.

If any of the three is "TBD/none" for a gate you are shipping, it is not ready.
Load the skill for the how — reference designs, the standard waiver convention,
and the anti-patterns the repo's gate audit surfaced.
