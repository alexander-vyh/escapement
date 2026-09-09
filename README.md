# Escapement

<!-- escapement:core-identity:start -->
**The control system for agentic delivery.**

> **Delegate outcomes. Get verified delivery.**

Escapement keeps bounded software outcomes moving across coding-agent sessions: from intent and authority through independent verification and authorized delivery. It is built first for operators running multiple coding-agent sessions on real repositories who want leverage without becoming the manual scheduler, reminder system, and final quality gate.

> Escapement converts available agent capacity plus delegated authority into verified, delivered outcomes while reserving human attention for consequential choices.

This repository is a snapshot of a working, opinionated system—not a universal product. Claims here are limited to behavior the current adapters and fixtures can prove.
<!-- escapement:core-identity:end -->

## The control loop in two minutes

```text
delegate → structure → execute → verify → deliver → learn
```

You delegate a bounded outcome and its constraints. Escapement makes the oracle and authority explicit, turns the work into an executable graph, allocates isolated capacity, keeps reversible work moving, challenges completion independently, follows the repository's delivery path, and records what the run taught.

The walkthrough shows how to invoke the existing control surfaces through a small CLI change. It is representative, not end-to-end proof; the evidence and limitation sections below show what has actually been observed.

[Open the representative product tour](docs/PRODUCT_TOUR.md)

## Evidence, not testimonials

Escapement's strongest proof is the repository's own delivery record—including cases where its controls disproved the plan or exposed a bad merge:

- an evidence audit invalidated a proposed goal gate and corrected contaminated measurements;
- isolated worktree creation removed a repository-wide capacity bottleneck, while the follow-up records that the first merge failed on Linux; and
- a captured Codex 0.153.4 Stop fixture overturned an obsolete host-limit assumption and shipped the supported part without claiming the unsupported rest.

[Inspect the evidence](docs/EVIDENCE.md)

## Start with the failure you have

| Failure mode | Escapement response |
|---|---|
| Agents declare victory at a green test | Define an independent outcome oracle, challenge it with bad implementations, then verify the final user-visible result. |
| Parallel sessions interfere or wait on one another | Allocate work explicitly and execute it in isolated worktrees with durable task state. |
| An agent finds a problem and stops at a summary | Continue reversible in-scope work, repair causal blockers, and reserve attention for a real consequential choice. |
| Finished work stalls at “what next?” | Resolve repository-declared landing authority and carry the branch through its normal delivery path. |
| Rules accumulate but nobody knows whether they help | Keep support claims fixture-backed, retain failure history, and remove machinery whose evidence does not justify it. |

Escapement is not a task app, autonomous product manager, or guarantee that every agent host exposes the same controls. It is the control layer around an existing coding-agent workflow.

## Supported hosts and truthful limits

Host-specific surfaces are rendered from authored sources under `agent-surfaces/` by `tools/render_agent_surfaces.py`. Generated `AGENTS.md`, `CLAUDE.md`, plugin metadata, and compatibility surfaces must not be edited directly.

| Surface | Claude Code | Codex |
|---|---|---|
| Instructions | `CLAUDE.md` | `AGENTS.md` |
| Installed hooks | Escapement Claude plugin | Escapement Codex plugin |
| Skills | Claude plugin skill tree | `.agents/skills/` and Codex plugin skills |
| Package metadata | Claude plugin manifest | Codex plugin manifest |

<!-- escapement:support-claims:start
merge-green-status=unsupported
merge-green-status-reason=The merge authorization hook resolves repository-declared merge authority but does not observe pull-request check or green status.
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
-->
<!-- escapement:support-claims:end -->

Today:

- merge authorization resolves repository policy but does not itself observe pull-request check status;
- `confirm_class` is stored but not enforced by the merge gate;
- deployment metadata is informational to the outcome resolver and does not itself execute or authorize a deployment command; and
- Codex has fixture-backed startup, tool-use, prompt, and Stop events, but scheduled wakeups, task-mode binding, and the local judge rung remain Claude-only.

Support in one host is never inferred from another host's lifecycle model.

## Install current adapters

The complete current workflow expects `openspec`, `bd`, `git`, `python3`, and `jq`. Install only the capability adapters you intend to use; `direnv` and Serena are optional.

### Codex

```bash
codex plugin marketplace add https://github.com/alexander-vyh/escapement
codex plugin add escapement@escapement
```

To update an existing checkout and effective plugin source:

```bash
git pull --ff-only
./scripts/codex-plugin-update.sh
```

The updater refuses to overwrite unrecognized user-authored skill content and verifies the installed source before reporting success.

### Claude Code

Inside Claude Code:

```text
/plugin marketplace add alexander-vyh/escapement
/plugin install escapement@escapement
```

Then refresh from a checkout:

```bash
mkdir -p "$HOME/src"
git clone https://github.com/alexander-vyh/escapement "$HOME/src/escapement"
cd "$HOME/src/escapement"
./scripts/plugin-update.sh
```

Restart Claude Code after an upgrade because an already-running process may retain an older versioned plugin root. `INSTALL.sh` is an optional compatibility installer for auxiliary assets; it is not the primary workflow installer.

## Architecture and operating doctrine

### Durable capability chain

These capabilities define Escapement independently of any current tool or client:

1. **Intent and authority**
2. **Design and specification**
3. **Executable dependency-aware work breakdown**
4. **Capacity allocation**
5. **Isolated execution**
6. **Action-local continuation and repair**
7. **Independent outcome verification**
8. **Authorized landing and delivery**
9. **Learning and feedback**

Design and work breakdown make intent, constraints, dependencies, and the independent oracle explicit enough to allocate capacity safely without repeatedly returning routine delivery decisions to the user.

### Current adapter mapping

<!-- escapement:adapter-mapping:start -->
| Durable capability | Current adapter |
|---|---|
| Design and specification | OpenSpec |
| Executable dependency-aware work breakdown | Beads |
| Isolated execution | Git worktrees |
| Capacity allocation | Claude Code, Codex |
| Authorized landing and delivery | GitHub |
<!-- escapement:adapter-mapping:end -->

The current mapping uses Beads for task state only. The supported isolated-creation transaction is `escapement-worktree create`; session context supplies its bundled path and scoped arguments. Replacing an adapter must not require changing the mission or capability chain.

### Delegated outcomes include their ordinary means

Delegating a bounded build, fix, change, or delivery includes the routine, proportionate actions needed to achieve and verify it inside the named repository and constraints: isolated edits, tests, builds, task-branch commits and pushes, pull requests, causal CI repair, and the repository-declared merge, deployment, and verification path.

Escapement requests attention when progress needs changed intent, a materially different valid outcome, an undelegated repository or audience, new privilege or credentials, destructive or irreversible shared effects, unsafe overlap with another owner, or a missing landing path. One unresolved choice blocks only its dependent action; independent authorized work continues.

### How the layers fit

Molecule formulas encode reusable work graphs. Skills explain procedures. Rules state policy. Hooks enforce only lifecycle events their host exposes. Tests and outcome verifiers check the result from independent evidence. Each layer can change while the capability contract remains stable.

| Area | Purpose |
|---|---|
| `agent-surfaces/` | Authored identity, onboarding, host evidence, and render manifest |
| `openspec/changes/` | Design, requirements, decisions, and change artifacts |
| `beads/formulas/` | Reusable task-graph templates |
| `claude/skills/`, `.agents/skills/` | Workflow procedures exposed to supported clients |
| `claude/rules/` | Operating policy |
| `claude/hooks/`, `harness/` | Fixture-backed enforcement and continuation machinery |
| `tools/render_agent_surfaces.py` | Generated-surface renderer and consistency validator |

See [docs/VOCABULARY.md](docs/VOCABULARY.md) for mechanics and [docs/NAMING.md](docs/NAMING.md) for why a clock escapement is the governing metaphor.

### Operating cautions

A gate earns its place only when a repeated or severe failure has a replayable oracle, valid work can pass, and a denial explains repair. Stored configuration and prose are not enforcement evidence. Authentication, permissions, per-project memory, and task databases remain user- or repository-owned state.

The bootstrap script runs in any Git repository by default. Constrain machine-wide bootstrap with a colon-separated allowlist when needed:

```bash
ESCAPEMENT_BOOTSTRAP_ROOTS="$HOME/src:$HOME/work"
```

## Credits

The current adapters build on [OpenSpec](https://github.com/Fission-AI/OpenSpec), [Beads](https://github.com/steveyegge/beads), Git, GitHub, and optional [Serena](https://github.com/oraios/serena). The operating doctrine draws from mission command, Grove's leverage, closed-loop control, Lean flow, constraint management, enabling bureaucracy, walking-skeleton development, and independent test-oracle practice.

## License

Escapement is licensed under the **GNU General Public License v3.0 or later** (`GPL-3.0-or-later`). See [`LICENSE`](LICENSE).
