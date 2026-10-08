# shadow_verifier: landing-time verifier in shadow mode

escapement-obwo asks for a landing-time check that catches a non-trivial behaviour
change landing without proof. This hook answers it without enforcing anything:

> **When work landed, would a blocking verifier have stopped it?**

It never blocks, asks, or prints to stdout, and no flag makes it enforce.
Enforcing is a separate change, made only once the promotion rule below is met.

## What counts as a landing

- **`gh pr merge`**, this repo's landing path. The runner resolves the PR with
  `gh pr view` (number, URL, `headRefOid`, state and files; bounded to 5s; if
  it can't resolve them, the landing is `inconclusive`). A PR that is not
  `MERGED` is `not-landed`, which covers a failed merge and an `--auto` merge
  still queued. **The oracle is not run for a merge**: CI already ran the tests
  at that head. Its presence is recorded as `declared` or `no-oracle`.
- **`bd close`**, judged at the commit checked out when the bead was closed.
  The bead's oracle runs in a temporary detached worktree at exactly that
  commit, and the worktree is removed afterwards.

It runs **after** the Bash call (PostToolUse), and only for a call that ran:

- **Claude** sends failed calls to `PostToolUseFailure`, where this hook is not
  registered. `interrupted` is honoured.
- **Pi** sets `is_error` on a failed call, and such a call gets nothing.
- **Codex** has no exit status in its PostToolUse payload. There, and on every
  host, the source of truth is asked instead: GitHub must say `MERGED`, and the
  tracker must say `closed`.

Which commands are landings is `_bd_command`'s shared reading. The whole command
is tokenized first and heredoc bodies are dropped, so a mention inside quotes, a
`-m` message, a `--body` or a heredoc never counts.

## What would block

First, the landed diff is classified the way the TDD gate classifies files: a
behaviour file is anything that is neither a test file nor exempt (docs,
config, scripts and the like). For a merge the diff is the PR's files; for a
close it's the diff from the remote default branch. **No behaviour file means
`not-applicable`**, and nothing is owed.

With a behaviour change, a landing gets `would-block` for any of these
**reason codes**, each recorded in `reason_codes` so they can be counted apart:

| Code | Meaning |
|---|---|
| `oracle-failed` | A closed bead's oracle failed on the landed commit. |
| `no-oracle` | There's nothing to judge it by: a bead with no ```` ```verify ```` block, or a trivial or evaporating one (parsed by `derive_contract`). For a merge it also covers a session with no contract. A merge is bound to the session's contract: its bead, or the contract's own `verification_command`. |
| `no-challenger` | The session dispatched no mutation challenger or outcome verifier. The role is read from whole tokens of the dispatch's `name` and `subagent_type` (Codex: task_name), never from its description or prompt. A reviewer type never counts, whatever it is named, and a negating token (`no-challenger-needed`) disqualifies the name. |

`would-pass` needs every oracle to be passing (close) or declared (merge), plus
a challenger dispatched this session.

`inconclusive` means the landing could not be judged. It never stands in for a
missing oracle or a missing challenger. The reasons:
- an oracle timeout, or the budget running out;
- an unresolvable PR;
- uncommitted changes at close;
- a foreign bead's oracle (not run);
- an unknown landed diff (with a missing oracle or challenger);
- no git checkout;
- the runner is busy (2 per repository) or was terminated.

`error` means the runner itself failed; it keeps the evidence gathered so far.

`duplicate` means the landing was already judged. A landing is the PR and its
head commit, or the closed beads and the commit. A repeated close or merge of
the same landing points at the first verdict through `duplicate_of`, and is
not counted again.

## Records

Every record carries `"gate":"shadow_verifier"`, `kind` (`merge`/`close`),
`landing_id`, `session_id`, `tool_use_id`, the truncated command, `head_sha`
and `reason_codes`. A merge also carries `pr_number`, `pr_url` and `pr_state`.
The hook writes a `provisional` record within its sync limit (2s by default;
`SHADOW_VERIFIER_SYNC_SECONDS` can raise it on a loaded machine, capped at 10s). The detached runner (40s budget) writes
the final one under the same `landing_id`. Records go to the root checkout's
`.beads/.gate-signal.jsonl`. A record that cannot be written is reported on
stderr.

`challengers` lists each matching dispatch. For a synchronous Claude dispatch,
`names_bad_implementations` records whether its reply named bad
implementations. That's a crude text reading, recorded for labelling only and
never part of the verdict.

**Ownership.** An oracle runs only for a bead this session claimed (its
contract) or one assigned to the current bd actor (`$BEADS_ACTOR`, else git
`user.name`, else `$USER`). It is still read for any bead, so a foreign bead
with no oracle is `no-oracle`. Oracles run real shell in the temporary
checkout, which keeps writes off your working tree. Anything outside that
checkout, the network included, is reachable.

## Promotion rule (required before any enforcement)

The thresholds are the user's call and are deliberately left unset. Until all
three `TODO` values are set by the user, the rule is not met.

| Parameter | Meaning | Value |
|---|---|---|
| `OBSERVATION_WINDOW` | Minimum period **and** minimum number of judged landings before the log is reviewed | TODO(user): e.g. N days and M landings |
| `MIN_CATCHES` | Minimum number of `would-block` landings later confirmed as real problems (the landed work was reverted, re-opened, or failed its outcome verification) | TODO(user) |
| `MAX_FALSE_WOULD_BLOCK_RATE` | Maximum share of `would-block` landings whose work proved sound, out of all `would-block` landings in the window | TODO(user) |

Procedure for the review:

1. Pull the window from every signal source (`_gate_signal.signal_sources()`)
   and pair `provisional` and final records by `landing_id`. A `provisional`
   record with no final record (the runner was SIGKILLed) counts as **one**
   `inconclusive` landing. `not-landed` records are excluded: nothing landed.
2. Label each `would-block` a **catch** or a **false would-block**, using
   evidence outside this hook: a revert, a re-opened bead, a failed outcome
   check, or GitHub's record of the merged `head_sha`.
3. Break the would-blocks down by `reason_codes` (`oracle-failed`,
   `no-oracle`, `no-challenger`). Each code must meet the rule on its own
   before that code is enforced. `not-applicable`, `not-landed` and
   `duplicate` records are excluded.
4. Count `inconclusive` and `error` landings separately, once each. They are
   neither catches nor false would-blocks. If they make up a large share, the
   check can't judge enough landings to enforce yet. Fix that first.
5. Promote only when `catches ≥ MIN_CATCHES` and
   `false would-blocks / would-blocks ≤ MAX_FALSE_WOULD_BLOCK_RATE` across
   `OBSERVATION_WINDOW`. Before promoting, add a blocking design that has an
   escape path in its denial and keeps writing persistent signal
   (`claude/rules/gate-design.md`).

## Known limits (deliberately not built)

- **Evidence is the session's, not the landing's** (`evidence_scope:
  "session"`). A challenger dispatched for PR A makes an unrelated merge of PR
  B in the same session look covered. A record carries the PR number and head
  next to the beads and dispatches (`tool_use_id`) its evidence came from, so
  labelling can spot this, but nothing ties a dispatch to a PR.
- **Gap against the acceptance:** escapement-obwo asks for a challenger "whose
  named bad implementations each fail a test". This hook records only that a
  challenger was dispatched. `names_bad_implementations` is a crude reading of
  its reply (Claude, synchronous dispatches only), it is never part of the
  verdict, and nothing checks that each bad implementation fails a test.

- Challenger evidence is per session and means "dispatched". It doesn't show
  that the challenger covered this change, and dispatches are observed on
  PreToolUse, so a dispatch that later failed still counts.
- A close made on the default branch after its merge has an empty branch diff,
  so it is `not-applicable`. The merge carries the verdict.
- A merge's oracle is recorded as declared, not run. That trusts CI to have
  run it at the PR head.
- `bd update <id> --status closed`, `gh api .../merge` and merges made in the
  GitHub UI are not seen.
- A close from a dirty tree is not judged (`inconclusive`), because the landed
  state can't be reproduced.
- The ownership rule trusts the bead's `assignee` and the bd actor as given.
