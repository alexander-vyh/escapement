# Design — repo-outcome-authorization

Status: `[PENDING SKELETON]`

## Problem Statement

A coding agent that finishes a change and opens a green PR stops there and asks
"want me to merge it now, or would you rather review the PR first?" — instead of
merging and shipping it live. The observable change this delivers: in a repo that
has declared its intended outcome, an agent that reaches green verification **merges
and ships without asking**, and can no longer end the session leaving a green PR
un-merged.

The root cause is an authorization gap, not a missing rule. The ship-live rule
already says "PR opened" is not done. But the **base Claude Code system prompt**
instructs the agent to *confirm before hard-to-reverse or outward-facing actions —
unless durably authorized.* Merging to a repo that auto-deploys to production is
textbook hard-to-reverse-and-outward-facing, and **no durable authorization artifact
exists**, so the agent obeys the base prompt's caution and asks. The fix is to
supply the artifact the base prompt already defers to.

## Strategic Alternatives

- **Do nothing / rely on the existing ship-live rule prose.** Rejected: the rule
  already exists and agents *still* ask (cro-executive-dashboard PR #242). Global
  rule prose loses to the base-prompt confirm-first caution because nothing
  repo-local grants the durable authorization the base prompt names.
- **Blanket global "always merge on green, never ask" rule (no per-repo file).**
  Rejected: too blunt. Some repos should not auto-deploy (not owned by the user; or
  a repo where the user genuinely wants to review first). A single global switch
  removes the ability to differentiate, and an un-scoped blanket claim keeps losing
  to the base-prompt caution. The per-repo file is the artifact the base prompt
  actually treats as authorization.
- **A hook that auto-merges PRs itself (agent-less automation).** Rejected: moves the
  merge decision out of the agent's outcome-ownership loop into opaque automation,
  and the agent still needs to *know* it is cleared to drive there. Declaration +
  agent-merges keeps ownership with the agent and is debuggable.

## Riskiest Assumption

I am betting that **a committed per-repo file will actually change agent merge
behavior and override the base-prompt confirm-first caution.** I will know I'm wrong
when an agent in a repo declaring `merged-and-deployed` + `auto_merge_on_green` still
asks "merge or review first?" on a green PR.

**Liveness:** if this is false, the entire feature is theater — the user keeps getting
asked and nothing improved. That is significant rework (the enforcement layer must
move from advisory rule text to a hard gate). This passes the liveness test.

**Embedded alternative (rejected build approach):** put the authorization in the
per-session contract (`init_contract.py --goal`) instead of a per-repo file — each
session declares its own outcome level. Rejected: authorization that must be
re-declared every session is not durable; the point is that the repo carries it once,
committed, so every future session and agent inherits it without the user restating.
Per-session re-declaration *is* the friction we are removing.

## Design

A committed, repo-root declaration read by both the agent (via rule) and the harness
(via a Stop-gate check).

### The declaration — `.escapement/repo.json`

`.escapement/repo.json` is the **per-project options manifest** — a single committed file
holding escapement's on-by-default per-project options. Outcome-authorization is the first
section; worktree-bootstrap-on-checkout (tracked separately, `escapement-195`) will be a
sibling section. Each option is elicited on by default at onboarding and defaults
conservatively when absent.


```json
{
  "intended_outcome": "merged-and-deployed",
  "auto_merge_on_green": true,
  "deploy": { "on": "push-to-main", "surface": "Cloud Run exec dashboard" },
  "confirm_class": []
}
```

- `intended_outcome`: ordered ladder — `committed` < `pr-opened` < `merged` <
  `merged-and-deployed`. Declares how far "done" reaches in this repo.
- `auto_merge_on_green`: when true, green verification ⇒ the agent merges without
  soliciting review. When false (or absent), the agent stops at `pr-opened` and may
  ask — the current behavior, now explicit and opt-in.
- `deploy`: optional, informational — lets the agent name the live surface in its
  report ("now live at X") rather than ask about it.
- `confirm_class`: optional narrow list of change kinds that STILL get one confirm
  even under `auto_merge_on_green` (see Open Questions — this is the user's call).

### Init-time elicitation (how the declaration gets written) — auto-written, then user-directed

**Amended 2026-07-04** (escapement-odfo): the original design had `project-bootstrap.sh`
surface a NOTE and rely on the agent to interactively elicit + write the declaration.
In practice this depended on the agent noticing the NOTE and following through *every*
session in every unconfigured repo — a real incident (cro-executive-dashboard PR #262)
showed a repo staying silently unconfigured indefinitely, and the agent fabricating a
"platform-level gate" rather than naming the missing declaration. `bootstrap_outcome`
now **writes the conservative default immediately** (`intended_outcome: pr-opened`,
`auto_merge_on_green: false`) the first time it sees no `.escapement/repo.json`, then
surfaces a NOTE offering to upgrade it — the elicitation-then-write flow becomes
upgrade-an-existing-file rather than create-from-nothing. `harness/bin/set_repo_outcome.py`
is the validated helper for that upgrade (or for hand-authoring a non-default
declaration directly): it rejects an invalid `intended_outcome` and refuses
`auto_merge_on_green: true` paired with an outcome below `merged`.

Adoption safeguards, so this never becomes a nag:
- The write fires **once per repo** — any existing declaration (including the
  auto-written default) silences it permanently.
- **The conservative default IS the "keep asking me" answer**, recorded as a real file
  instead of an implicit, invisible absence.
- Only fires in escapement-onboarded repos (same guard as the existing bootstrap steps),
  never in arbitrary directories.

This makes `confirm_class` a **per-repo elicited value**, not a global build-time decision —
the floor-vs-carveout choice is the user's, set (or left default) per repo.

### Resolution semantics (the reader — `repo_outcome.py`)

- **Absent declaration ⇒ conservative default:** `intended_outcome: pr-opened`,
  `auto_merge_on_green: false`. Never assume authorization the repo did not grant.
  This is the fail-safe: an unconfigured repo behaves exactly as today.
- Malformed / unparseable ⇒ same conservative default, plus a surfaced warning (never
  silently treat a broken file as authorization).

### Enforcement — three layers

1. **Rule text (proactive).** `continuation-harness.md` gains: the repo's declaration
   IS the durable authorization the base prompt defers to; an agent that reaches green
   in an `auto_merge_on_green` repo **must merge and must not solicit review.**
   Simultaneously, the "irreversible external action" carve-out is tightened so a
   *merge that triggers auto-deploy does not qualify* — the agent can merge, so it
   must. `outcome-ownership.md` adds "want me to merge, or review first?" to the named
   anti-pattern list.
2. **Stop-gate check (backstop).** A deterministic check (parity with the existing
   `git_work_remains`): if the session produced a green PR in an `auto_merge_on_green`
   repo and it is still open, **Stop is blocked** with a resumption prompt naming the
   PR to merge. Authorization is gated on *green* — a red/unverified PR never triggers
   this (that would authorize shipping broken code, an anti-metric below).
3. **PreToolUse merge gate (amendment, escapement-odfo, 2026-07-04).** Layers 1 and 2
   both operate *around* the merge decision — proactive rule text before it, a Stop-time
   backstop after it — neither intercepts a `gh pr merge` invocation itself. The
   incident that motivated this layer (PR #262) was not a red-PR or Stop-time failure;
   it was an agent reasoning about authorization in free text and fabricating an
   external constraint rather than attempting the merge and reporting the true reason
   it was (or wasn't) blocked. `merge_authorization_gate.py`, a `PreToolUse` hook on
   `Bash(gh pr merge:*)`, resolves `.escapement/repo.json` via the same `repo_outcome.py`
   and either allows silently (authorized) or denies with the real, non-fabricatable
   reason (unauthorized) — moving the decision from agent judgment to a deterministic
   check at the point of action. Escape path: `# merge-authorization-waiver: <reason>`
   appended to the command once the user has given explicit go-ahead in the
   conversation. This does not replace layer 1's behavioral instruction to *attempt*
   the merge rather than pre-judge it in chat — the gate only produces a truthful
   verdict once that attempt happens.

## Anti-Metrics

Even if this works perfectly, it has failed if:

1. **It authorizes merging RED PRs.** Authorization must be gated on green verification
   (the contract oracle passing), never blanket. Shipping unverified code live is worse
   than asking.
2. **It auto-merges in repos the user did not configure or does not own.** Absent
   declaration must mean "ask / stop at PR" — the conservative default. A default that
   assumed merge would ship changes live in other people's repos.
3. **The user loses the ability to say "hold, let me review" on a specific repo.** The
   `intended_outcome` ladder and `auto_merge_on_green: false` must remain first-class,
   so a repo can opt *out* of auto-merge deliberately.

## Walking Skeleton

`[PENDING SKELETON]`

**What it is:** `.escapement/repo.json` schema + `repo_outcome.py` reader (conservative
default when absent) + the durable-authorization rule text — then observe an agent at
the merge decision in a configured test repo.

**What it tests:** the riskiest assumption — does the committed file actually make an
agent merge a green PR without asking?

**What done looks like:** in a scratch repo declaring `merged-and-deployed` +
`auto_merge_on_green: true`, an agent (or a scripted replay of the decision point)
reaching a green PR **merges it and emits no "review first?" solicitation**; in a
scratch repo with no declaration, the same agent stops at `pr-opened`. Observable via
transcript, not "tests pass."

**Tasks (≤3):**
1. `.escapement/repo.json` schema + `repo_outcome.py` reader with conservative default
   + unit tests (absent ⇒ pr-opened/false; malformed ⇒ default+warn; valid ⇒ parsed).
2. Rule edits: durable-authorization statement in `continuation-harness.md`, tighten
   the irreversible-action carve-out, add the anti-pattern entry in
   `outcome-ownership.md`.
3. Behavioral test: replay an agent at the merge decision point against a configured
   vs. unconfigured repo; assert merge-without-asking vs. stop-at-PR.

**Cutting test:** the Stop-gate enforcement and `confirm_class` are removed from the
skeleton — the skeleton only needs to prove the declaration changes behavior. Both are
future increments below.

## Proof of Delivery

Worth continuing when, after building the skeleton, a real agent session in a
configured repo ships a green PR live without asking — verified in the transcript —
and the same agent still asks (or stops at PR) in an unconfigured repo.

## Future Increments

`[PLACEHOLDER]`

- **Stop-gate enforcement.** ✅ BUILT (deterministic backstop). `stop_hook.py`
  `_unmerged_automerge_pr` + `_verification_work_remains` block a `verification_passed`
  stop when the repo authorizes auto-merge and an open PR exists for the current branch
  (reason `verification_passed_unmerged_automerge_pr`). Gated on green (only reached on
  the verification-passed path, anti-metric #1) and on authorization (anti-metric #2).
  This makes the feature enforced, not compliance-based — it fires regardless of whether
  the agent read the rule.
- **`confirm_class` carve-out.** Done when a change matching a declared danger class
  (e.g. `db-migration`) still draws one confirm under `auto_merge_on_green` — not when
  the field merely exists. Gated on the Open Question below. Still open.
- **`bd`/CLI authoring helper** (`set-repo-outcome`). ✅ BUILT (escapement-odfo,
  2026-07-04) as `harness/bin/set_repo_outcome.py` — writes a schema-valid
  `.escapement/repo.json`, refuses an invalid `intended_outcome`, and refuses
  `auto_merge_on_green: true` paired with an outcome below `merged`.
- **PreToolUse merge gate.** ✅ BUILT (escapement-odfo, 2026-07-04) as
  `merge_authorization_gate.py` — see Enforcement layer 3 above. Not anticipated in
  the original design; added after a real incident showed layers 1–2 don't cover an
  agent that free-narrates a fabricated reason instead of attempting the merge.
- **Auto-write the conservative default on absence.** ✅ BUILT (escapement-odfo,
  2026-07-04) — `scripts/project-bootstrap.sh`'s `bootstrap_outcome` now writes
  `.escapement/repo.json` immediately instead of only asking the agent to elicit one
  interactively. See "Init-time elicitation" above.

## Open Questions

- **[RESOLVED] `confirm_class` — absolute floor (A) vs. narrow carve-out (B)?**
  Resolved by the user: **neither is a global build-time decision — it is elicited
  per-repo at onboarding.** The init-time prompt asks the user, per repo, whether the
  floor is absolute or a danger class still gets one confirm; the answer is written into
  that repo's `.escapement/repo.json`. The skeleton captures the choice at elicitation;
  enforcing the carve-out (danger-class *detection*) is the `confirm_class` increment.
- **[DEFERRABLE] Scope of `auto_merge_on_green` gating** — is "green" the session
  contract's `verify` exit-0, or must it also include the repo's own CI status? For the
  skeleton, contract-green is sufficient; CI-status coupling is an increment.
