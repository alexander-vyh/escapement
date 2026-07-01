## Problem Statement

Agents have no per-repo way to express *how far to take work* — local commit only,
push + open PR, or push + merge. The recently beads-injected "Conservative (default)"
managed block tells agents not to commit/push unless explicitly asked, which directly
contradicts the existing drive-through harness (`~/CLAUDE.md` mandates push and "never
stop before pushing"; `validate_no_shirking` blocks early stops). The result is
contradictory instructions and stranded work. After this change, a repo declares one
ceiling and every agent session in it knows — and the escapement gates *enforce* —
exactly where "done" is.

## Non-Goals

1. **A global / uniform ceiling.** The entire point is per-repo variation; a global
   knob recreates the one-size-fits-all friction that caused this. Locks in: the
   ceiling lives with the repo, not the user or the machine.
2. **Patching or fighting beads.** We do not edit beads' managed-block template. We
   override it with a value the gates read — beads' own block states explicit
   instruction wins. Locks in: a beads upgrade can regenerate its block without
   touching ceiling behavior.
3. **Auto-detecting a repo's ceiling** from its history or branch protection. The
   ceiling is declared, with a safe default. Locks in: an unconfigured repo is `pr`,
   never silently `merge`.

## Capabilities

### New Capabilities

- `git-completion-ceiling` — per-repo config file, a resolver, and PreToolUse cap
  enforcement with a waiver escape.

### Modified Capabilities

- None in the skeleton. The Stop-side floor-alignment (teaching `validate_no_shirking`
  and the harness stop gate to read the ceiling) is a future increment; in the
  skeleton the floor mandate is prose, which is compliance-soft and does not hard-block.

## Impact

- **escapement** (source of truth for the harness): a new resolver module and a new
  PreToolUse hook (or an addition to the existing `validate_no_shirking.py`, which
  already fires PreToolUse on `git commit` / `gh pr create` / `git push`), wired in
  `claude/settings.template.json` and deployed via `INSTALL.sh` symlinks.
- **Each governed repo**: a new `.claude/repo-policy.json` (one field today:
  `git_completion_ceiling`).
- **No change to beads.** No change to jixia-advisors product code (this design lives
  here only because discovery was run here; build happens in escapement).

## Riskiest Assumption

We believe the escapement gates can resolve **repo-root → ceiling at hook time** and
enforce it as a **hard cap** (block `git push` in a `local` repo; block merge in a
`pr` repo) **while the agent can still legitimately stop at the ceiling** (commit in a
`local` repo) without `validate_no_shirking` or the harness false-blocking. We will
know this is true when, in a `local` fixture repo, an agent's `git push` is denied AND
a stop after a plain commit is permitted — both in one live session. If false (the
hook can't cleanly read the value, or the cap deadlocks against the "never stop before
pushing" mandate), we will fall back to **CLAUDE.md-prose-only** ceilings: a
`Git ceiling: local|pr|merge` line per repo, agent-compliance only, no hook — buildable
immediately but unenforced.

**Liveness:** if this assumption is false and undiscovered for ~2 weeks, we will have
shipped a config the gates do not actually enforce (prose-in-disguise) or introduced a
deadlock that strands work — significant rework. So the skeleton tests it first.

## Walking Skeleton

A PreToolUse gate reads a per-repo ceiling file and **hard-blocks `git push` in a repo
set to `local`**, while a stop after a plain commit in that repo is not punished —
proving the cap and the floor cohere for one tier.

1. **Config + resolver** — define `.claude/repo-policy.json`
   (`{"git_completion_ceiling": "local|pr|merge"}`) and `resolve_ceiling(cwd)` that
   walks up to the git root, reads the file, and returns the tier (default `pr` when
   the file or field is absent).
2. **PreToolUse hard cap** — on the `git push` path, call `resolve_ceiling`; if
   `local`, deny with a message naming the ceiling and the `--ceiling-waiver "<reason>"`
   escape, and emit a `_gate_signal.record(gate="git-completion-ceiling", ...)`. Allow
   push for `pr`/`merge`/unconfigured. Wire into `claude/settings.template.json`.
3. **Behavioral test** — a `local` fixture repo: assert `git push` is denied (cap) and
   that a transcript ending after a commit (no push, no shirking language) is allowed
   to Stop (floor coherence). A `pr` / unconfigured fixture: assert `git push` is
   allowed. Includes a negative control (unconfigured repo must NOT block push) and a
   positive control (a `merge` repo allows push).

## Proof of Delivery

This is done when, in a real repo set to `git_completion_ceiling: local`, a live agent
session attempting `git push` is denied with an actionable message + waiver path, and
the same session can stop after committing without a shirking-block — observed in a
live session, not just unit-green.

## Anti-Metrics

1. The gate blocks the **user's own** manual pushes. It must govern agent tool-calls
   only — the user can always `!git push`. If a human push is ever blocked, the design
   is wrong even if every test passes.
2. A repo gains a `.claude/repo-policy.json` the gates never actually read
   (prose-in-disguise) — i.e., enforcement is faked by documentation.
3. An **unconfigured** repo blocks `git push`. The default must be permissive (`pr`);
   if absence-of-config denies a push, the rollout is unsafe.

## Decisions

- **Hard cap, not advisory** (user decision, 2026-06-21): "If a repo is set as no push
  allowed, then push should be blocked." A hard PreToolUse denial — paired with a
  mandatory `--ceiling-waiver "<reason>"` escape per the gate-design rule (a hard deny
  without a named, agent-invokable way forward is coercive).
- **Tiers are boundaries** (`local` = no-push, `pr` = no-merge, `merge` = unrestricted).
  The tier names the highest allowed action; the cap blocks anything above it.
- **Ceiling is one value serving as both floor and cap** (user: "the driving from
  escapement should always align with the repo limits"). Escapement drives work *up to*
  the ceiling; the cap blocks *past* it. The harness's completion target is redefined
  per repo by the ceiling — not a separate setting beside it.
- **Config location `.claude/repo-policy.json`** (not a single-purpose `ceiling.json`)
  so future per-repo settings have an idiomatic home, git-versioned and machine-readable
  — chosen over CLAUDE.md prose (gates can't reliably parse prose) and over a
  `contract.json` field (that is per-session; the ceiling is per-repo).
- **Reuse `validate_no_shirking.py`'s PreToolUse surface** if clean — it already
  intercepts `git push` / `gh pr create`; otherwise a sibling hook. Decided at build
  time against the actual code.

## Risks & Trade-offs

- **Cap-without-alignment deadlock** → the "never stop before pushing" mandate is prose
  (compliance-soft), not a hard Stop gate, so blocking push in `local` does not
  hard-deadlock; the skeleton still asserts stop-at-commit is permitted to prove
  coherence. The hard floor-alignment is a tracked future increment.
- **Collision-detection ordering** (concurrent sessions sharing one checkout) → the
  ceiling check must run *after* the existing collision steer, so a collided session is
  still routed to `bd worktree create` regardless of ceiling. Accepted; covered by an
  ordering test in the floor increment.
- **`merge` detection at PreToolUse is fuzzy** (`git merge` vs `gh pr merge` vs
  push-to-main) → the `pr`-tier merge-cap is deferred; the skeleton enforces only the
  `local` push-cap, where the boundary is a single unambiguous command.
- **Waiver abuse** (agent waives every block) → the waiver requires a substantive
  reason and emits a gate signal for half-life review; value-not-presence validation
  rejects placeholder reasons. Accepted with monitoring.

## Future Increments

`[PLACEHOLDER]` — purchased by validating the skeleton:

- **Stop-side floor-alignment** — teach `validate_no_shirking` + the harness stop gate
  to read the ceiling so stop-at-ceiling is a *sanctioned* outcome and the prose
  mandate is replaced by a ceiling-aware rule. *Done when a live `pr`-repo session stops
  at an open PR with no false shirking-block, and a `local`-repo session stops at a
  commit, both gate-sanctioned.*
- **`pr`-tier merge-cap** — block agent merge-to-main in a `pr` repo. *Done when an
  agent's `gh pr merge` / merge-to-main is denied in a `pr` repo.*
- **Per-repo setup prompt** — the "asks per repo" UX at init. *Done when setup writes
  `repo-policy.json` without hand-editing — built only if hand-authoring proves annoying
  (behavior precedes belief).*
