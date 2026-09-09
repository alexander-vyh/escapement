# Escapement Product Tour

This is a representative walkthrough of behavior already present in the repository. It is not a captured transcript, benchmark, or promise that every host automates every part of the loop.

The example is deliberately ordinary: add `--json` output to a small CLI while preserving its default text output. The feature is hypothetical; the control loop is the product.

## Try it after installation

Start a fresh Claude Code or Codex session in a repository where the current capability adapters are available. There is no separate Escapement command shell. Give the agent this bounded outcome:

> Add machine-readable JSON output to the status command while preserving its default text output. Use the repository's existing conventions and delivery path. Verify both interfaces from the public CLI, then ship the result unless a consequential choice is required.

The host instructions and lifecycle hooks supply the control layer around that ordinary prompt. During a non-trivial run, expect inspectable repository state rather than a new UI:

- a Test Oracle Brief under `.agent/runtime/test-oracle-briefs/` before implementation;
- durable work state in `bd` when the repository uses it;
- the session-injected `escapement-worktree create` transaction when isolation is needed;
- behavioral controls and an independent mutation challenge before implementation; and
- a feature branch and pull request carried through the repository's declared delivery path.

Availability is host- and repository-dependent. The [support table](../README.md#supported-hosts-and-truthful-limits) is the authority for what is mechanically enforced today.

## 1. Delegate the outcome

The operator delegates an observable result:

> Add machine-readable JSON output. Keep the default human-readable output compatible. Ship it through this repository's normal pull-request and release path.

That outcome already authorizes routine work inside the repository: inspect, isolate, edit, test, review, push, open the pull request, repair causal failures, and follow the declared landing path. It does not authorize changing the default format, publishing to a new audience, requesting a new credential, or accepting a destructive migration. Those are consequential choices.

## 2. Structure the work

Before implementation, the work records four things:

- **Outcome:** callers can request JSON without breaking existing text consumers.
- **Independent source of truth:** the public CLI contract and observed process output, not a private formatting helper.
- **Constraints:** current language and CLI conventions, compatibility, security, and repository ownership rules.
- **Controls:** a positive control proves valid JSON is emitted; a negative control proves default text is unchanged; an invalid implementation such as changing the default must fail.

For larger outcomes, design artifacts become a dependency-aware work graph. For a small change, the same reasoning can stay compact. The amount of ceremony scales; the invariant does not.

## 3. Execute in isolation

Escapement allocates the change to an isolated worktree and durable task state. Another coding-agent session can work on a separate outcome without sharing uncommitted files or treating the same queue item as its own.

If implementation exposes a causal defect inside the delegated scope, the agent repairs it and continues. An adjacent opportunity is recorded without silently expanding the outcome.

## 4. Verify independently

The first tests are written from the public contract and observed output. A mutation challenger asks whether plausible bad versions would still pass—for example, hardcoding the example JSON, deleting the default-output path, or asserting only that an internal serializer was called.

When the implementation is complete, an outcome verifier runs the CLI as a user would:

```text
tool status          → existing text output remains usable
tool status --json   → valid JSON with the required semantic fields
tool status --bogus  → the documented error behavior remains intact
```

A green unit test is evidence, but it does not substitute for this final behavior.

## 5. Deliver within authority

The task branch is pushed and a pull request is opened. The repository's CI system determines check status. Escapement resolves the repository's declared landing policy, but its merge authorization hook does not itself observe whether those checks are green.

After merge, repository deployment metadata tells the agent what delivery context exists. That metadata is informational; it does not run a release command by itself. The already-delegated delivery authority is what permits the agent to follow the repository's normal refresh or deployment path and verify the installed result.

If the repository has no declared landing path, or delivery needs a new credential or irreversible shared action, the operator gets the decision. Routine delivery does not become another confirmation round.

## 6. Learn from the run

The verification history and gate decisions make a later question answerable: did the oracle catch bad work, did the workflow create delay without value, and which constraint actually limited delivery?

Learning changes the next control only when evidence justifies it. A recurring severe miss with a replayable oracle may earn a gate. A rule that adds friction without changing outcomes is a candidate for removal.

## What the operator experiences

The visible product is not a dashboard. It is the difference between supervising agent activity and delegating a result: fewer status prompts, fewer repeated permissions for ordinary work, explicit escalation when the choice is genuinely consequential, and inspectable evidence at delivery.

For real repository runs—including counterevidence—see [Evidence](EVIDENCE.md). For current host gaps, return to [Supported hosts and truthful limits](../README.md#supported-hosts-and-truthful-limits).
