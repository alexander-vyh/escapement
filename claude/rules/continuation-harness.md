# continuation-harness — outcome-or-resumption gate (live)

A new deterministic Stop gate runs alongside `validate_no_shirking.py`. Both can block; they are additive. The harness gate enforces **outcome-bias over action-bias**: stopping is forbidden unless you've demonstrated completion, scheduled your own resumption, or been explicitly released by the user.

## The three Stop-permission paths

You may Stop iff one of these is true:

1. **Verification passed this turn.** You ran `~/.claude/harness/bin/verify`, it exited 0, and the run happened within the last 5 minutes.
2. **Wakeup registered.** You called `ScheduleWakeup` for a future-dated check-in. The wakeup entry exists in your session's thread dir (`~/.claude/harness/threads/{session_id}/scheduled.json`, keyed by `CLAUDE_CODE_SESSION_ID`).
3. **User released.** The user typed `stop`, `end here`, `done for now`, `that's enough`, `we're done`, `halt`, etc.

If none of these holds, Stop is blocked with a constructive resumption prompt. The block is *noise, not work-halting* — your turn ends, the user sees the prompt, and the conversation continues. But repeated blocks on the same turn waste tokens and user attention.

## How to declare a contract

Before your first implementation tool call on any non-trivial task, scaffold a contract:

```bash
python3 ~/.claude/harness/bin/init_contract.py \
  --goal "<one sentence: what 'done' means for the user>" \
  --verify "<shell command whose exit 0 proves done>"
```

The `--verify` command is the **oracle**. It must be something whose exit code mechanically demonstrates the outcome — `pytest path/to/test.py`, `bd close <id>`, `gh pr view <n> --json state -q '.state == \"OPEN\"'`, etc. Sloppy contracts (`--verify "true"`) get caught at first-run human review for novel/`agent-declared` sources.

### Contracts for config work (you still owe one)

Config/docs work being TDD-exempt does NOT exempt it from a continuation-harness contract. TDD-exemption means "no unit test"; the harness still wants proof the outcome happened. The right `--verify` for config is the appropriate rung of the behavioral-config ladder (see `tdd-enforcement.md` § "Behavioral config is not exempt"), NOT a parse check, and NOT `true`:

| Config kind | `--verify` oracle |
|-------------|-------------------|
| Passive config / docs (data an app reads, prose) | parse check is fine: `python3 -c "import yaml; yaml.safe_load(open('f.yml'))"` / `python3 -c "import json; json.load(open('f.json'))"` |
| GitHub workflow YAML (routine) | `actionlint .github/workflows/<f>.yml` (mandatory floor) |
| GitHub workflow YAML (trigger / auth / deploy-gating) | `gh workflow run <f>.yml --ref <test-branch> && gh run watch <id> --exit-status` + assert the *downstream* run started. Lint alone is forbidden here. If unreproducible locally, register a **waiver** (see below) instead of a fake green. |
| Terraform / OpenTofu (config-authoring) | `tofu validate` then a deterministic plan assertion, e.g. `tofu plan -out=tfplan && tofu show -json tfplan \| jq -e '<assertion about resource_changes>'` |
| Kubernetes manifests | `kubeconform <f>` then `kubectl apply --dry-run=server -f <f>` |

If the real behavior can only be observed after merge (platform semantics, no sandbox), do NOT register a passing parse-check as the contract. Instead declare the contract's verification as the **post-merge observation command** and register a `ScheduleWakeup` to run it after merge, or surface a waiver to the user. A green parse check standing in for an unverified trigger change is exactly the oracle-downgrade the harness exists to prevent.

## How to verify

When you consider the task done:

```bash
~/.claude/harness/bin/verify
```

The script runs your contract's `verification_command`, captures the result back to `contract.json#/last_run`, and exits with the same code. If exit 0 and within the current-turn window, the gate allows Stop next time. If it fails, you fix the underlying issue or file a blocker bead documenting why you cannot — *documented failure is also an outcome*. Don't keep flailing.

## How to schedule resumption

If your work is genuinely waiting on something external (CI, merge queue, DAG run, an external agent), use the `ScheduleWakeup` tool. Don't write "I'll check back" as prose and end the turn — prose-as-polling is the largest measured stall class (30%) and is exactly what this gate exists to prevent.

### Task-mode gate + external-event wait: use ScheduleWakeup, not task pickup

When the task-mode gate blocks with `tasks_remain_in_queue` but your **session goal** is blocked on an external event (CI finishing, a merge completing, a scheduled dbt/DAG run, an external agent completing its work), the correct response is:

```
ScheduleWakeup(delaySeconds=<when the event will complete>, reason="<what you're waiting for>", prompt="<same loop prompt>")
```

Do **not** pick up unrelated ready tasks from `bd ready` to drain the queue and satisfy the gate. That is scope creep, not progress — you are doing work the user did not ask for in this session, and the session's actual outcome remains unverified.

The three release paths from a task-mode block are:
1. **Finish the actual session work** — drain the tasks that belong to this session's goal, verify the outcome.
2. **ScheduleWakeup** — register a future check-in for when the external blocker clears.
3. **User release** — the user says `stop` or `end here`.

Picking up unrelated backlog items is not a fourth path. If `bd ready` shows tasks outside the current session's scope, ignore them — they belong to a different session.

### Background-workflow watchdog (long runs die silently at the host timeout)

A background `Workflow` run is killed at the Claude Code host's task timeout (~13 min, observed 2026-05-29) with **no completion notification** — the parent is silently stranded mid-run. That timeout is a platform limit this repo cannot reconfigure; the mitigation is to make the death *observable* and *recoverable* instead of silent. When you launch a `Workflow` that may exceed ~13 min of wall-clock:

1. **Register a fallback wakeup for it.** `ScheduleWakeup(delaySeconds=<~run estimate + buffer>, reason="watchdog: workflow <runId>", prompt="<resume/check prompt>")`. Since the ScheduleWakeup→Stop-gate bridge now works (bead `escapement-0wg`), this both releases the Stop gate while you wait and re-invokes you when the timer fires.
2. **On re-invocation, classify the run mechanically — do NOT do manual `ps`/file-activity forensics:**
   ```bash
   python3 ~/.claude/harness/bin/workflow_status.py --run <runId>
   ```
   Exit 0 = `completed` (collect the result). Non-zero = actionable: `running` (re-arm the wakeup and wait longer), `no_signal` (silently died — resume), `ended_incomplete` (errored — inspect).
3. **Resume a dead run** with `Workflow({scriptPath, resumeFromRunId: "<runId>"})` — completed agents return from cache; only the killed/edited call onward re-runs. If a run dies repeatedly at the same boundary, decompose the script into smaller phases (each phase a separate background run) so no single run approaches the timeout.

The residual platform fix (the runtime emitting its own death signal / raising the timeout) is tracked outside this repo; the harness-side mitigation above turns silent stranding into a scheduled, mechanical re-check.

## Rule: outcome-bias

If you are not done and not scheduled to return, you are not stopping. Action without outcomes (more tool calls, more subagent dispatches, more bead-claims) does not substitute for proof of completion or proof of resumption. See `feedback/outcome-bias-over-action-bias` memory for the underlying principle.

## Completion target: ship it live

There is **no git completion ceiling**. Done means the outcome is live and verified
end-to-end — merged and deployed where the change actually runs — not "PR opened" or
"committed locally." A cap that stopped an agent below live delivery contradicted the
outcome-ownership rule (done = the real result is happening), so the ceiling machinery
(`ceiling_push_cap.py`, `repo-policy.json`, `set-repo-ceiling`) was removed. Drive work
all the way to a verified live outcome; if a step genuinely requires a human (a
credential, an irreversible external action), name the exact blocker and continue the
rest — do not treat "PR opened" as done.

### Per-repo outcome authorization — the durable authorization the base prompt defers to

The base Claude Code system prompt says: *confirm before hard-to-reverse or
outward-facing actions — unless durably authorized.* A repo's committed
`.escapement/repo.json` (the per-project options manifest) **is** that durable
authorization. Read it before deciding whether to merge (`harness/bin/repo_outcome.py`
resolves it):

- `intended_outcome` at or above `merged` **and** `auto_merge_on_green: true` →
  **you are pre-authorized.** When your change reaches green verification, **merge it
  and ship it live. Do NOT ask "want me to merge it now, or review the PR first?"** —
  that solicitation is the exact anti-pattern this authorization exists to remove. If
  the repo also declares a `deploy` surface, name it in your report ("now live at X")
  rather than ask about it.
- No declaration, malformed, or `auto_merge_on_green: false` → the conservative
  default (stop at `pr-opened`, may ask). Unchanged from today. Never assume
  authorization a repo did not grant.

**The "irreversible external action" carve-out does NOT cover a merge that triggers
auto-deploy.** That carve-out is for steps you genuinely *cannot* perform without a
human — typing a credential, clicking an external approval. A `gh pr merge` you have
the ability to run is not such a step; a repo that declared `merged-and-deployed`
authorized exactly that outcome. Merging-to-auto-deploy is the *point*, not a blocker
— do not stretch the carve-out to re-introduce the ask the declaration removed. The
one exception is a change matching the repo's declared `confirm_class` (a narrow,
per-repo danger list), which still draws one confirm.

## Status

This rule is paired with the continuation-harness (May 2026). Code installs to `~/.claude/harness/bin/` (deployed by `INSTALL.sh` from the repo's `harness/` source); runtime state lives in `~/.claude/harness/` and is keyed per session (`threads/{session_id}/`) so concurrent agents never clobber each other. The full spec lives in the repo at `openspec/changes/continuation-harness/`. Still v0.1+: full 57-stall regression test, the launchd waker that actually fires scheduled wakeups, bead-derived contracts, and the supervisor daemon.
