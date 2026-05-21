# Problem Framing — continuation-harness

Confirmed inputs to discovery. Source: 2026-05-18 design conversation with the user, after a session-miner analysis of 57 stall events across 14 days of transcripts and live observation of three regex Stop-hook false-positives during this very design session.

## Problem

Claude Code agents (single and multi-agent) stall mid-task in measurable, recurring patterns:

- Spin down after closing one bead despite ready siblings remaining in the same molecule
- Sit for hours waiting on subagents that never report back
- Narrate next actions ("now push", "now run the verification") and end the turn without taking them
- Announce future check-ins ("I'll check back in 5 min", "back at 19:32") without scheduling them
- Occasionally trigger false-positive blocks from the existing regex Stop hook (`validate_no_shirking.py`) on legitimate technical content — the hook is net-positive enforcement (catches real shirking the user wants caught) but its prose-pattern matching makes architectural discussion of error handling expensive in tokens. The new harness is *additive* coverage on stall classes the regex can't see, not a replacement

Measured baseline (14-day window): 57 short-prod events (`well?`, `now?`, `continue`); 19/30 recent main-thread sessions ended on plain text with no terminating tool call; 3 false-positive Stop hook firings on architectural descriptions within this design session alone.

## Why now

Existing markdown rules in `~/.claude/rules/` describe the right behavior (`outcome-ownership.md`, `agent-teams-default.md`) but get evicted from context by compaction in long sessions. The regex Stop hook intended to enforce them just demonstrated three false-positives in one design conversation — actively blocking the very design discussion of its own replacement. Multi-agent work (default per `agent-teams-default.md`) is currently bottlenecked on these failure modes, and the user wants to do more of it.

## Decision authority

`none — solo personal tooling owned by the user.`

## Behavioral population

`none — single-user harness; only the user's own Claude Code sessions consume it.`

## Riskiest assumption

Betting that a small set of deterministic mechanically-checkable gates — verification command exit code, registered wakeup, queue-drain across bead scope (molecule → epic → broader), and subagent coverage with fallback wakeup — catches the majority of measured stall classes without producing the false-positive class the current regex hook produces.

Wrong when:
- Agents game the gates by writing trivially-passing verification commands (e.g., `verification.sh = true`), satisfying the letter but escaping the spirit
- The wakeup-and-respawn cycle introduces new failure modes that exceed the time saved (e.g., orphaned wakeups, double-spawn races, respawn loops)
- The deterministic check fails to catch a non-trivial class of stalls not visible in the current measurement (unknown unknowns)

Liveness: would know within ~2 weeks of deploying the MVP by re-running session-miner on post-deployment transcripts and comparing short-prod rate, terminal-tool-call rate, and false-positive count to the 14-day baseline.

## Success criteria

- Short-prod rate (`well?`, `now?`, `continue`, etc. in transcripts) drops to **<10% of current** within 4 weeks of MVP deployment.
- Long-horizon multi-agent runs complete unattended **>90%** of the time, or fail with a documented blocker bead.
- **Zero false-positive blocks** by the new Stop gate (vs three by the current regex hook in this single conversation).
- Harness maintenance burden stays **under** time saved — negative ROI means delete.
- Portable: writing a Codex or pi.dev adapter takes **days, not weeks**.
