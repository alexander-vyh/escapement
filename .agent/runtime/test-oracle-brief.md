# Test Oracle Brief — continuation-harness v0 gate

Scope: tests for `harness/bin/would_block_stop.py` and the supporting filesystem state primitives. This brief governs the test plan for the deterministic Stop gate at the heart of the harness.

## Business invariant

A Claude Code session MUST NOT terminate at Stop without having either (a) demonstrated completion via verification exit code matching `expected_exit` within the current turn, OR (b) scheduled its own resumption via a future-dated wakeup entry, OR (c) been explicitly released by the user typing a stop-class word. Stopping in any other state is the failure the harness exists to prevent.

## Session-isolation invariant (v0.1 — added 2026-05-20)

Two concurrent Claude Code sessions (a parent agent and a named subagent, or two separate terminals working the same repo) MUST have isolated contract storage. One session declaring or verifying its contract MUST NOT overwrite, read, or be confused by another session's contract.

The independent source of truth for "which session am I" is the session identifier: `CLAUDE_CODE_SESSION_ID` (environment variable, available to in-session Bash tool calls) for the in-session tools (`verify`, `init_contract`), and `payload.session_id` (Stop hook stdin) for the Stop hook. These two values are the same for a given session, so both resolve to the same thread directory: `harness/threads/{session_id}`.

- **Negative control:** session A writes `contract.json`; session B writes its own `contract.json`. A's contract MUST be byte-identical afterward (no overwrite). This is the exact bug being fixed — v0 used a single shared `threads/current/` and B clobbered A.
- **Positive control:** session A's `verify` updates A's `last_run`; A's Stop hook reads A's fresh `last_run` and returns allow. Session B's empty thread is unaffected and B's Stop hook still blocks (B has no proof).
- **Resolution invariant:** `thread_dir_for_session(session_id)` MUST be a pure function of `(HARNESS_THREAD_DIR override, session_id, HARNESS_ROOT)` — deterministic, no I/O, same inputs → same path. Override (`HARNESS_THREAD_DIR`) wins for testing; absent session_id falls back to `threads/current` (backward compat, single-session contexts).
- **Sanitization:** session_id is used as a path component, so it MUST be sanitized (alnum/dash/underscore only, length-capped) to prevent path traversal or invalid directory names. A malicious or malformed session_id MUST NOT escape the `threads/` directory.
- **Fragile implementation to reject:** keying by anything that is NOT unique-per-session — e.g., cwd, repo path, or a global "current" pointer. Those collide exactly when two agents share a repo, which is the reported failure. The test MUST include two distinct session_ids resolving to two distinct dirs.

## Independent source of truth

The filesystem state at `harness/threads/{thread}/contract.json` and `harness/threads/{thread}/scheduled.json`, plus the most recent user message text from the Claude Code session transcript. Each of these is observable without invoking the gate logic itself; the test can construct synthetic state directly without reading any production artifact.

## Solution constraints

- **Pure function.** `would_block_stop(thread_state: dict)` takes a state dict, returns a tuple. No I/O inside the decision function. (File loading is in a separate `load_thread_state` helper that the tests bypass.)
- **No prose pattern matching.** The function MUST NOT inspect any free-form text from the agent's output. Only structural data — exit codes, timestamps, enumerated user-stop strings — drives decisions. This is the explicit user requirement.
- **No LLM calls.** Deterministic, sub-millisecond evaluation only.
- **Same input → same output, always.** No clocks beyond comparing `last_run.timestamp` and `wake_at` to "now"; tests parameterize "now" via fixture timestamps so the same case is reproducible across machines.
- **Stop-hook budget: <100 ms per call.** Tests do not enforce this directly but the implementation must respect it (no network, no large file reads).
- **Default to block.** When state is missing or malformed, the function returns `("block", _)`. Never default-allow.

## Invalid solution classes

- Implementation that consults the agent's assistant message text in any way.
- Implementation that returns "allow" by default when state files are missing, malformed, or have unexpected types.
- Implementation that accepts a passing `last_run` from arbitrary time in the past (stale-run reuse) — `last_run` timestamp MUST be within the current-turn window (default 300 s).
- Implementation that ignores `expected_exit` and treats any non-zero exit as "verified" or any zero exit as "verified" regardless of the declared expectation.
- Implementation that counts past-dated `wake_at` entries as valid wakeups.
- Implementation that matches user-release on substrings or fuzzy matches rather than the explicit enumerated set.

## Fragile implementation to reject

The tempting shortcut: checking only that `contract.json#/last_run` exists (without validating `exit_code == expected_exit` AND fresh timestamp). This passes the happy-path test but accepts any historical passing run as proof of current completion — defeating the outcome-bias principle the gate exists to enforce. **Tests MUST include a stale-`last_run` case that the gate correctly blocks**, and a `last_run` with mismatched exit code that the gate also blocks.

## Negative control

A `thread_state` containing `contract.last_run = {exit_code: 0, timestamp: <10 min ago>, …}` and no wakeup and no user release MUST yield `("block", "no_completion_or_resumption_proof")`. This proves the gate does NOT accept stale verifications as proof of current completion.

Second negative control: `thread_state = {}` (everything missing) MUST yield `("block", "no_contract")`. This proves the gate defaults to block.

## Positive control

A `thread_state` containing `contract.last_run = {exit_code: 0, timestamp: <now>, …}` (with `expected_exit: 0`) MUST yield `("allow", "verification_passed")`. This proves the happy path is not accidentally broken by overzealous stale-detection or default-to-block logic.

Second positive control: `thread_state = {scheduled: [{wake_at: <future>, …}]}` MUST yield `("allow", "wakeup_registered")` even when no contract exists. This proves the wakeup escape valve works without a contract.

## Missing / unresolved handling

- Missing files → loader returns `None` → function treats as null.
- Unparseable JSON → loader returns `None` → function treats as null.
- Past-dated `wake_at` entries → silently ignored (not counted as wakeups).
- Non-dict entries inside `scheduled` array → silently ignored.
- Unrecognized user message text → treated as not a user release.
- Fields beyond the schema → silently ignored (forward compatibility).
- `last_run` present but missing `timestamp` → treated as no run.
- `last_run.timestamp` malformed (non-ISO-8601) → treated as no run.

The default for any unresolved or ambiguous state is fail-closed: block Stop. The user's "outcome-bias not action-bias" principle says inaction is preferable to wrong action; in this gate's terms, blocking is preferable to allowing on uncertain state.

## Final outcome verification

`python3 harness/tests/test_gate.py` must exit 0 with all cases reported as PASS. The test suite enumerates the canonical scenarios: verification_passed (fresh), verification_passed (stale → blocks), verification_failed (exit mismatch → blocks), wakeup_registered (future), wakeup_past (does not count), user_released ("stop"), user_released ("end here."), no_contract no_wakeup no_release, contract present but no proof, wakeup wins over absent contract.

For the gate's integration with Claude Code (post-test-pass): a manual smoke test invoking `harness/bin/stop_hook.py` with a synthetic JSON payload on stdin must return `{"decision": "block", ...}` JSON for a state with no contract and no wakeup, and exit 0 with no output for a state with a fresh passing verification.

## Notes on what this brief does NOT cover

- The `verify` shell script's correctness (separate behavior, separate brief if needed).
- The Claude Code Stop-hook adapter's handling of the full Anthropic hook protocol (separate manual smoke test).
- The shape and content quality of agent-declared `verification_command`s (out of scope; user/bead-author responsibility).
- The full 57-stall regression test (deferred to v0.1).
