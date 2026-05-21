# continuation-harness

Deterministic Stop-gate harness for Claude Code (and, via adapters, other agent CLIs). Targets the stall classes diagnosed in the 14-day session-miner analysis (May 2026): announced-poll-then-waited, narrate-then-stop, phase-complete-then-stop.

Design lives in `../openspec/changes/continuation-harness/`. This directory is the v0 implementation.

## Layout

```
harness/
├── bin/
│   ├── would_block_stop.py     # pure gate function — block or allow
│   ├── verify                  # agent affordance — runs verification_command, writes last_run
│   ├── stop_hook.py            # Claude Code Stop-hook adapter
│   └── init_contract.py        # helper for agents to scaffold a contract
├── schemas/
│   ├── contract.schema.json    # JSON Schema for contract.json
│   └── scheduled.schema.json   # JSON Schema for scheduled.json
├── threads/
│   └── current/                # the active thread directory (v0 — single active thread)
│       ├── contract.json       # agent-declared outcome contract
│       └── scheduled.json      # array of durable wakeup entries
├── tests/
│   ├── contract-schema.test.json
│   ├── scheduled-schema.test.json
│   └── test_gate.py            # sanity-test for would_block_stop
├── incidents.jsonl             # append-only log of every gate decision
└── baseline-{date}.json        # captured baseline metrics
```

## How it works (v0)

1. Agent declares its outcome via `contract.json` (or invokes `bin/init_contract.py` to scaffold).
2. When the agent considers the task done, it runs `bin/verify` — this executes `verification_command`, captures the exit code, writes `last_run` back to `contract.json`.
3. At Stop, the Claude Code adapter (`bin/stop_hook.py`) calls `would_block_stop(thread_state)`:
   - **allow** if `last_run.exit_code` matches `expected_exit` within the current turn
   - **allow** if `scheduled.json` has a future-dated wakeup entry
   - **allow** if the user typed an explicit-stop word
   - **block** otherwise
4. Block decisions return a constructive resumption prompt; the agent receives it and continues.

Coexists with `~/.claude/hooks/validate_no_shirking.py` — both fire on Stop, both can block. Additive coverage.

## Session isolation (v0.1 — 2026-05-20)

Thread directories are keyed by session id: `harness/threads/{CLAUDE_CODE_SESSION_ID}/`. Every Claude Code session — including each named subagent, which is its own session — gets an isolated thread dir, so concurrent agents working the same repo never clobber each other's `contract.json`. Resolution is identical across the three touch points (`would_block_stop.thread_dir_for_session()`, the `verify` shell script, and `init_contract.py`):

1. `HARNESS_THREAD_DIR` env override (tests / special cases)
2. sanitized `CLAUDE_CODE_SESSION_ID` → `threads/{session_id}` (in-session tools) / `payload.session_id` (Stop hook) — these are the same value
3. fallback → `threads/current` (single-session / non-Claude contexts)

`threads/current/` remains as the fallback bucket only; it is no longer the default for live Claude Code sessions.

## Still v0.1+

Full 57-stall regression test, launchd waker firing scheduled wakeups (and carrying thread identity across respawns), bead-derived contracts, human-readable `(team_id, agent_name)` naming layered on top of session-id keying, and the supervisor daemon.
