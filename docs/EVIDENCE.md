# Escapement Evidence

These are inspectable repository incidents, not testimonials and not a benchmark. They show what the control loop changed, where its own evidence was wrong, and what remained unsupported. Pull-request records are the source of truth; the summaries below are navigation, not a substitute for them.

### PR #230 — Evidence corrected the plan

- **Record:** [Make the Stop gate evidence trustworthy and its contract gate reachable](https://github.com/alexander-vyh/escapement/pull/230)
- **Observed outcome:** An audit found that test fixtures contaminated the incident log and that a contract-verification branch was unreachable for scoped task sessions. The change isolated test state, added a leak guard with a positive control, and restored contract-gate reachability before any stricter goal policy was attempted.
- **Counterevidence / remaining limit:** The planned goal requirement was not shipped. The evidence refuted that plan's premise, so this pull request repaired measurement and execution reachability first.

### PR #234 — Verification history made oracle bite measurable

- **Record:** [Record verify-run history](https://github.com/alexander-vyh/escapement/pull/234)
- **Observed outcome:** The previous `last_run` field erased fail-then-pass history and made the apparent green rate tautological. A bounded rolling run history now preserves recent failures while the latest run continues to drive the Stop decision.
- **Counterevidence / remaining limit:** Historical records still conflate “verification ran red” with “verification had not run yet.” The new history improves prospective evidence; it does not reconstruct missing past events.

### PR #220 — Parallel worktree creation removed a lock bottleneck

- **Record:** [Release the repository lock during worktree bootstrap](https://github.com/alexander-vyh/escapement/pull/220)
- **Observed outcome:** A public CLI check showed a second worktree reaching its own bootstrap while the first bootstrap remained blocked. Durable receipts, exact ownership, and guarded recovery preserved isolation rather than trading throughput for unsafe cleanup.
- **Counterevidence / remaining limit:** The Linux/ext4 CI suite failed after merge. The macOS result and local controls were insufficient to claim a portable green delivery on their own.

### PR #221 — The failed merge became an oracle repair

- **Record:** [Retain replacement inode controls](https://github.com/alexander-vyh/escapement/pull/221)
- **Observed outcome:** The follow-up made filesystem replacement controls deterministic on both macOS and Linux/ext4, then passed the focused transaction suite and CI.
- **Counterevidence / remaining limit:** Production behavior was unchanged. This was a test-oracle correction required to make the earlier safety claim portable, not a second runtime feature.

### PR #226 — Current host behavior replaced an obsolete assumption

- **Record:** [Land the Codex Stop gate on the plugin surface](https://github.com/alexander-vyh/escapement/pull/226)
- **Observed outcome:** A captured Codex 0.153.4 `Stop` payload proved that the host emitted that lifecycle event and honored its block decision. The shipped adapter delegates decisions to the shared core, while separate fixture-shaped `UserPromptSubmit` tests prove recorder behavior without claiming a live capture of that event.
- **Counterevidence / remaining limit:** Codex still has no scheduled wakeup, task-mode repository binding, or local judge rung. A session that has genuinely ended is not re-entered.

## What this evidence supports

The records support a narrower and more useful claim than “agents become autonomous”: Escapement can make authority explicit, isolate capacity, reject weak completion evidence, keep supported in-session work moving, and carry an authorized result through delivery while making failures inspectable.

They do not prove universal host parity, automatic deployment, perfect code-touch detection, or outcome quality independent of the oracle. Those limits remain visible in the [README capability table](../README.md#supported-hosts-and-truthful-limits).
