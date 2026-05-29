# continuation-harness

Deterministic Stop-gate harness for Claude Code (and, via adapters, other agent CLIs). Targets the stall classes diagnosed in the 14-day session-miner analysis (May 2026): announced-poll-then-waited, narrate-then-stop, phase-complete-then-stop.

Design lives in `../openspec/changes/continuation-harness/`.

## Source vs. runtime state (the install model)

This directory is **source only** — code, schemas, tests. `INSTALL.sh` symlinks `bin/` and `schemas/` into `~/.claude/harness/`, and runtime state lives there too. **Nothing is ever written into a repo working tree**, and the code carries **no hardcoded clone path** (it self-locates and reads state from `~/.claude/harness`, overridable via `CONTINUATION_HARNESS_HOME`). So you can clone this repo to any path, run `INSTALL.sh`, and every Claude session in any repo uses the same decoupled harness.

```
# Source (this repo — symlinked into ~/.claude/harness by INSTALL.sh):
harness/
├── bin/
│   ├── would_block_stop.py     # pure gate fn + thread_dir_for_session + harness_home
│   ├── verify                  # agent affordance — runs verification_command, writes last_run
│   ├── stop_hook.py            # Claude Code Stop-hook adapter (self-locating)
│   ├── init_contract.py        # scaffold a contract
│   └── baseline.py             # baseline metrics scanner
├── schemas/{contract,scheduled}.schema.json
└── tests/test_gate.py          # gate + session-isolation + portability tests

# Runtime state (~/.claude/harness — real dirs, NOT this repo, NOT symlinked):
~/.claude/harness/
├── bin -> <repo>/harness/bin           # symlink (code)
├── schemas -> <repo>/harness/schemas   # symlink (code)
├── threads/{session_id}/               # per-session contract.json + scheduled.json
└── incidents.jsonl                     # append-only gate-decision log
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

> ⚠ **Wakeup caveat (until the launchd waker ships — see "Still v0.1+").** A
> future-dated `scheduled.json` entry unlocks Stop, but nothing yet *fires* that
> wakeup automatically. Treat a registered wakeup as **human-must-resume**: it lets
> the turn end cleanly, but the agent will not be re-invoked on its own until the
> waker daemon exists. Do not rely on a wakeup as autonomous resumption for
> unattended work.

Coexists with `~/.claude/hooks/validate_no_shirking.py` — both fire on Stop, both can block. Additive coverage.

## Session isolation (v0.1 — 2026-05-20)

Thread directories are keyed by session id: `harness/threads/{CLAUDE_CODE_SESSION_ID}/`. Every Claude Code session — including each named subagent, which is its own session — gets an isolated thread dir, so concurrent agents working the same repo never clobber each other's `contract.json`. Resolution is identical across the three touch points (`would_block_stop.thread_dir_for_session()`, the `verify` shell script, and `init_contract.py`):

1. `HARNESS_THREAD_DIR` env override (tests / special cases)
2. sanitized `CLAUDE_CODE_SESSION_ID` → `threads/{session_id}` (in-session tools) / `payload.session_id` (Stop hook) — these are the same value
3. fallback → `threads/current` (single-session / non-Claude contexts)

`threads/current/` remains as the fallback bucket only; it is no longer the default for live Claude Code sessions.

## Still v0.1+

Full 57-stall regression test, launchd waker firing scheduled wakeups (and carrying thread identity across respawns), bead-derived contracts, human-readable `(team_id, agent_name)` naming layered on top of session-id keying, and the supervisor daemon.
