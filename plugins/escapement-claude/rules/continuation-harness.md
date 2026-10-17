# continuation-harness — outcome-or-resumption gate (live)

A new deterministic Stop gate runs alongside `validate_no_shirking.py`. Both can block; they are additive. The harness gate enforces **outcome-bias over action-bias**: stopping is forbidden unless you've demonstrated completion, scheduled your own resumption, or been explicitly released by the user.

## The three Stop-permission paths

You may Stop iff one of these is true:

1. **Verification passed this turn.** You ran `~/.claude/harness/bin/verify`, it exited 0, and the run happened within the last 5 minutes.
2. **Wakeup registered.** You called `ScheduleWakeup` for a future-dated check-in. The wakeup entry exists in your session's thread dir (`~/.claude/harness/threads/{session_id}/scheduled.json`, keyed by `CLAUDE_CODE_SESSION_ID`).
3. **User released.** The user typed `stop`, `end here`, `done for now`, `that's enough`, `we're done`, `halt`, etc.

**A session that changed code must have declared an outcome.** If you edited a tracked,
non-gitignored file inside a git tree and no contract exists, Stop is blocked with
`no_declaration`. The requirement is *derived* from your own transcript, never asked for
up front and never self-declared — so a conversation, a read-only investigation, or a
session that only wrote to `/tmp` or a scratchpad is never gated. Declare the outcome
(`derive_contract.py --bead <id>`, else `init_contract.py`), or revert the edits.

If none of these holds, Stop is blocked with a constructive resumption prompt. This is
a real control transition: the attempted turn ends and the agent must resume through a
new turn. It can therefore consume time, tokens, and user attention; do not describe it
as harmless noise or use repeated blocks as a continuation strategy.

## Action-local waits

An unresolved consequential choice **blocks only that action and its dependents**;
**independent authorized work continues**. Preserve the blocked dependency, run other
ready work, and return to the decision only when it becomes the last remaining route.
The session is `input_required` only when no authorized path toward the delegated
outcome remains runnable. Informational side questions do not cancel the active outcome;
answer them and resume unless the user explicitly redirects or stops the work.

<!-- escapement:detail:start -->

## How to declare a contract

### Preferred: declare the oracle on the bead, once

If the work is tracked by a bead, put the oracle in the bead's acceptance criteria as
a fenced `verify` block. `harness/bin/derive_contract.py` reads it and builds the
contract — `goal` from the bead title, `verification_command` from the block,
`source: bead-derived`. No second authoring step.

The acceptance criteria carry prose plus one fenced block tagged `verify`:

~~~text
<what a user must be able to observe>

```verify
<shell command whose exit 0 proves that outcome>
```
~~~

Pass that whole string to `bd create --acceptance=...` (or `bd update <id> --acceptance=...`
to add one to an existing bead). A concrete example:

~~~text
The Finance close line reads plain language and states whether the close is
authoritative or degraded. No rendered close-status string contains an
underscore-derived enum, including for an unmapped basis value.

```verify
cd src/dashboards/frontend && npx vitest run outcome/outcome-1940.test.jsx
```
~~~

Only a fence tagged `verify` counts, so an illustrative ``` block in the criteria is
never mistaken for an oracle. Absent or trivial oracles (`true`, `:`, `echo x`) are
rejected — the deriver is fail-closed, and **a bead with no verify block yields no
contract at all**, which silently degrades "done" to whatever is mechanically
checkable (a green suite, clean lint) rather than to the outcome the bead exists to
produce.

Write the oracle against the surface a reader actually sees — render the component,
call the endpoint, query the report — not against a helper function. "A test exists"
is not an outcome; "the line on the page reads X" is.

### Fallback: hand-author when there is no bead

```bash
python3 ~/.claude/harness/bin/init_contract.py \
  --goal "<one sentence: what 'done' means for the user>" \
  --verify "<shell command whose exit 0 proves done>"
```

The `--verify` command is the **oracle**. It must be something whose exit code
mechanically demonstrates the outcome — an end-to-end behavioral check, a report/query
assertion, or a public workflow state check. Task closure such as `bd close <id>` is
tracking state, not an independent outcome oracle. Sloppy contracts (`--verify "true"`)
get caught at first-run human review for novel/`agent-declared` sources.

<!-- escapement:detail:end -->
### Contracts for config work (you still owe one)

Config/docs work being TDD-exempt does NOT exempt it from a continuation-harness contract. TDD-exemption means "no unit test"; the harness still wants proof the outcome happened. The right `--verify` for config is the appropriate rung of the behavioral-config ladder (see `tdd-enforcement.md` § "Behavioral config is not exempt"), NOT a parse check, and NOT `true`:

<!-- escapement:detail:start -->
| Config kind | `--verify` oracle |
|-------------|-------------------|
| Passive config / docs (data an app reads, prose) | parse check is fine: `python3 -c "import yaml; yaml.safe_load(open('f.yml'))"` / `python3 -c "import json; json.load(open('f.json'))"` |
| GitHub workflow YAML (routine) | `actionlint .github/workflows/<f>.yml` (mandatory floor) |
| GitHub workflow YAML (trigger / auth / deploy-gating) | `gh workflow run <f>.yml --ref <test-branch> && gh run watch <id> --exit-status` + assert the *downstream* run started. Lint alone is forbidden here. If unreproducible locally, register a **waiver** (see below) instead of a fake green. |
| Terraform / OpenTofu (config-authoring) | `tofu validate` then a deterministic plan assertion, e.g. `tofu plan -out=tfplan && tofu show -json tfplan \| jq -e '<assertion about resource_changes>'` |
| Kubernetes manifests | `kubeconform <f>` then `kubectl apply --dry-run=server -f <f>` |

<!-- escapement:detail:end -->
If the real behavior can only be observed after merge (platform semantics, no sandbox), do NOT register a passing parse-check as the contract. Instead declare the contract's verification as the **post-merge observation command** and keep verification pending until that observation is available. A green parse check standing in for an unverified trigger change is exactly the oracle-downgrade the harness exists to prevent.

<!-- escapement:detail:start -->
## How to verify

When you consider the task done:

```bash
~/.claude/harness/bin/verify
```

The script runs your contract's `verification_command`, captures the result back to
`contract.json#/last_run`, and exits with the same code. If exit 0 and within the
current-turn window, the gate allows Stop next time. If it fails, fix the underlying
issue. If an unresolved consequential choice blocks that action, persist the dependency
and continue independent authorized work; documenting a failure is durable state, not
completion.

<!-- escapement:detail:end -->
Do **not** pick up unrelated ready tasks from `bd ready` to drain the queue and satisfy the gate. Continue only the delegated outcome.

## Completion target: ship it live

Done means merged and deployed where the change actually runs — not "PR opened" or
"committed locally." There is no git completion ceiling. Commits, task-branch pushes,
pull-request updates, and a repository's standard declared landing path are authorized
ordinary means, not categorically human-only. If an action genuinely crosses delegated
authority (a new credential, an undelegated irreversible shared effect), name that exact
dependency and continue the rest.

### Per-repo outcome authorization — the durable authorization the base prompt defers to

<!-- escapement:support-claims:start
confirm-class-enforcement=reserved
confirm-class-enforcement-reason=Repository confirmation classes are stored but are not currently enforced by the merge authorization hook.
deploy-execution=informational
deploy-execution-reason=Repository deploy metadata is surfaced as outcome context and does not execute or independently authorize a deployment command.
code-touch-detection=partial
code-touch-detection-reason=The no_declaration gate derives whether a session changed code from that session's transcript. Write, Edit, MultiEdit and NotebookEdit calls carry an explicit path and are detected exactly; Bash-mediated writes (sed -i, redirects, heredocs, tee, cp/mv, patch, git apply) are recognised by pattern and are high-recall but not exhaustive, so a sufficiently indirect write can evade detection. A missing transcript, missing cwd, or unavailable git all resolve to did-not-touch-code, so the gate fails open by design.
codex-code-touch-detection=unsupported
codex-code-touch-detection-reason=The no_declaration gate derives whether a session changed code from that session's transcript. The Codex Stop adapter loads thread state without a transcript path or cwd, because Codex transcripts are not parsed (nullable path, undocumented format), so touched_code is always false there and a Codex session that changed code still stops as conversational. The requirement is enforced on Claude only.
codex-scheduled-continuation=unsupported
codex-scheduled-continuation-reason=Codex has no scheduled wakeup, task-mode repository binding, or local judge rung, so a Codex session that genuinely ends is not re-entered; its Stop adapter reuses the shared decision core only while the session is live.
pi-stop-gate=partial
pi-stop-gate-reason=On omp the stop gates run at a main session's awaited session_stop only: omp emits it for no subagent and does not await extension agent_end, so a delegated worker's stop is not judged; omp itself reminds a subagent to yield and warns its parent when nothing came back. On omp and Pi a stop block holds a session at most once per unchanged reason, repository, contract and active-bead state, and at most three times per session; past that the stop is allowed with an advisory and recorded as stop_livelock_backstop.
-->
<!-- escapement:support-claims:end -->

The base prompt confirms hard-to-reverse actions *unless durably authorized*. A repo's
committed `.escapement/repo.json` **is** that authorization. Read it before merging
(`harness/bin/repo_outcome.py` resolves it):

- `intended_outcome` at or above `merged` **and** `auto_merge_on_green: true` →
  pre-authorized for the declared landing path. On green evidence, **merge and ship it
  live. Do NOT ask "want me to merge it now, or review the PR first?"** — that
  solicitation is the exact anti-pattern this authorization removes. If the repo declares
  a `deploy` surface, name it in your report ("now live at X") rather than ask.
- No declaration, malformed, or `auto_merge_on_green: false` → stop at `pr-opened`, may
  ask. Never assume authorization a repo did not grant.

**The "irreversible external action" carve-out does NOT cover a merge that triggers
auto-deploy.** It covers steps you genuinely cannot perform without a human — typing a
credential, clicking an external approval. A `gh pr merge` you can run is not one — do
not stretch the carve-out to re-introduce the ask the declaration removed.

Support boundary, narrower than the configuration vocabulary: the merge hook does not
observe green status; `confirm_class` is reserved and not currently enforced; `deploy`
metadata is informational. Do not claim stronger enforcement until a point-of-effect fixture proves it.

**Attempt the merge; do not pre-judge repository authorization in conversation.** Run
`gh pr merge <PR> --squash` and let `merge_authorization_gate.py` (PreToolUse on
`Bash(gh pr merge:*)`) return the actual verdict. If it denies, report its
`permissionDecisionReason` — verbatim in substance, never a guess dressed up as an
external constraint. (An agent once invented a "platform-level gate" that branch
protection confirmed did not exist.) To configure a repo, offer
`harness/bin/set_repo_outcome.py` rather than asking the user to hand-write JSON.
