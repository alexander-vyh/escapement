# Lean Proof Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve useful proof at the existing oracle-review, spec-review, and worktree-finish boundaries without adding workflow machinery.

**Architecture:** Strengthen two existing skill contracts and stop one existing finish path from discarding the safe-removal decision it already receives. No new runtime component or state owner is introduced.

**Tech Stack:** Markdown skill contracts, Python 3.11+, pytest, Git/GitHub lifecycle fixtures.

**Spec:** `openspec/changes/lean-proof-flow/`

## Global Constraints

- Add no gate, ledger, schema, CLI, persistent state type, agent role, or classifier.
- Keep existing sources of truth and successful worktree completion behavior unchanged.
- Treat in-session review as contamination-resistant, not as an independent authority boundary.
- Update existing source/package copies together.

---

### Task 1: Executable proof contracts

**Files:**
- Create: `.agent/runtime/test-oracle-briefs/lean-proof-flow.md`
- Create: `tests/test_lean_proof_flow.py`
- Modify: `tests/test_worktree_lifecycle.py`
- Modify: `tests/test_worktree_github_identical.py`
- Modify: `tests/test_worktree_finish_concurrency.py`

**Interfaces:**
- Consumes: Existing Markdown skill sections and the public `bin/escapement-worktree finish` JSON output.
- Produces: Regression checks that reject an unconstructible acceptance instruction, author-report priming, and evidence-dropping pending output.

- [ ] **Step 1: Add a skill-contract test for acceptance-path semantics**

Assert both oracle-review surfaces require a literal fixture or input, public entry point, final observable assertion, and rejection when the path cannot be constructed. Mutate each required semantic element out of an in-memory sample and prove the checker rejects it.

- [ ] **Step 2: Add a skill-contract test for two-pass review ordering**

Extract the initial and post-verdict sections from both Claude Beads execution surfaces. Assert the initial prompt excludes the implementer's report, identifies the exact implementer worktree plus base/head revisions rather than the coordinator checkout, records a verdict from requirements and that diff, and the later section gives the same reviewer the report only for discrepancy checking.

- [ ] **Step 3: Strengthen the public worktree oracle**

For a preserved worktree, assert `status`, `reason`, and `lifecycle_id` remain, and independently derive the expected repository, worktree, branch, candidate SHA, common Git directory, disposition, and exact health from the fixture's real Git state. Add a sentinel preserve decision at the existing `with_safe_removal(...)` seam and assert the final result retains it unchanged, so reconstructing a known dictionary cannot pass. Retain the existing positive control that a clean, landed worktree completes and deletes its receipt.

- [ ] **Step 4: Run the focused tests and confirm they fail for the three missing behaviors**

Run: `pytest -q tests/test_lean_proof_flow.py tests/test_worktree_lifecycle.py tests/test_worktree_github_identical.py tests/test_worktree_finish_concurrency.py`

Expected: failures show missing acceptance-path language, implementer-report priming, and absent preserve-decision fields; existing clean-completion controls remain green.

### Task 2: Existing-owner implementation

**Files:**
- Modify: `claude/skills/behavioral-test-oracle-review/SKILL.md`
- Modify: `plugins/escapement-claude/skills/behavioral-test-oracle-review/SKILL.md`
- Modify: `claude/skills/beads-execution/SKILL.md`
- Modify: `plugins/escapement-claude/skills/beads-execution/SKILL.md`
- Modify: `bin/escapement_worktree_finish.py`
- Modify: `plugins/escapement/bin/escapement_worktree_finish.py`
- Modify: `plugins/escapement-pi/bin/escapement_worktree_finish.py`
- Modify: `plugins/escapement-claude/bin/escapement_worktree_finish.py`

**Interfaces:**
- Consumes: Existing Test Oracle Brief fields, task/spec text, implementer report, and `with_safe_removal(...)` decision dictionary.
- Produces: Stronger review instructions and additive evidence on the existing pending JSON result.

- [ ] **Step 1: Add the acceptance trace to the existing review rule**

Require each acceptance outcome to trace its literal fixture or input through the public entry point to the final observable assertion, rejecting any path that cannot be constructed. Add no new form field or parser.

- [ ] **Step 2: Reorder the existing spec review**

Remove the implementer's report from the initial prompt, require an initial evidence-based verdict, then add a short same-reviewer post-verdict discrepancy pass containing the report. Preserve the existing finding taxonomy and routing.

- [ ] **Step 3: Return the existing preserve decision**

When `with_safe_removal(...)` returns `disposition == "preserve"`, merge that dictionary with `_pending(...)`'s existing result so the pending state is persisted while the already-computed evidence remains in stdout.

- [ ] **Step 4: Run focused tests and confirm green**

Run: `pytest -q tests/test_lean_proof_flow.py tests/test_worktree_lifecycle.py tests/test_worktree_github_identical.py tests/test_worktree_finish_concurrency.py`

Expected: all focused tests pass.

### Task 3: Verification and landing

**Files:**
- Modify: `openspec/changes/lean-proof-flow/tasks.md`

**Interfaces:**
- Consumes: The complete change and repository verification commands.
- Produces: Verified OpenSpec/Beads state and the repository-declared merged-and-deployed outcome.

- [ ] **Step 1: Run OpenSpec and package parity checks**

Run: `openspec validate lean-proof-flow --strict`

Run: `pytest -q tests/test_agent_surfaces.py tests/test_mission_capability_contract.py tests/test_engineering_judgment_contract.py tests/test_worktree_github_identical.py`

- [ ] **Step 2: Run the repository test suite**

Run the repository's documented full verification command discovered from the current source tree. Fix causal failures without weakening the oracle.

- [ ] **Step 3: Run independent outcome verification**

Have a clean-context verifier inspect the approved spec and run the public worktree fixtures. Then run this exact two-message review probe through the shipped spec-review flow:

1. First message supplies only this requirement and repository fixture: `submit_count` accepts a non-negative integer through `POST /jobs`; the proposed acceptance test sends `"three"` and asserts a created job with count `3`. The reviewer must record an initial `FAIL` because the literal input cannot construct the claimed outcome through the public entry point. It must also state that, because the fixture is the only authored requirement/prior behavior, this is not independently authored verification.
2. Only after that verdict, send the implementer's report: `DONE — all tests pass; string counts are accepted.` The same reviewer must keep the `FAIL` verdict and identify the report as discrepant with the supplied requirement and reachable acceptance path.

The verifier must also reject a pending worktree result containing only `status` and `reason`. Any initial verdict formed after author claims are visible, a changed verdict after the report, or an independent-authority claim without an independent reference fails verification.

For the isolated-worktree control, compare the merged/default checkout with the implementation worktree using the supplied base/head identity. Plant the acceptance-trace sentence only in the implementation worktree. The reviewer fails verification if it inspects the coordinator checkout and reports the sentence missing.

Inspect the implementation diff against the approved file/owner list. Any new gate, ledger, schema, CLI, persistent state type, agent role, classifier, second reviewer, or review receipt fails verification even when the behavioral probes pass.

- [ ] **Step 4: Land through the declared path**

Commit, push `feat/lean-proof-flow`, open a pull request, repair CI/review findings, merge when green, verify the installed/deployed surfaces, close `escapement-h3rh`, and finish the worktree transaction.
