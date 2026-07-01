# Problem Framing — git-completion-ceiling

Confirmed by user 2026-06-21.

## Problem

Agents have no per-repo way to express *how far to take work* (local commit only /
push + open PR / push + merge to branch). The recently beads-injected "Conservative
(default)" managed block tells agents not to commit/push unless explicitly asked, which
directly contradicts the user's months-old drive-through harness (`~/CLAUDE.md` mandates
push and "never stop before pushing"; `validate_no_shirking` blocks early stops). Net:
contradictory instructions, stranded work, friction.

## Why Now

The Conservative inversion is live and disrupting sessions (landed in jixia-advisors
2026-06-11 via `bd init` / beads 1.0.5; older repos still carry the prior "push is
MANDATORY" block). It actively fights the existing harness today — not hypothetical.

## Decision Authority

User (Alexander), sole owner of escapement. Effectively `none — solo personal tooling`.

## Behavioral Population

The escapement Stop / PreToolUse gates (must read the ceiling and act on it) and the
agent sessions they govern (whose finishing behavior changes). The user sets the
per-repo value.

## Riskiest Assumption

Betting the gates can read a per-repo ceiling at hook time and enforce it as a hard cap
two-sided (block `git push` in a `local` repo; block merge in a `pr` repo) while the
agent can still legitimately stop at the ceiling (commit in a `local` repo) without
`validate_no_shirking` or the harness false-blocking — and without breaking the
collision-detection ordering. Wrong when the hook can't cleanly resolve repo-root →
ceiling, or the cap deadlocks against the "never stop before pushing" mandate. Would
know within the first skeleton. If false and undiscovered ~2 weeks → significant rework
(shipped config nobody enforces, or a deadlock that strands work).

## Success Criteria

Observable: (a) in a `git_completion_ceiling: local` repo, an agent's `git push` is
blocked by the gate with an actionable message + waiver escape; (b) in a `pr` repo, an
agent commits → pushes → opens PR and a stop there is permitted (no shirking-block), but
merge is not auto-done; (c) an unconfigured repo defaults to `pr` and push is allowed;
(d) the beads "Conservative" contradiction no longer strands work because the ceiling
now defines "done."
