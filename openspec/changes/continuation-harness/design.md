# continuation-harness — design

## Problem Statement

After this work, Claude Code agents that today stop one tool-call short of done, sit idle waiting on subagents, or announce future check-ins without scheduling them instead either *finish the outcome* (verification passes) or *schedule their own return*. The user stops typing "well?" and "continue" because the agent has either produced a verifiable result or registered a wakeup that will resume the work on its own. Stall classes that today consume hours of wall-clock and dozens of token-wasting rebukes become mechanically impossible: there is no Stop path that doesn't pass through "proof of completion or proof of resumption."

## Non-Goals

1. **Won't replace the markdown rule layer.** Rules in `~/.claude/rules/*.md` continue to describe correct behavior; the harness mechanically enforces what the rules already say. Discovering a stall class that needs new behavioral guidance still means updating the rules, not the harness.
2. **Won't judge outcome quality.** The harness checks whether a declared `verification.sh` exits 0. It does not assess whether the verification is meaningful, whether the code is good, or whether the agent's chosen approach was sound. Contract quality is the bead author's and the user's responsibility.
3. **Won't run LLM-judge logic in the Stop gate.** No Anthropic `type: "prompt"` hooks, no reviewer subagents, no probabilistic stuck-detection in the MVP. Determinism is a design property, not an optimization.
4. **Won't track cost.** Token-spend ledgers, per-task budgets, and parallel-agent caps are out of MVP scope by explicit user direction.
5. **Won't fleet-scale.** Refinery-style bisecting merge queue, Mayor planner-router, and 20+ parallel-agent orchestration are out of scope. Target scale is 2-8 named agents per team.
6. **Won't retire the existing regex Stop hook.** `validate_no_shirking.py` is a net-positive piece of enforcement today — it regularly catches real shirking the user wants caught. It continues running alongside the new gate. The two are additive: the regex sees prose patterns, the new gate sees tool-use shape and verification state. Retirement is not on the table; *improving* the regex hook (e.g., reducing its false-positive rate by gating on session state from the new harness) is a viable future increment.
7. **Won't write its own verification commands.** Where a bead has acceptance criteria, `verification_command` is derived from those. Where no bead exists, the agent declares a contract and the harness surfaces it for first-run human review.

## Capabilities

### New Capabilities

- `outcome-contract` — declared per-task, stored as `contract.json`, runnable via `verification_command`
- `verification-gate` — exit-code-based Stop barrier; the load-bearing primitive
- `durable-wakeup-registry` — `scheduled.json` + launchd waker; turns "I'll check back" from prose into a mechanically-enforced re-spawn
- `stop-barrier-supervisor` — level-triggered reconciler that observes session state and either permits Stop or blocks with a constructive resumption signal
- `identity-layer` — `(team_id, agent_name)` schema across all threads; single-agent is just team-of-one
- `adapter-claude-code` — first concrete adapter; translates Claude Code session events into the canonical journal shape and writes back wakeup entries

### Modified Capabilities

None. This is a greenfield addition under `claude-workflow-setup/harness/`. The existing regex Stop hook (`validate_no_shirking.py`) is unmodified; the new gate runs as a separate Stop-hook entry in `~/.claude/settings.json` alongside it.

## Impact

- **New directory tree** under `~/GitHub/claude-workflow-setup/harness/` containing the supervisor, adapter, schemas, and per-thread storage.
- **New launchd entry** under `~/Library/LaunchAgents/` for the supervisor + scheduled-wakeup waker.
- **Modified `~/.claude/settings.json`** — adds a Stop-hook entry pointing at the new gate. The existing `validate_no_shirking.py` entry is retained.
- **No changes to `beads`** — the harness reads `bd` state but does not write to it. (Future increments may write blocker beads on documented failures.)
- **No changes to Serena, OpenSpec, or the existing rules layer.**
- **No existing artifacts retired or modified.** The regex Stop hook is unchanged; this work is purely additive. The only existing file touched is `~/.claude/settings.json`, which gains a new Stop-hook entry without altering any existing entries.

## Riskiest Assumption

**We believe** a small set of deterministic mechanically-checkable gates — verification command exit code, registered durable wakeup, and (in future increments) bead-queue drain and subagent coverage — catches the majority of measured stall classes without producing the false-positive class the current regex hook produces. **We will know this is true when** session-miner re-scan at the 4-week mark shows the short-prod rate (`well?`, `now?`, `continue`) has dropped to <10% of the current 14-day baseline AND the new gate produced zero false-positive blocks on legitimate technical content over the measurement window. **If false**, we revert to the current rule-based discipline, accept that the stall problem requires LLM-judge or human-in-the-loop primitives the MVP deliberately excluded, and re-evaluate whether to invest in Anthropic Managed Agents migration or a different architecture entirely.

Embedded alternative (rejected): an LLM-judge Stop hook (Anthropic `type: "prompt"`) that semantically classifies the session's terminal state via a Haiku call. Rejected because (a) the failure mode under scrutiny is paraphrase-fragility, and an LLM judge has its own paraphrase-fragility shape (different mistakes, same class); (b) it adds per-Stop cost that compounds; (c) the user's stated requirement is *deterministic* tools, not better heuristics.

Probes:
- *What changes if false?* The MVP design becomes wrong — we'd need an LLM judge or reviewer-subagent layer the MVP deliberately excluded. Schema and supervisor architecture survives; only the gate logic changes.
- *How fast would we discover?* The walking skeleton's shadow phase (task 3) surfaces it within one week of real-session data.
- *Can we test before code?* Partially — we can replay the existing 57-stall transcript sample against a paper version of the gate logic before writing the supervisor. Worth doing as task 0.

## Walking Skeleton

Ship today. The skeleton deploys the deterministic Stop gate in **enforcing mode** alongside the existing regex hook (both can block; both are additive). The riskiest-assumption test happens against real session data starting the day the gate ships, not on a delayed observation cycle.

Targeted stall class: 30% announced-poll-then-waited (largest single category). Scope: verification-passed OR wakeup-registered OR explicit-user-release. No queue-drain, no subagent-coverage, no contract gaming protection beyond first-run human review of agent-declared contracts — those are v0.1+ increments.

1. **Baseline + schemas + gate logic** (~75 min). Capture current short-prod rate, terminating-tool-call rate, and FP-block count from existing transcripts as `harness/baseline-{date}.json`. Create the directory tree under `harness/`. Write JSON Schemas for `contract.json` and `scheduled.json`. Implement `would_block_stop(thread_state) -> (decision, reason)` covering all five gate scenarios (verification_passed, wakeup_registered, user_released, no_completion_or_resumption_proof, no_contract). Sanity-test against 10 recent transcripts to confirm correct decisions before deployment — the full 57-stall regression test is v0.1, not today.

2. **Agent affordance — `verify` script** (~30 min). The agent's bridge to the gate: reads its `contract.json`, runs `verification_command`, writes the result (exit code, timestamp) back to thread state. Agents invoke `verify` as a Bash tool call when they consider themselves done; the gate then sees the resulting `last_run` and either allows Stop or doesn't.

3. **Deploy the enforcing Stop hook** (~60 min). Write the Claude Code adapter as an enforcing Stop hook (returns `{"decision": "block"}` on the JSON protocol when conditions warrant) alongside `validate_no_shirking.py`. Register in `~/.claude/settings.json` without modifying existing entries. Verify live with two real Claude Code sessions: one that calls `verify` with a passing contract (gate allows Stop), one that ends on prose "I'll check back" without `ScheduleWakeup` (gate blocks Stop).

Cutting test: this is the minimum that *enforces* the riskiest-assumption check against real traffic. Anything more — full regression test, launchd waker firing wakeups, bead-derived contract auto-generation, queue-drain, subagent-coverage, supervisor process — is v0.1 or later, after observing how v0 behaves in real use.

## Proof of Delivery

This is done when the enforcing Stop gate is live in `~/.claude/settings.json`, has blocked at least one real announced-poll-then-waited stall in a real session AND has not blocked any legitimate completion in the first 24 hours of use — observable by the user's session experience plus the harness's own decision log. If the gate fires a clear false-positive in the first day, it's tuned (or temporarily disabled while tuned) before the 4-week measurement window starts. The 4-week measurement window then evaluates the larger riskiest-assumption proof: short-prod rate <10% of baseline AND zero FP blocks comparable to the regex hook's pattern.

## Anti-Metrics

1. **Token spend per task increases.** If the harness causes more re-spawns, longer per-turn responses, or additional shadow-overhead such that aggregate token cost rises — even if stall counts drop — the cure is worse than the disease.
2. **User cognitive load increases.** If the user finds themselves thinking about `contract.json` authoring, `scheduled.json` state, or harness internals on a per-task basis, the harness has failed its transparency goal. Measure: count of harness-related user prompts ("why didn't it stop?" / "what's in the shadow log?") in transcripts.
3. **False-positive count > 0** on the new gate. Any single block that prevents legitimate work is a failure regardless of how many real stalls were caught. The bar is exactly zero.

## Decisions

**Deterministic gates only in MVP.** Filesystem state + exit codes + structured tool-call inspection. Alternatives: LLM-judge Stop hook (rejected — paraphrase-fragility in a different shape, adds cost); reviewer-not-author subagent (rejected for MVP — high token cost, delegates judgment to LLM); regex content matching (rejected — demonstrated three false-positives in this design session).

**External supervisor + filesystem state, not in-CLI hooks.** The supervisor reads `~/harness/threads/{thread_id}/` files and is invariant across CLI choice. Alternatives: pure Claude Code hooks (rejected — non-portable, hooks can't see across compaction); Anthropic Managed Agents (rejected for MVP — early beta, vendor lock-in, would still need portable fallback for Codex/pi).

**Bead-derived contracts where possible, agent-declared otherwise.** Verification commands default to `bd show <id> --acceptance-criteria` output. Alternatives: agent-declared every time (rejected — agent can slop contracts to escape gates); user-declared every time (rejected — too much friction for routine work).

**2-8 named-agent scale.** Designed for current user pattern. Alternatives: single-agent (rejected — user runs multi-agent regularly per rules); fleet/Gastown scale (rejected — cost-ineffective at current model performance per user; explicit out-of-scope).

**Thin adapter per CLI.** Supervisor knows nothing about Claude Code specifically; each adapter is one of: Claude Code (MVP), Codex (future), pi.dev (future). Alternatives: Claude-only (rejected — explicit user requirement for portability); pi-native TypeScript (rejected — user is currently on Claude Code).

**Existing regex Stop hook is a net-positive enforcement layer; new gate is additive.** The regex hook catches real shirking the user wants caught; FPs are noise that injects token-cost but does not halt work. The two layers see different things — regex sees prose patterns, new gate sees tool-use shape and verification state. Alternatives: replace immediately (rejected — the regex hook is doing useful work today and removing it would regress); shadow then retire (rejected — retirement isn't the goal; *improving* the regex hook's FP rate by gating on harness state is the path forward if FPs become a measured problem).

**Strategic alternative: do nothing / wait for Managed Agents.** Considered and rejected. Public beta April 2026; maturity 6-12 months out is speculative; pain is current and rising. The MVP is designed to be small enough (<1k LOC target) that migration to Managed Agents — if it matures — is a days-not-weeks port.

**Strategic alternative: change workflow rather than build tooling.** Considered (smaller tasks, less aggressive parallelism, fewer named agents). Rejected because session-miner data shows stall rates do not correlate with task size; user's multi-agent productivity gains are real and measurable; workflow change would trade a known win for an unmeasured one; and crucially, would not address the regex hook's false-positive problem at all.

## Risks & Trade-offs

- **Contract gaming** (agents write trivial `verification.sh = true`) → Bead-derived contracts where possible; first-run human review for novel contracts; periodic audit of contract content via independent agent (post-MVP).
- **Wakeup loops** (wakeup fires, agent re-announces, wakeup re-schedules indefinitely) → OTP-style crash budget (`MaxR`/`MaxT` analogue): hard cap on consecutive wakeups for a thread; escalate to user after N.
- **Adapter rot** (Claude Code changes its session format) → Adapter is isolated, ~200 LOC; format changes are observable and infrequent; failed parse degrades gracefully (gate refuses to enforce when state is unparseable, accepts FP risk over corruption risk).
- **Supervisor itself stalls** → launchd respawn on exit; per-thread heartbeats both ways; supervisor is short-running (level-triggered reconciler ticks every N seconds, doesn't hold state in memory).
- **Race conditions in multi-agent state files** → Per-agent journals avoid most contention; team-level writes are routed through `bd` which already handles concurrency.
- **Time spent building exceeds time saved** → MVP scope is one stall class (announced-poll); kill-criterion built into Proof of Delivery; total LOC budget under 1k.
- **Anthropic Managed Agents subsumes the layer** → Accept. Keep the design small enough that migration cost is bounded; identity layer `(team_id, agent_name)` maps cleanly onto Managed Agents' persistent-filesystem model.
- **Shadow phase produces ambiguous data** → Pre-commit the replay test (skeleton task 1) as a baseline; if shadow data is ambiguous, the replay test is the tiebreaker.

## Future Increments [PLACEHOLDER]

Options purchased by validating the riskiest assumption:

- **queue-drain check** — extend the Stop barrier to inspect `bd ready` across molecule/epic scope; addresses the 9% phase-complete-then-stop class.
- **subagent-coverage clause** — auto-register a fallback wakeup whenever the agent dispatches subagents; addresses the parent-sits-for-hours pattern explicitly.
- **bead-chain continuation** — explicit support for "closed one bead, claim the next" as a Stop-barrier clause, not just a rule-layer expectation.
- **reviewer-not-author subagent Stop hook** (Layer 3) — only if FP count > 0 in MVP, or if a stall class emerges that purely-deterministic checks cannot catch.
- **Codex adapter** — when portability is exercised (vendor change, exploration, or specific Codex strengths warrant it).
- **pi.dev adapter** — same trigger; lightest implementation given pi's TS extension model and native JSONL.
- **Cost ledger** — token-spend tracking per task with soft caps; explicitly deferred per user direction.
- **File-level claims for multi-agent edits** — when measured edit conflicts on shared files justify the lock primitive.
- **Predecessor-session interrogation ("seance")** — when cross-session handoffs become routine enough to warrant first-class support.
- **Integration-stream branching** — when 3+ parallel agents on shared code routinely produce merge-cone conflicts.
- **Improve `validate_no_shirking.py`** — reduce its false-positive rate by gating the prose-pattern check on session state from the new harness (e.g., fire only if the regex matches AND `verification_command` did not pass this turn AND no wakeup is registered). Keeps the catches the user values; eliminates the technical-discussion FPs.
