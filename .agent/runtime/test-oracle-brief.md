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

# Test Oracle Brief — stop-gate hardening (blocker-laundering close-out)

Covers three coordinated requirements (R1 winddown floor, R2 blocked-bead drain,
R3 blocker-claim verification). The change exists because a 931k-token session
laundered its stop through the harness's own vocabulary: it filed a blocker bead
("blocked on another team's test / Salesforce delivery timing" — the "other team"
did not exist), which drained `bd ready`, so `_check_task_mode_queue` returned
`("allow", "queue_drained")`, and the model wrote "This is a clean, honest
stopping point." and stopped — no ScheduleWakeup, blocker claim validated by
nothing. Three holes lined up: the winddown regex never matched "stopping point";
an empty `bd ready` allowed Stop even with blocked beads present; and a blocker
claim could be pure prose with no verification.

## 1. Business invariant

Three invariants, one per requirement, all serving one outcome — **a task-mode
session cannot reach a stop by asserting a blocker; it must either finish the
scoped queue, schedule a verifiable resumption, or be released by the user.**

- **R1 (winddown floor):** `is_winddown_offer()` returns True for stop-declaration
  phrasing of the "stopping point" family ("This is a clean, honest stopping
  point.", "good/natural/reasonable stopping point ...") so that, with reversible
  work remaining, the wind-down rung blocks it into continuation. It must NOT fire
  on "stop"/"point" used in non-wind-down senses (an implementation question, a
  loop's stopping *condition*, "I'll keep going from this point").
- **R2 (blocked-bead drain):** in `_check_task_mode_queue`, an empty `bd ready`
  that coexists with ≥1 scoped *blocked* bead no longer yields a free
  `queue_drained` allow. It yields `("block", "blocked_tasks_no_wakeup")` whose
  display text names the agent-invokable escapes (ScheduleWakeup; unblock/close the
  bead if the blocker is refuted; user "stop"). Empty ready + zero blocked stays
  `("allow", "queue_drained")`, unchanged.
- **R3 (blocker verification):** when the *release path is a wakeup* and scoped
  blocked beads exist, every gating blocked bead must carry a `blocker-verify:
  <cmd>` that exits 0 within a bounded timeout OR a substantive `blocker-waiver:
  <reason>`. Otherwise `("block", "wakeup_blocker_unverified")`. A trivial verify
  command (`true`, `:`, `exit 0`, empty/whitespace) is rejected **without
  execution**; a placeholder waiver (<20 chars, "tbd"/"n/a"/"todo"/...) is rejected.

## 2. Independent source of truth

- **R1:** the literal assistant message text and human judgment of whether it is a
  stop offer — encoded as labeled positive/negative string fixtures, NOT the regex
  itself (an implementation-echo test that imported `_WINDDOWN_PATTERNS` and re-ran
  it would prove nothing).
- **R2/R3:** the `bd` query results (`ready` list, the blocked-bead list) and the
  bead's own text fields, supplied through the **injectable `run_bd(args) ->
  Optional[list]`** seam — identical to `test_task_mode_queue.py`'s `_fake_runner`.
  Correctness is observable from inputs (ready empty? how many blocked? does each
  blocked bead carry a passing verify / valid waiver?) without reading the gate's
  branches.
- **R3 execution:** real subprocess exit codes of safe commands (`true` exits 0,
  `false` exits 1) are the oracle for "did the verify actually run and pass" — not
  a mock asserting a runner was called.

## 3. Solution constraints

- Stop-hook (`harness/bin/`), stdlib only, state-only sibling-import style. All bd
  access through the injectable `run_bd`; tests MUST inject, never spawn real bd.
- **Scope discipline (load-bearing):** the blocked-bead probe MUST be scoped the
  same way `bd ready` is — via `--parent <parent_id|task_id>`. Probing the whole
  repo backlog re-opens exactly the over-reach the team already walked back
  (stop_hook.py "Without scoping, bd ready returns the entire repo backlog, causing
  derailment into unrelated tasks", and the `_check_bd_queue_implicit` watermark
  carve-out). A session parked next to unrelated blocked backlog must still drain.
- **bd-failure degradation unchanged:** `ready is None` keeps the existing
  `has_beads_dir` split (`task_mode_bd_ready_failed` vs `task_mode_bd_unavailable`).
  The blocked probe is reached only when `ready == []`.
- **gate-design three rules:** every new block reason's display text names an
  agent-invokable escape IN the denial (ScheduleWakeup / unblock-or-close /
  user-stop); decisions flow through `_log_incident` → `_record_gate_signal`;
  validation is value-not-presence (R3 substance floors; R2 fires on real blocked
  beads, not a flag).
- **R3 bounded timeout** ~10s; command error/timeout = unverified (NOT confirmed) —
  the waiver is the escape, so a flaky verify is never a trap that strands the
  agent.
- **user_released stays unconditional** in all three requirements (the user's
  release valve is never gated by blocker verification).

## 4. Invalid solution classes

- **(a) Presence-only blocker-verify** — accepting any non-empty command string as
  "verified" without running it (the `--verify "true"` class the harness exists to
  catch). R3 unit tests must reject `true`/`:`/`exit 0` *without execution* and must
  require a `false` command to yield unverified.
- **(b) Display-only gate** — adding a `blocked_tasks_no_wakeup` entry to
  `_TASK_MODE_DISPLAY` while `_check_task_mode_queue` still returns `("allow", ...)`.
  Tests assert the *decision* is `block`, not merely that nicer text exists.
- **(c) Over-broad R1 regex** — a pattern keying on "stop", "point", or "?" that
  also fires on legitimate questions / code discussion. Negative controls must pass
  against the new patterns, not just the old ones.
- **(d) Unscoped blocked-bead probe** — querying repo-wide blocked beads so a
  session parked beside unrelated blocked backlog blocks. The fake must return
  blocked items only for the *scoped* query; an unscoped impl that blocks on
  out-of-scope blocked work fails the drain test.
- **R3 mock-only execution** — mocking the command runner and asserting it was
  called, instead of observing a real exit code. Rejected per
  implementation-echo-tests; R3 execution tests use real `true`/`false`.

## 5. Fragile implementation to reject

Named, must each fail at least one test:

- **F1 — "any nonempty `blocker-verify` string passes."** Defeated by an R3 test
  that supplies `blocker-verify: false` (nonempty, runs, exits 1 → unverified) AND
  a test that supplies `blocker-verify: true` and asserts it is rejected as trivial
  *without* being counted as a pass. A presence-only impl allows both → fails.
- **F2 — "rename the reason / add display text, still return allow."** Defeated by
  R2 tests asserting `decision == "block"` for ready-empty-plus-blocked, and an R3
  integration test asserting `("block", "wakeup_blocker_unverified")`. A
  text-only change leaves the decision `allow` → fails.
- **F3 — "broad regex on stop/point/?"** Defeated by R1 negatives ("Postgres or
  SQLite?", "the loop's stopping condition", "I'll keep going from this point",
  "at this point the parser returns"). A broad impl matches them → fails.
- **F4 — "probe blocked beads unscoped."** Defeated by an R2 drain test where the
  *scoped* blocked query returns `[]` (and the impl is expected to allow), paired
  with the scoped-block test where it returns ≥1. An unscoped impl that pulls
  repo-wide blocked work blocks the drain case → fails.
- **F5 — "waiver presence-only."** Defeated by R3 waiver tests rejecting "tbd",
  "n/a", a <20-char reason, and accepting a real ≥20-char non-placeholder reason.

## 6. Negative control

- **R1:** "Should I use Postgres or SQLite?", "the loop's stopping condition is
  wrong", "I'll keep going from this point", "at this point the parser returns
  None" → `is_winddown_offer` False.
- **R2:** empty ready + **zero** blocked → `("allow", "queue_drained")` (unchanged);
  non-empty ready → `("block", "tasks_remain_in_queue")` (unchanged, blocked probe
  not even consulted).
- **R3:** a blocked bead carrying `blocker-verify: false` → unverified (the verify
  ran and failed, proving execution happened); `blocker-verify: true` → rejected as
  trivial (proving the substance floor); waiver "tbd" → rejected.
- **Scope:** scoped blocked query returns `[]` despite repo having blocked backlog
  → drain allowed.

## 7. Positive control

- **R1:** "This is a clean, honest stopping point.", "good stopping point", "a
  natural stopping point to pause", "this is a reasonable stopping point to hand
  off" → `is_winddown_offer` True; and with `reversible_work_remains=True` →
  `winddown_decision` blocks (`winddown_offer_work_remains`).
- **R2:** empty ready + ≥1 scoped blocked bead, no wakeup →
  `("block", "blocked_tasks_no_wakeup")`; `_TASK_MODE_DISPLAY["blocked_tasks_no_wakeup"]`
  exists and names "ScheduleWakeup".
- **R3:** blocked bead with `blocker-verify: false`-style passing command (use real
  `true`-equivalent at the verify layer via a `blocker-verify: <a real exit-0
  command that is not in the trivial set>`) → confirmed; blocked bead with a
  ≥20-char non-placeholder `blocker-waiver:` → allowed; at `main()`/integration
  level: wakeup registered + every scoped blocked bead verified/waivered → allow.

## 8. Missing/unresolved handling

- **R1:** empty/None text → False (fail-open: no offer, no block).
- **R2/R3:** `ready is None` (bd failure) → existing degradation, blocked probe NOT
  reached. Blocked query returning None (bd hiccup on the *second* call) → treat as
  **unknown, fail toward block** inside a real beads repo (do not silently allow a
  drain we couldn't verify); degrade to allow only where the existing ready-None
  path already degrades. Pin this in a test.
- **R3:** a blocked bead with NEITHER a `blocker-verify` NOR a `blocker-waiver` line,
  under the wakeup path → unverified → block (a bare blocker claim is the original
  incident). Command timeout/error → unverified, not confirmed.

## 9. Final outcome verification

`python3 -m pytest harness/tests/ -q` — all 159 pre-existing tests still pass; new
`harness/tests/test_blocked_bead_gate.py` (R2 + R3, including `blocker_verify` unit
tests) and the new R1 functions in `harness/tests/test_winddown_gate.py` pass once
implemented. Integration oracle: a task-mode Stop payload with a wakeup registered
and a scoped blocked bead carrying no verify/waiver → `_check_task_mode_queue` (or
the `main()` wakeup-path branch) yields `wakeup_blocker_unverified` block, and the
emitted denial text names ScheduleWakeup + unblock/close + user-stop.

## Design-tension verdict (R3) — for the adversarial verifier

R3 makes `wakeup_registered` **no longer a fully-universal override in task mode
when scoped blocked beads exist**: a wakeup releases Stop only if each gating
blocked bead is verified or waivered. This is the correct call. The wakeup
override's purpose is "I am genuinely waiting on an external event and will return
to check it" — its legitimacy *rests on* the blocker being real. The incident is
the exact failure of treating the override as unconditional: a fabricated blocker
plus a (here, absent) wakeup laundered a permanent stop. Gating the wakeup-release
on blocker verifiability restores the override's precondition rather than removing
the override. The escape stays cheap and agent-invokable: a real `blocker-verify`
command (one line) or a substantive `blocker-waiver` reason re-opens the wakeup
path immediately — and `user_released` remains unconditional, so a human is never
trapped. The residual cost is that a legitimate blocker with no scriptable check
must be expressed as a waiver (≥20 chars) rather than waved through; that is the
intended friction (a labeled signal), not a trap.

---

# Test Oracle Brief — worktree-guard escape classes (bead claude-workflow-setup-q0f)

Three behaviors (A1 detection-escapes, A2 foreign-worktree-operation guard, A3
stop-gate worktree degradation). All three trace to one incident: a cake session
operated inside a *pre-existing foreign worktree* via `git -C /private/tmp/main-tree
fetch/checkout -b ...`. The creation guard never fired (its regex is prefix-anchored
to `^git worktree add`, and it gates CREATION only, not operating inside an existing
non-bd worktree), and downstream `stop_hook._check_task_mode_queue` degraded to
`("allow","task_mode_bd_unavailable")` because a worktree has no literal `.beads/`
dir — so the foreign worktree silently ungated the Stop gate.

## 1. Business invariant

- **A1:** `beads_worktree_guard` must DENY a worktree-CREATION command even when
  `git worktree add` is reached through intervening global flags (`git -C <dir>
  worktree add`, `git --git-dir=… worktree add`) or inside a compound command (`cd
  x && git worktree add …`, `env FOO=1 git worktree add …`), inside a beads project.
  It must still ALLOW genuinely-innocent git commands (`git log`, `git status`).
- **A2:** when a git STATE-CHANGING command (`checkout`, `switch`, `pull`, `merge`,
  `commit`, `rebase`, `reset`, `cherry-pick` — pinned list) targets, via `-C <dir>`
  or cwd, a *linked worktree* whose main repo has `.beads/` but which lacks
  `.beads/redirect`, the guard must DENY with the beads-worktree skill's recovery
  path (`bd worktree create <path> -b <branch>`; do NOT `bd init` inside a worktree)
  named IN the denial, emit `_gate_signal.record(...)`, and document a waiver escape.
  READ-ONLY git (`log`, `status`, `diff`, `show`, `branch --list`) must PASS.
- **A3:** `stop_hook._check_task_mode_queue` — when `repo_cwd` is a *linked worktree*
  (its `.git` is a FILE containing `gitdir: …`) whose resolved main repo HAS
  `.beads/`, a bd-unavailable result must degrade to **BLOCK** (the laundering
  channel — a foreign worktree must not free-allow Stop), while a genuinely
  non-beads cwd keeps the current `("allow","task_mode_bd_unavailable")`.

## 2. Independent source of truth

- **A1:** the literal command string + the cwd's beads context (`.beads/` at cwd or
  an ancestor, or `BEADS_DIR`). Observable without the guard's regex. Tests drive
  `main()` with a PreToolUse payload (mirroring `test_beads_worktree_guard._run`) and
  read the emitted `permissionDecision` JSON + exit code — never the private regex.
- **A2:** the filesystem layout — `.git` is a FILE (`gitdir:`) for a worktree; the
  main repo (resolved from the gitdir pointer) has `.beads/`; the worktree lacks
  `.beads/redirect`. Plus the command's subcommand + `-C` target. All fabricated
  with `tmp_path`; no real git, no real bd.
- **A3:** the injected `run_bd` returning None (bd can't resolve) + the fabricated
  worktree layout (`.git` file → main repo with `.beads/`). The decision tuple is
  observable from those inputs.

## 3. Solution constraints

- Hooks: stdlib, fail-OPEN on malformed stdin (never wedge the pipeline), canonical
  deny mechanism (permissionDecision="deny" JSON on stdout, exit 0 — NOT exit 2),
  per the existing guard's contract.
- A3 in `harness/bin/`: stdlib, state-only, all bd via injectable `run_bd`; tests
  hermetic with `tmp_path` worktree layouts. The `.git`-file detection must resolve
  the main repo and check ITS `.beads/`, not the worktree's.
- gate-design three rules on every new deny: escape IN the denial (A2: the `bd
  worktree create` recovery + a `# beads-worktree-waiver: <reason>` ≥20-char escape);
  `_gate_signal.record(gate=…, decision=…, reason=…, **extras)`; value-not-presence
  (A2 fires on a REAL foreign-worktree layout — `.git` file + main `.beads/` + no
  redirect — not on a flag; A1 matches the REAL `worktree add` token, not any string
  containing "worktree").
- **A1 matcher-widening trade-off — the brief takes a position (verifier, attack
  this):** the settings matcher `Bash(git worktree add:*)` is *prefix*-scoped, so
  `git -C x worktree add` never reaches the hook regardless of how good the regex is
  — the runtime never invokes it. **Position: register a SECOND matcher
  `Bash(git:*)` for this guard** (keeping the existing narrow one), and widen the
  in-hook regex to detect `worktree add` after intervening flags / in compound
  commands. Cost: a python-startup on every `git …` Bash call (~tens of ms). This is
  judged acceptable because (a) the guard already short-circuits with a cheap regex
  `match`/`search` and returns 0 before any beads-dir walk for non-worktree git, and
  (b) the alternative (matcher stays narrow) leaves A1 *structurally unclosable* —
  the most common escape (`git -C`) bypasses the runtime invocation entirely. The
  rejected alternative — drop matcher scoping to bare `Bash` — is worse: it pays the
  startup on EVERY Bash call, not just git. The test pins the registration of BOTH
  matchers so a regression that drops the wide one re-opens the `git -C` hole.
- **A1 known limitation (documented, not fixed):** a regex over the command string
  cannot distinguish `git worktree add` from `echo "git worktree add"` /
  `# git worktree add` without full shell parsing. **Line: accept the
  false-positive** (a denied `echo` is a cheap, self-evident annoyance with the
  recovery command right there; the agent re-words and proceeds) rather than risk a
  false-NEGATIVE (a real `worktree add` slipping through inside a heredoc/quote is
  the exact failure the guard exists to prevent). The test asserts the documented
  behavior: a `worktree add` token preceded by a real command separator (`&&`, `;`,
  `|`, newline) or as the first git invocation DENIES; a bare `git log` ALLOWS. We do
  NOT add a test demanding `echo "git worktree add"` pass — that would pin the
  fragile parse we are explicitly declining to build.

## 4. Invalid solution classes

- A1 regex that only re-anchors but still requires `git` to be the literal first
  token (misses `git -C x worktree add`).
- A1 widening the in-hook regex while leaving the matcher narrow (regex never runs
  for `git -C`).
- A2 detecting "is a worktree" by `.git`-file presence ALONE, without checking the
  resolved main repo has `.beads/` (would deny worktree ops in plain-git multi-
  worktree repos — over-block).
- A2 blocking READ-ONLY git in a foreign worktree (over-block; log/status/diff must
  pass).
- A3 keying the degradation on `repo_cwd/.beads` existence alone (the current bug —
  a worktree has no `.beads/` dir so it free-allows). Must resolve the `.git`-file
  main repo.
- Any of the above with presence-only `_gate_signal` / a placeholder waiver.

## 5. Fragile implementation to reject

- **F-A1 "anchor-only regex"**: `^\s*git\s+worktree\s+add` widened to `\bgit\b.*\bworktree\s+add\b`
  but matcher unchanged → `git -C x worktree add` STILL never reaches the hook.
  Defeated by `test_guard_registered_on_wide_git_matcher` (asserts `Bash(git:*)` is a
  registered matcher) + a `git -C` payload test that expects DENY.
- **F-A2 "worktree = .git-file"**: deny any state-changing command whose target has a
  `.git` FILE, skipping the main-repo `.beads/` check. Defeated by
  `test_plain_git_worktree_operation_allowed` (a worktree whose main repo has NO
  `.beads/` → ALLOW).
- **F-A2b "deny everything in the foreign worktree"**: deny read-only too. Defeated
  by `test_readonly_git_in_foreign_worktree_allowed`.
- **F-A3 "dir-check degradation"**: `has_beads_dir = (cwd/'.beads').exists()` only.
  Defeated by `test_foreign_worktree_bd_unavailable_blocks` (worktree `.git` file →
  main repo with `.beads/` → bd None → must BLOCK) paired with
  `test_genuine_non_beads_cwd_still_allows` (no `.git` file, no main `.beads/` → bd
  None → still allow).

## 6. Negative control

- A1: `git log --oneline`, `git status`, `git commit -m "worktree add docs"` (the
  phrase only in a commit message — but note: `git commit` is itself an A2 concern
  inside a foreign worktree; in a NON-beads cwd it must ALLOW) → no CREATION deny.
- A2: `git -C <foreign-wt> log` / `git -C <foreign-wt> status` → ALLOW.
  `git -C <plain-git-worktree> checkout main` (main repo has no `.beads/`) → ALLOW.
- A3: `repo_cwd` with no `.git` file and no resolvable main `.beads/`, `run_bd`→None
  → `("allow","task_mode_bd_unavailable")` unchanged.

## 7. Positive control

- A1: `git -C /tmp/main worktree add ../wt -b foo` in a beads project → DENY naming
  `bd worktree create`; `cd /tmp/main && git worktree add ../wt` → DENY.
- A2: `git -C <foreign-wt> checkout -b feature` where `<foreign-wt>/.git` is a file,
  the resolved main repo has `.beads/`, and `<foreign-wt>/.beads/redirect` is absent
  → DENY naming `bd worktree create` + the no-`bd init` warning; signal recorded.
- A3: worktree `repo_cwd` (`.git` file → main `.beads/`), `run_bd`→None → BLOCK.

## 8. Missing/unresolved handling

- A1/A2: malformed stdin / unparseable command → fail-OPEN (exit 0, allow) —
  unchanged contract.
- A2: a `.git` file whose `gitdir:` pointer is unresolvable / main repo missing →
  cannot confirm a foreign-beads worktree → fail-OPEN (allow). The guard only fires
  on a POSITIVELY-confirmed foreign-beads-worktree layout.
- A3: `.git` file present but main-repo resolution fails → treat as non-beads
  (current allow) rather than block on an unconfirmed inference — A3 blocks only when
  the main `.beads/` is POSITIVELY resolved. (Bias note: A3 biases toward BLOCK only
  on confirmed beads context, mirroring the existing `has_beads_dir` semantics.)

## 9. Final outcome verification

`python3 -m pytest claude/hooks/tests/test_beads_worktree_guard.py harness/tests/ -q`
— new A1/A2 cases in `test_beads_worktree_guard.py` and new A3 cases in a
`harness/tests/` file pass once implemented; all currently-green tests stay green
(combined python baseline today: 806 passed). Integration oracle: a PreToolUse
payload `git -C <beads-main> worktree add ../wt` → deny JSON naming `bd worktree
create`; a fabricated foreign-worktree `_check_task_mode_queue` with `run_bd`→None →
`("block", …)`.

## A1 matcher-widening verdict — for the adversarial verifier

The position above (add a second `Bash(git:*)` matcher rather than widen to bare
`Bash` or leave it narrow) is the load-bearing design call. Attack surface: (1) the
per-`git`-call python startup — measure it; if the team deems it unacceptable, the
fallback is a shell-level pre-filter in the hook command (`grep -q 'worktree add'`
before invoking python), which the test should then pin instead. (2) The
false-positive line on `echo "git worktree add"` — if the team wants that to pass, it
requires real shell tokenization (shlex of the whole pipeline), which re-introduces
parse fragility; the brief's position is to decline it and accept the cheap
false-positive. Both are deliberately surfaced, not hidden.

---

# Test Oracle Brief — INSTALL.sh --update pin-dir drift (bead claude-workflow-setup-egk)

RAPID FORM (3-section). Low-blast-radius: one resolution step in `--update`. The
fragile-implementation challenge (below) passes against the 3-section subset, so the
short form is legitimate.

**Context.** `ensure_pinned_checkout` operates on `$ESCAPEMENT_PIN_DIR` (default
`~/.claude/.escapement-pinned`, legacy fallback `CWS_PIN_DIR`). A machine installed
in the CWS era has `~/.claude/*` symlinks resolving into `~/.claude/.cws-pinned`. A
bare `./INSTALL.sh --update` (no env override) refreshes `.escapement-pinned` — a
checkout NOTHING links to — while the live pin (`.cws-pinned`) stays stale. This is
how the wind-down judge sat undeployed.

### 1. Business invariant

`./INSTALL.sh --update` (no env override) must refresh the checkout that the
**currently-deployed symlinks actually resolve into**, not a hard-coded default. The
effective pin dir is resolved from a deployed sentinel symlink's real target (e.g.
`readlink -f "$CLAUDE_DIR/hooks/<a-deployed-hook>"` → strip back to its checkout
root), so:
- **B1:** symlinks point into `.cws-pinned` + bare `--update` → `.cws-pinned` is the
  dir fetched/ff-merged.
- **B2:** an explicit `ESCAPEMENT_PIN_DIR=…` env override still WINS over symlink
  resolution (operator intent is authoritative).
- **B3:** fresh install (no deployed symlinks to resolve) → current behavior (default
  `.escapement-pinned`), unchanged.
- **B4:** symlinks resolve into dir X while the env default is dir Y (mismatch, no
  explicit override) → the update must target X (the live one) OR fail loudly — it
  must NEVER silently fast-forward Y while X stays stale.

### 2. Negative control (what must fail if the code is wrong)

A `--update` run in a sandbox HOME whose deployed hook symlink points into
`$HOME/.claude/.cws-pinned`, with NO `ESCAPEMENT_PIN_DIR` set, that touches
`.escapement-pinned` (creating/fetching it) while leaving `.cws-pinned` at its old
commit → FAIL. The test asserts the OLD commit in `.cws-pinned` advanced (or the run
errored loudly), and that the run did NOT silently create/advance a `.escapement-
pinned` that nothing links to. (This is exactly the drift that left the judge
undeployed.) Positive control: B3 fresh install still produces `.escapement-pinned`
and green symlinks.

### 3. Final outcome verification

`bash tests/test_install_pinned.sh` (extended with the B1–B4 cases, same sandboxed-
HOME + `ESCAPEMENT_PIN_REMOTE=$REPO` offline harness; `--dry-run` to assert the
resolved target dir in the planned output where a real fetch is undesirable). The
load-bearing assertion: after a bare `--update`, the dir whose commit changed is the
one the live symlinks resolve into. Manual: on a CWS-era machine, `readlink -f
~/.claude/hooks/<hook>` and the "refreshing pinned checkout: <dir>" log line name the
SAME directory.

### Fragile-implementation challenge (mandatory in rapid form)

**F-B "update whatever dir the env var says and exit 0"** (the current behavior:
`ensure_pinned_checkout` reads `$ESCAPEMENT_PIN_DIR` and ff-merges it, ignoring where
symlinks point). Against the 3-section subset: the **negative control (§2)** fails it
directly — symlinks point at `.cws-pinned`, no env override, F-B refreshes
`.escapement-pinned` and exits 0, so `.cws-pinned`'s commit never advances → the
assertion "the dir whose commit changed is the one symlinks resolve into" fails. The
short form is therefore legitimate (the oracle and the negative control both survive
the cut; only the restatement sections were dropped). A second fragile impl —
**"always resolve from symlinks, ignore the env override"** — is caught by B2 (explicit
override must win); the test includes it so the resolution order is pinned, not just
the resolution.

---

# Test Oracle Brief — wind-down rung: kill the regex floor, judge-only (ARCHITECTURE CHANGE)

User directive (supersedes all prior regex-floor work, incl. the F3 lookahead dispute —
dev stood down): wind-down classification is SEMANTIC. The local-LLM judge
(`winddown_judge.py`) becomes the SOLE classifier. The deterministic regex floor
(`_WINDDOWN_PATTERNS` + `is_winddown_offer`) is REMOVED. "Semantic or nothing": when the
judge is unavailable there is no regex backstop — fail-open to allow — BUT the outage is
SIGNALLED so it is visible (gate-design Rule 2 / the same F5 class as the R3 ImportError
fail-open).

## 1. Business invariant

- Classification of "is this assistant turn a wind-down / decision-punt offer" comes
  ONLY from the judge's verdict. No string pattern decides it.
- `winddown_judge.decide(text, work, model_offer)`: offer ⇔ `model_offer is True`. There
  is no `regex_offer or ...` union. False → not-offer (allow). None → unavailable → allow.
- `winddown_gate` is reduced to `RECOVERY_PROMPT` + `winddown_decision(text, work,
  is_offer)`; `is_offer` is the caller-supplied verdict. With the floor gone, an absent
  verdict (`is_offer=None`) means "no offer → allow", NEVER "consult a regex".
- `stop_hook._winddown_override`: the structural prefilter is UNCHANGED — it runs ONLY
  on a `conversational` allow with reversible work remaining (bd/git). Within that slice,
  classification = a fresh message-scoped cached verdict, else the inline judge (bounded
  `_INLINE_JUDGE_TIMEOUT`, fail-open). The `not _wg.is_winddown_offer(text)` regex
  consultation at the cache-cold branch is REMOVED — the judge is consulted whenever work
  remains and the cache is cold.
- Judge unavailable / timeout / unclear (None) WITH work remaining → ALLOW **and** a
  `winddown_judge_unavailable` signal recorded via `_log_incident` (→ incidents.jsonl +
  the `.gate-signal.jsonl` bridge). Silent fail-open is forbidden.
- Verdict cache semantics (message-scoped `text_sha`, `_WINDDOWN_VERDICT_FRESH_SECONDS`
  freshness window) are UNCHANGED — pinned to survive the refactor.

## 2. Independent source of truth

The judge's verdict, supplied through the existing INJECTABLE seams — `judge=` (a
`Callable[[text], Optional[bool]]`) on `_winddown_override`/`_compute_winddown_verdict_inline`,
`post=` on `model_verdict`, and `is_offer=`/`model_offer=` on
`winddown_decision`/`decide`. Tests inject the verdict directly; no running model, no
regex. The structural-prefilter truth (work-remains via bd `work_check` / git) and the
cache file (`winddown_verdict.json`) are observable filesystem state. The fail-open
signal's truth is the incidents log (redirected per-test via `sh.INCIDENTS_LOG`).

## 3. Solution constraints

- Stop-hook + sibling modules, stdlib, fail-open philosophy. The judge MUST be bounded
  and never block/crash the hook.
- The structural prefilter (conversational + work-remains) is the gate on WHEN we
  classify — it must not change, or the judge starts running on every turn (latency).
- gate-design Rule 2: the fail-open ALLOW emits a labeled signal. Rule 1: the block
  denial (`RECOVERY_PROMPT`) keeps naming the escape (proceed / async-flag / user-stop)
  — unchanged.
- never-suppress: the removed regex tests are REPLACED by equal-or-stronger judge-only
  oracles, not deleted. The phrase-level true-positive corpus (wrap/night/"stopping
  point"/separate-clause "for today") moves to the JUDGE's fixtures — it is no longer a
  hook-level assertion because the gate no longer classifies prose.

## 4. Invalid solution classes

- Leaving `is_winddown_offer`/`_WINDDOWN_PATTERNS` on the module (floor survived).
- `decide` still doing `regex_offer or (model_offer is True)` (union remnant) — a
  judge-down session would still block obvious wraps via the regex.
- `winddown_decision(is_offer=None)` falling back to a regex (or crashing on the deleted
  helper) instead of allowing.
- `_winddown_override` still short-circuiting the judge when the regex would have caught
  the text (judge never consulted → the judge isn't actually the classifier).
- Silent fail-open: judge None → allow with no signal (invisible outage).
- Changing the structural prefilter so the judge runs outside the conversational +
  work-remains slice (latency regression / over-nag).
- Touching the cache freshness / message-scoping (a stale verdict mis-firing).

## 5. Fragile implementation to reject

- **"Union remnant"**: `decide` keeps the regex `or`. Defeated by
  `test_judge_unavailable_allows_even_obvious_wrap` (None + obvious wrap → MUST allow),
  `test_model_says_not_offer_allows` (False + wrap text → allow), and
  `test_decide_does_not_consult_any_regex` (monkeypatches `is_winddown_offer` to explode).
- **"Regex pre-empt remnant"** in `_winddown_override`: defeated by
  `test_judge_IS_consulted_for_obvious_offer_no_regex_preempt` (spy asserts the judge IS
  called for a wrap offer the old regex caught).
- **"Silent fail-open"**: defeated by `test_fail_open_emits_judge_unavailable_signal`
  (redirects `sh.INCIDENTS_LOG`, asserts a `winddown_judge_unavailable` record).
- **"Floor not actually removed"**: defeated by `test_regex_floor_api_removed` /
  `test_regex_floor_is_removed` (assert the API is gone).

## 6. Negative control

- `decide(text, work, model_offer=False)` → allow / `no_winddown_offer`, for ANY text
  including an obvious wrap — the judge's NO is authoritative.
- `winddown_decision(is_offer=True, reversible_work_remains=False)` → allow (no-work gate
  still prevents nagging a legitimate stop — UNCHANGED).
- Structural prefilter: no bd/git work → `_winddown_override` returns None and the judge
  is NEVER consulted (`test_inline_judge_NOT_called_when_no_work_remains`, kept).

## 7. Positive control

- `decide(text, work, model_offer=True)` → block, for BOTH a wrap phrase and a paraphrase
  the old regex missed (judge owns both equally).
- Fresh cached verdict short-circuits the inline judge (`test_cached_verdict_short_circuits_inline_judge`, kept).
- Git-aware work-remains still flips a bd-drained session to block when the (injected)
  verdict says offer (`test_git_flips_bd_drained_to_block_in_override`, now judge-injected).

## 8. Missing/unresolved handling

- Judge None (down / unclear / unparseable) → ALLOW (fail-open) + `winddown_judge_unavailable`
  signal. The structural prefilter still gates this to the conversational + work-remains
  slice, so a healthy non-winddown turn never even reaches the judge.
- Empty/None assistant text → no override (None), unchanged.
- Cache miss + judge None → allow + signal (the slice where the outage matters).

## 9. Final outcome verification

`python3 -m pytest harness/tests/test_winddown_gate.py harness/tests/test_winddown_judge.py
harness/tests/test_winddown_live.py -q` — the judge-injected rung tests, the architecture
guards (regex API removed), the judge-only `decide` semantics, and the fail-open-signal
test all pass once the refactor lands; the surviving cache/git/prefilter tests stay green.
Full harness suite stays green except these intended reds until dev implements. Manual:
with the local model down, a conversational stop with unpushed commits → allow AND an
incidents.jsonl record reason `winddown_judge_unavailable`.

## SCOPE NOTE (no tests) — validate_no_shirking.py is also regex-based

The OTHER Stop hook, `claude/hooks/validate_no_shirking.py`, is likewise regex/prose-
pattern based. The user's "semantic or nothing" ruling arguably extends to it, but that
is a SEPARATE, larger change (a different hook, different corpus, its own judge wiring).
Named here as KNOWN-OUT-OF-SCOPE so it lands as a follow-up bead rather than as silent
inconsistency. Not touched by this change; no tests added for it here.

