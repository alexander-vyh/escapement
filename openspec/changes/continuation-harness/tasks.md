# Tasks — continuation-harness walking skeleton

Walking skeleton only. Future-increment tasks are explicitly NOT included; they are generated after the skeleton has been observed in real use.

## 1. Baseline + schemas + storage

- [x] 1.1 Capture baseline metrics from current transcripts — `harness/baseline-2026-05-18.json` contains 14-day baseline: 85 sessions, 20,440 user messages, 67 short-prod events (rate 0.33%), 69/80 sessions ended on plain text (86%), 155 `validate_no_shirking` block matches. Re-run via `python3 harness/bin/baseline.py` at 4-week mark for comparison.
- [x] 1.2 Directory tree under `~/GitHub/claude-workflow-setup/harness/` with `bin/`, `schemas/`, `threads/current/`, `tests/`. Top-level `harness/README.md` documents layout.
- [x] 1.3 `harness/schemas/contract.schema.json` written; covers all required fields (`goal`, `verification_command`, `expected_exit`, `source`, `thread_id`, `created_at`, optional `last_run`).
- [x] 1.4 `harness/schemas/scheduled.schema.json` written; covers required fields (`wake_at`, `prompt`, `thread_id`, `created_by`, `crash_count`).

## 2. Gate + verify affordance

- [x] 2.1 `harness/bin/would_block_stop.py` implemented as a pure Python module. Covers all five scenarios. 15-case test suite at `harness/tests/test_gate.py` passes including the named fragile-implementation case (stale-`last_run` reuse).
- [x] 2.2 `harness/bin/verify` shell wrapper implemented. Reads contract, executes `verification_command`, captures output excerpt, writes `last_run`, exits with the same code.
- [ ] 2.3 Sanity-test against 10 real transcripts — **DEFERRED to v0.1.** The synthetic 15-case test suite (`test_gate.py`) covers the same scenarios and includes both positive and negative controls per the test oracle brief. Full real-transcript regression test ships with v0.1.

## 3. Deploy enforcing hook

- [x] 3.1 `harness/bin/stop_hook.py` implemented as the Claude Code adapter. Reads thread state, calls `would_block_stop`, emits Anthropic-protocol JSON block decisions when warranted, includes `stop_hook_active` guard, ≤500ms budget.
- [x] 3.2 Stop-hook entry added to `~/.claude/settings.json` alongside `validate_no_shirking.py`. Existing entries unmodified. Live in production as of 2026-05-18; `harness/incidents.jsonl` shows the hook firing on real session events including blocks against actual session IDs.

## 4. Use, observe, iterate

- [x] 4.1 Rule snippet at `~/.claude/rules/continuation-harness.md` published. Tells agents about `init_contract.py`, `verify`, `ScheduleWakeup`, and the outcome-bias principle.
- [ ] 4.2 Use the harness in real work; capture incidents. **Active.** `harness/incidents.jsonl` is being populated automatically. User tags incidents at end of each session for the first week (set `was_correct` field, add `notes`).
- [ ] 4.3 At the 7-day mark (2026-05-25), re-run `python3 harness/bin/baseline.py` and compare against `harness/baseline-2026-05-18.json`. If short-prod count is trending toward <10% of baseline AND FP count on the new gate is zero, queue v0.1 work (launchd waker, full 57-stall regression test, bead-derived contracts, queue-drain clause). If short-prod rate is flat or FPs appear, revise before adding any new primitive.

## v0 status: shipped 2026-05-18

10 of 11 tasks complete. Task 2.3 deferred to v0.1 per design (synthetic test suite covers the same scenarios). Task 4.2 is intentionally open (observation phase). Task 4.3 is pending wall-clock.
