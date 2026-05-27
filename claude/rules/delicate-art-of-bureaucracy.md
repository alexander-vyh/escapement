# The Delicate Art of Bureaucracy — Global Rule

This repo is a bureaucracy. The hooks, skills, gates, rules, and harnesses
in `claude-workflow-setup/` are a structured set of routines that turn
problem-solving successes into reusable practice. That is not pejorative —
it is the operative frame.

Bureaucracies decay in predictable directions unless designed to stay
**lean, learning, and enabling**. The four design features below distinguish
enabling from coercive bureaucracy (Adler & Borys, 1996). Walk them before
adding or modifying any gate.

For the implementation patterns that make a gate satisfy these features —
escape paths, persistent signal, value-not-presence validation — see
`claude/rules/gate-design.md`.

## When this rule applies

When you are about to:

- Add a new hook, gate, rule, or skill to this repo
- Modify the denial-message language of an existing gate
- Decide whether to keep, revise, or retire an existing rule
- Design a waiver / exemption / override path
- Triage a complaint that a gate is producing friction

…walk the four design features explicitly. Name the failure mode you are
preventing. State the signal the gate will produce. Make the rationale
visible in the artifact itself.

When this rule conflicts with another rule, the resolution belongs in the
discussion, not in silent suppression of one or the other. Surface the
tension, name which design feature is being traded for which, and decide
deliberately.

## The four design features (Adler & Borys, 1996)

Every gate, hook, rule, skill, and harness in this repo must be evaluated
against these four properties. They are not slogans; they are testable.

### 1. Repair
Can the practitioner repair the process themselves when it breaks, or does
every deviation force escalation? Enabling: the breakdown becomes signal —
the user sees what went wrong, can fix it locally, and the system learns
from the fix. Coercive: deviations are suspect; the only response is to
call a specialist or wait for approval.

**Test for a new gate:** when this gate fires incorrectly, can the user
unblock themselves with information surfaced in the denial, or do they have
to escalate, paper over, or disable the gate?

### 2. Internal transparency
Does the rule expose its rationale to the user, or is it a flat assertion
of duty? Enabling: the rule explains *why*, surfaces metrics so the user
can self-assess, and the procedure becomes a working tool rather than a
hurdle to circumvent. Coercive: rules are issued for compliance; the
rationale is "the engineer's province" and not the user's business.

**Test for a new gate:** does the denial message include the rationale and
the specific path to compliance? Or just the prohibition?

### 3. Global transparency
Does the practitioner see where this rule fits into the wider system, or
only their slice of it? Enabling: the user understands the broader
workflow the gate is protecting and can reason about edge cases. Coercive:
panoptic — the system sees everything, the user sees only the cell they
are in ("that's not your job").

**Test for a new gate:** is the gate's role in the overall workflow
discoverable from `CLAUDE.md`, `claude/rules/`, or the rule's own header?
Can a new agent figure out *why this exists* without reverse-engineering?

### 4. Flexibility
Are deviations treated as risks to be minimized or as learning opportunities
to be captured? Enabling: multiple legitimate paths are documented with
guidance for choosing; reasoned exceptions are first-class. Coercive: any
deviation requires superior approval, which means in practice it requires
work-arounds.

**Test for a new gate:** is there a documented waiver path that requires a
*reason* (not a checkbox), and does the reason text feed back into
improving the rule, or is the only escape "disable the gate"?

## The four failure modes

Bureaucracies degrade in predictable directions. Each direction has a name.
Recognizing them early is the work.

- **Bloated** — heavy controls, lots of busywork, more rules than the risk
  warrants. Symptom: the user spends more time managing the workflow than
  doing the work.
- **Petrified** — rules that outlived the problem they were created to
  solve. Symptom: a rule has lived for a year without revision and nobody
  remembers why it exists.
- **Coercive** — gates whose purpose is to say "no" rather than enable the
  next step. Symptom: denial messages are punitive, not actionable.
- **Mock bureaucracy** — rules that are followed for symbolic value but
  ignored in practice. Symptom: agents satisfy the gate (fake `--spec-id`,
  throwaway waiver text) without performing the underlying work. Wiesche,
  Schermann & Krcmar (2013) found that *both* enabling AND coercive designs
  can produce mock bureaucracy if implementation conditions are wrong —
  enabling-by-design is not a guaranteed cure.
  [per published abstract; full paper not accessed]

## Operating rules

These follow from the four design features and the four failure modes.

1. **Every rule has a half-life.** Annual review minimum. A rule that
   hasn't been revised in a year is a candidate for re-justification, not
   for veneration. Adler & Borys's paper is itself thirty years old and
   still operative — that is a *property* of the framework, not a default
   assumption to extend to every gate.
2. **Every gate produces signal.** Waivers are not friction; they are
   labeled training data. Denials are not punishment; they are questions
   the system is asking. If a gate produces no usable signal, it is bloat.
3. **Design intent does not survive implementation.** A gate designed
   enablingly will be experienced coercively if deployed without context,
   without trust, or without the practitioner's input on its rationale
   (Adler & Borys, 1996, p. 78: *"a procedure designed with an enabling
   intent and embodying enabling features can be implemented coercively"*).
   How the gate is rolled out matters as much as how it is designed.
4. **Behavior precedes belief.** When a new gate ships, the user does not
   need to believe in it first. Run the gate, observe the friction, revise.
   Shook (2010): *"It's easier to act your way to a new way of thinking
   than to think your way to a new way of acting."*
5. **Coercion is a smell, not a strategy.** A gate that exists primarily
   to block — without a corresponding affordance to *unblock* — is on the
   coercive axis. Add the affordance or remove the gate.

---

## For deeper context

The remainder of this rule is for readers who want to understand *why* the
framework above is shaped the way it is. Agents executing on a task do not
need to read further. The operational content above is self-sufficient.

### The operative thesis (Schwartz, 2020)

Schwartz names the operative frame directly: *"We bureaucratize as a way to
turn our problem-solving successes into problem-solved routines."* The
routines are how we don't re-solve the same problem twice. Whether they
remain useful depends on whether they stay enabling or drift coercive.

### Lineage

The framework here is not Schwartz's invention. He popularized it for a
practitioner audience; the operative content traces back through Adler:

- **Gouldner (1954)** — first denounced the "metaphysical pathos" around
  the term *bureaucracy* and argued that bureaucracy could deliver
  efficiency without enslavement. The original challenge.
- **Adler & Borys (1996)** — answered Gouldner's challenge by
  distinguishing enabling from coercive formalization along the four
  dimensions above (repair, internal transparency, global transparency,
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
belong in this rule's lineage:

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
