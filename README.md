# Escapement

Escapement is an agentic workflow system built **on top of [OpenSpec](https://github.com/Fission-AI/OpenSpec)**, adding:

- **Adversarial overlays** on OpenSpec's discovery step (riskiest-assumption, pre-mortem, red/blue team, walking-skeleton sections injected as internal prompts — not visible in the output docs).
- **A bridge to [Beads](https://github.com/steveyegge/beads)** so OpenSpec's `tasks.md` becomes a real task graph (`bd create --spec-id ...`) that agents can execute against.
- **A molecule formula** (`mol-feature`) that orchestrates the full brainstorm → discovery → skeleton → build → retro lifecycle with two human gates.
- **Hooks, rules, and skills** that enforce the workflow at the tool-call level: TDD-first, named-agent teams, outcome-verification, OpenSpec init checks, spec-ID linkage, never-suppress discipline, Serena-first navigation. Claude Code is the primary adapter; **Codex is a supported host** via a generated `AGENTS.md`, project hooks in `.codex/hooks.json`, and skills in `.agents/skills` (see [Hosts](#hosts-claude-code-and-codex)).

**This does not replace OpenSpec — it uses it.** The `/discovery` skill calls `openspec init`, `openspec instructions`, and `openspec status` under the hood. The `proposal.md` / `design.md` / `specs/*.md` files written are standard OpenSpec artifacts. Engineers comfortable with bare OpenSpec can read the changes a teammate produced through this workflow with no extra context.

> ⚠️ This is a snapshot of one working setup, not a product. Read, adapt, cherry-pick. The opinions are strong.

## Why "Escapement"?

`Escapement` is named for the clock mechanism that turns stored energy into measured motion. It restrains runaway movement, gives the oscillator enough impulse to continue, and advances the train one tick at a time. This repo applies that model to agentic work: OpenSpec, Beads, hooks, test oracles, verification, and wakeups convert model effort into controlled, outcome-verified progress.

See [docs/NAMING.md](docs/NAMING.md) for the naming rationale and collision notes.

---

## What you get

### The core pattern

```
you say "build X"
        │
        ▼
┌───────────────────────────┐
│ mol-feature (beads)       │  root epic + 9 step tasks (2 are gates)
└──────────┬────────────────┘
           │ step: discovery
           ▼
┌───────────────────────────┐
│ /discovery skill          │  adversarial overlay on OpenSpec CLI
│   └─ writes ──────────────┼──▶ openspec/changes/{name}/
│                           │     ├─ proposal.md   ← standard OpenSpec
│                           │     ├─ design.md     ← + adversarial sections
│                           │     ├─ specs/*.md    ← requirement IDs
│                           │     └─ tasks.md
└──────────┬────────────────┘
           │ step: work-breakdown
           ▼
┌───────────────────────────┐
│ /work-breakdown skill     │  reads openspec, writes beads
│   └─ creates ─────────────┼──▶ bd spec issues (--acceptance fields)
│                           │    bd task issues (--spec-id links)
└──────────┬────────────────┘
           │ step: execute-skeleton → review → execute-full
           ▼
       parallel named agents implement tasks,
       reading --acceptance via --spec-id
```

### Layers (adopt one, some, or all)

| Layer | Files | What it buys you |
|------|------|------------------|
| **1. Formulas** | `beads/formulas/*.json` | 10-step workflow definition for `bd mol pour` |
| **2. Skills** | `claude/skills/*/` | The "how" for each step — discovery, work-breakdown, execution, oracle review |
| **3. Commands** | `claude/commands/*.md` | Slash-command shims (`/discovery`, `/work-breakdown`, `/brainstorm`, `/review`) |
| **4. Rules** | `claude/rules/*.md` | Global discipline — TDD, agent teams, outcome ownership, never-suppress, Serena-first |
| **5. Hooks** | `claude/hooks/*.py` | Tool-call-level enforcement (see below) |
| **6. Bootstrap** | `scripts/project-bootstrap.sh` | SessionStart hook auto-inits openspec/beads/serena per repo |

Each layer adds value without requiring the ones above. You can install just the skills, or skills + formulas without hooks. Start small.

---

## Hosts: Claude Code and Codex

Escapement is **host-neutral at the core** — beads, OpenSpec, test-oracle discipline, and outcome verification don't depend on which agent runs them. The host-specific surfaces are *generated* from one neutral manifest (`agent-surfaces/manifest.json`) by `tools/render_agent_surfaces.py`, and a `--check` mode fails CI if they drift, so the two hosts stay in sync:

| Surface | Claude Code | Codex |
|---------|-------------|-------|
| Instructions | `CLAUDE.md` | `AGENTS.md` *(generated)* |
| Project hooks | `claude/settings.template.json` → `~/.claude/` | `.codex/hooks.json` *(generated)* |
| Skills | `claude/skills/` | `.agents/skills/` |
| Plugin packaging | `.claude-plugin/plugin.json` | `plugins/escapement/.codex-plugin/` *(generated)* |

The portable core runs on both: beads context loading (`bd prime`) and the TDD / oracle / outcome gates (Test Oracle Brief, discovery, spec-ID, implementation-echo, oracle-downgrade, outcome-assertion) are wired into `.codex/hooks.json` and **fixture-tested against Codex's payload shape**.

**Claude Code is the richer adapter today.** Per the `agent-surface-parity` spec, Claude-only features — multi-agent `TeamCreate` teams and `ScheduleWakeup` continuation — are *excluded* from Codex surfaces rather than faked: a Codex hook is marked blocking only when a fixture proves it works against the current Codex payload. New shared behavior is added to the manifest first, then rendered to whichever host surface can actually enforce it.

---

## Prerequisites

| Tool | Install | Verify |
|------|---------|--------|
| `openspec` | `brew install openspec` (or `npm i -g @fission-ai/openspec`) | `openspec --version` |
| `bd` (beads) | [github.com/steveyegge/beads](https://github.com/steveyegge/beads) | `bd --version` |
| `direnv` | `brew install direnv` | `direnv version` |
| `python3` | usually present | `python3 --version` (3.9+) |
| `jq` | `brew install jq` | `jq --version` |
| `git`, `bash` | usually present | — |

Claude Code or Codex must be installed and working. The `Install` steps below are Claude Code's machine-wide setup; Codex instead reads the repo-relative surfaces committed in the project (`AGENTS.md`, `.codex/hooks.json`, `.agents/skills`), so it needs no symlink install. [Serena MCP](https://github.com/oraios/serena) is optional but the navigation hooks are silent unless `.serena/memories` exists in a project.

---

## Install

```bash
git clone https://github.com/alexander-vyh/escapement ~/GitHub/escapement
cd ~/GitHub/escapement
./INSTALL.sh
```

`INSTALL.sh` creates **symlinks** from `~/.claude/` and `~/.beads/` into a **pinned checkout** of this repo (`~/.claude/.escapement-pinned`, tracking `main`) — *not* your live working tree. This is deliberate: `~/.claude` is machine-wide, so if it symlinked your working tree, a branch switch or mid-edit here could break hooks in **every** repo at once. With the pinned checkout, your day-to-day git work in this repo never disturbs your live config. Existing files are moved to `<file>.backup-<timestamp>` before being replaced — nothing is silently overwritten.

Because the deploy is pinned, edits go live in two steps: land them on `main`, then run `./INSTALL.sh --update` (fast-forwards the pinned checkout). Prefer instant edits-from-working-tree (accepting the branch-fragility)? Install with `./INSTALL.sh --dev`.

### Settings merge (you do this by hand)

Your `~/.claude/settings.json` likely exists and contains your personal permissions and auth config. The installer does NOT overwrite it.

Open `claude/settings.template.json` and merge the `hooks` block into your existing `~/.claude/settings.json`. Or if you have no existing settings, copy the template as a starting point:

```bash
cp claude/settings.template.json ~/.claude/settings.json
# then add your permissions.allow list, apiKeyHelper, etc.
```

---

## First run

After installing and merging settings:

1. Open Claude Code in a fresh git repo under `~/GitHub/` (the bootstrap script is gated on that path — edit `scripts/project-bootstrap.sh:24-27` to widen).
2. On SessionStart, the bootstrap script runs (idempotent, fail-open):
   - `direnv allow` on any `.envrc`
   - `openspec init --tools claude` if `openspec/` is missing
   - `bd init --prefix <repo-name>` if `.beads/` is missing
   - Prompts for Serena onboarding (interactive)
3. Say: *"let's build a small feature to validate the setup — add a /status slash command"*
4. Claude should respond by pouring `mol-feature` and walking you through: brainstorm → discovery → review → breakdown → skeleton → build → retro.

If that flow happens end-to-end, everything is wired correctly.

---

## Anatomy

### The molecule formula (`beads/formulas/mol-feature.formula.json`)

Nine steps, two human gates, four phases (Design / Validate / Build / Learn):

```
brainstorm ──▶ discovery ──▶ [GATE: review-discovery] ──▶ work-breakdown
                                                                │
                                                                ▼
                              execute-skeleton ──▶ [GATE: review-skeleton]
                                                                │
                                                                ▼
                              execute-full ──▶ ceremony-retro ──▶ outcome-check
```

Each step's `description` tells Claude what to do — often "run /discovery" or "dispatch named agents via TeamCreate". The formula is the script; the skills are the subroutines.

### The skills

```
build                              ← front-door router; pours the right molecule
  └─ brainstorming                 ← "should we build this at all?" pre-filter
       └─ discovery                ← adversarial wrapper on openspec CLI
            └─ work-breakdown      ← openspec → beads spec+task issues
                 └─ beads-execution  ← dispatches agents for bd ready
                      ├─ behavioral-test-oracle-review  ← brief before each code change
                      ├─ dispatching-parallel-agents
                      └─ subagent-driven-development
```

### The hooks (what the rules can't enforce alone)

Grouped by what they protect:

**OpenSpec workflow**
- `openspec_init_guard.py` — blocks `openspec` commands when `openspec/` doesn't exist
- `design_doc_location_guard.py` — warns when design docs go to `docs/plans/` instead of `openspec/changes/`
- `discovery-gate.py` — blocks `bd create` of features/epics without a design doc
- `discovery-nudge.py` — nudges `/discovery` when a prompt looks like feature work
- `discovery-close-gate.py` — on `bd close`, surfaces proof-of-delivery + anti-metrics
- `spec_id_enforcement.py` — blocks `bd create --type task` under `mol-feature` without `--spec-id`
- `mol_status_check.py` — SessionStart, surfaces active molecules

**TDD + test oracle discipline**
- `tdd-gate.py` — requires test file modification before implementation
- `test_oracle_brief_gate.py` — requires `.agent/runtime/test-oracle-brief.md` for behavioral code changes
- `test_reminder.py` — PostToolUse nudge to run tests after edits
- `implementation_echo_test_gate.py` — rejects tests that echo the implementation
- `oracle_downgrade_warning_gate.py` — warns on test-oracle weakening in diffs
- `outcome_assertion_gate.py` — on `gh pr create`, blocks tests with only structural assertions

**Outcome verification + shirking**
- `validate_no_shirking.py` — blocks "pre-existing failure" evasion at commit/PR/Stop
- `ceiling_push_cap.py` — enforces a repo's git completion ceiling (`.claude/repo-policy.json`: `local`|`pr`|`merge`); blocks `git push` in a `local` repo (waiver: `CEILING_WAIVER=`). Set it with `set-repo-ceiling set <tier>`
- `review_gate.py` — soft gate on `bd close` if no review agent was dispatched
- `review_nudge.py` — UserPromptSubmit, nudges `/review` on review-intent prompts

**Agent discipline**
- `enforce_named_agents.py` — blocks anonymous agents and multi-agent dispatch without `TeamCreate`
- `context_burn_detector.py` — nudges agent dispatch after excessive inline research
- `session_cleanup.py` — SessionStart, cleans /tmp state from the above

**Serena navigation discipline** (silent unless `.serena/memories` exists)
- `serena_preference_gate.py` — blocks full-file Read on code when Serena is available
- `serena_preference_injection.py` — UserPromptSubmit, steers toward Serena symbol tools
- `serena_onboarding_check.sh` — SessionStart, nudges Serena onboarding when missing

Each hook's docstring at the top of the file is authoritative — read it before editing.

---

## ⚠️ Warnings

### This is opinionated

The `rules/` directory encodes strong opinions:

- **`planning-discipline.md`** — `mol-feature` on any non-trivial work
- **`tdd-enforcement.md`** — failing test FIRST in any test-capable repo
- **`agent-teams-default.md`** — `TeamCreate` + named agents for anything multi-step
- **`outcome-ownership.md`** — done = verified end-to-end, not "my change compiles"
- **`molecule-awareness.md`** — surface active molecules on every session start
- **`beads-worktree-integration.md`** — `bd worktree create` instead of `git worktree add`
- **`never-suppress.md`** — no `# noqa`, no `--no-verify`, no test downgrades — fix the underlying issue
- **`serena-first.md`** — symbol tools over full-file Read when Serena is onboarded

Read the rules BEFORE installing. Edit to match your philosophy. These are not universally applicable — the TDD and never-suppress rules in particular will feel restrictive if your project has no test infrastructure or relies on legacy suppression patterns.

### Hooks are load-bearing

Skills produce guidance. Hooks produce enforcement. If you install skills without hooks, Claude can and will drift from the workflow. If you install hooks without skills, the hooks will block things without offering a path forward.

Install both, or neither.

### Path assumptions

The bootstrap script (`scripts/project-bootstrap.sh:24-27`) is gated on `~/GitHub/*`. If your repos live elsewhere, edit that case statement or parameterize it.

Some rules reference `~/GitHub/` paths directly — `grep -r '~/GitHub' claude/rules/` before installing if you're particular about that.

### Not shared

Deliberately excluded from this bundle:
- `~/.claude/settings.json` (personal auth + permissions) — only the `hooks` block is templated
- `~/.claude/projects/*/memory/` (per-project memory)
- General-utility hooks unrelated to the workflow (statusline, transcript backup, IDE wrappers, context injection)
- `~/.beads/` databases

---

## Uninstall

```bash
./INSTALL.sh --uninstall
```

Removes all symlinks. Your `.backup-<timestamp>` files are left alone — rename them back manually to restore your previous config.

---

## Credits

The substance comes from elsewhere; this repo is the glue.

- **[OpenSpec](https://github.com/Fission-AI/OpenSpec)** — the structured change-management framework this workflow runs on top of. The discovery skill is an opinionated wrapper, not a replacement.
- **[Beads](https://github.com/steveyegge/beads)** — graph-based task tracker designed for AI agents, with molecule formulas as a workflow templating layer.
- **[Serena](https://github.com/oraios/serena)** — LSP-backed semantic code navigation; the Serena rule + hooks make it the default during the build phase.
- **Walking-skeleton thinking** (Steven Gong et al.) — riskiest assumption first, 1–3 tasks, 30–60 min each.
- **Manager Tools, Radical Candor, Playing to Win, Lencioni, Grove, Brené Brown** — the rules' flavor on outcome ownership, feedback, and psychological safety.

The glue — molecule formulas, skill overlays, hook enforcement, settings template — is my own iteration, not a product. Expect to modify before adopting.
