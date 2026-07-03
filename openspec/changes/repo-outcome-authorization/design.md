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

### Init-time elicitation (how the declaration gets written) — user-directed

The declaration is a **standard per-project option, elicited on by default** at repo
onboarding — not hand-written. `project-bootstrap.sh`
already surfaces onboarding NOTEs the agent acts on (it bootstraps beads/serena and
reports what it did). It gains one more check: if the repo has no `.escapement/repo.json`,
it surfaces a NOTE — "No outcome policy set for this repo." The agent, seeing that at
session start, **asks the user once**: how far should agents drive here (`committed` /
`pr-opened` / `merged` / `merged-and-deployed`), auto-merge on green or not, and (per-repo)
whether any danger class still needs a confirm. It writes `.escapement/repo.json` from the
answer.

Adoption safeguards, so this never becomes a nag:
- The prompt fires **once per repo** — a written declaration (any level) silences it.
- **Declining is a first-class answer:** it writes an explicit conservative declaration
  (`intended_outcome: pr-opened`, `auto_merge_on_green: false`), so "keep asking me / I'll
  review" is a recorded choice, not a perpetual prompt.
- Only fires in escapement-onboarded repos (same guard as the existing bootstrap steps),
  never in arbitrary directories.

This makes `confirm_class` a **per-repo elicited value**, not a global build-time decision —
the floor-vs-carveout choice is the user's, asked at init, per repo.

### Resolution semantics (the reader — `repo_outcome.py`)

- **Absent declaration ⇒ conservative default:** `intended_outcome: pr-opened`,
  `auto_merge_on_green: false`. Never assume authorization the repo did not grant.
  This is the fail-safe: an unconfigured repo behaves exactly as today.
- Malformed / unparseable ⇒ same conservative default, plus a surfaced warning (never
  silently treat a broken file as authorization).

### Enforcement — two layers, belt and suspenders

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

- **Stop-gate enforcement.** Done when a session that tries to end with an open green
  PR in an `auto_merge_on_green` repo is blocked by the harness — not when the rule
  text merely says so.
- **`confirm_class` carve-out.** Done when a change matching a declared danger class
  (e.g. `db-migration`) still draws one confirm under `auto_merge_on_green` — not when
  the field merely exists. Gated on the Open Question below.
- **`bd`/CLI authoring helper** (`set-repo-outcome`), so the declaration is written by
  a command with validation, not hand-edited JSON. Done when the command writes a
  schema-valid file and refuses invalid outcome levels.

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
