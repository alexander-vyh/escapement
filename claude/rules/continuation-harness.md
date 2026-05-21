# continuation-harness — outcome-or-resumption gate (live)

A new deterministic Stop gate runs alongside `validate_no_shirking.py`. Both can block; they are additive. The harness gate enforces **outcome-bias over action-bias**: stopping is forbidden unless you've demonstrated completion, scheduled your own resumption, or been explicitly released by the user.

## The three Stop-permission paths

You may Stop iff one of these is true:

1. **Verification passed this turn.** You ran `~/GitHub/claude-workflow-setup/harness/bin/verify`, it exited 0, and the run happened within the last 5 minutes.
2. **Wakeup registered.** You called `ScheduleWakeup` for a future-dated check-in. The wakeup entry exists in `harness/threads/current/scheduled.json`.
3. **User released.** The user typed `stop`, `end here`, `done for now`, `that's enough`, `we're done`, `halt`, etc.

If none of these holds, Stop is blocked with a constructive resumption prompt. The block is *noise, not work-halting* — your turn ends, the user sees the prompt, and the conversation continues. But repeated blocks on the same turn waste tokens and user attention.

## How to declare a contract

Before your first implementation tool call on any non-trivial task, scaffold a contract:

```bash
python3 ~/GitHub/claude-workflow-setup/harness/bin/init_contract.py \
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
~/GitHub/claude-workflow-setup/harness/bin/verify
```

The script runs your contract's `verification_command`, captures the result back to `contract.json#/last_run`, and exits with the same code. If exit 0 and within the current-turn window, the gate allows Stop next time. If it fails, you fix the underlying issue or file a blocker bead documenting why you cannot — *documented failure is also an outcome*. Don't keep flailing.

## How to schedule resumption

If your work is genuinely waiting on something external (CI, merge queue, DAG run, an external agent), use the `ScheduleWakeup` tool. Don't write "I'll check back" as prose and end the turn — prose-as-polling is the largest measured stall class (30%) and is exactly what this gate exists to prevent.

## Rule: outcome-bias

If you are not done and not scheduled to return, you are not stopping. Action without outcomes (more tool calls, more subagent dispatches, more bead-claims) does not substitute for proof of completion or proof of resumption. See `feedback/outcome-bias-over-action-bias` memory for the underlying principle.

## Status

This rule is paired with the v0 deployment of the continuation-harness, May 2026. The full spec lives at `~/GitHub/claude-workflow-setup/openspec/changes/continuation-harness/`. v0 scope is a single active thread (`harness/threads/current/`); multi-agent state isolation, full 57-stall regression test, the launchd waker that actually fires scheduled wakeups, bead-derived contracts, and the supervisor daemon are v0.1+.
