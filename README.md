# Claude Workflow Setup

An opinionated Claude Code workflow that wires together **OpenSpec** (design docs),
**Beads** (task graph), and a **molecule formula** that orchestrates the full
brainstorm → design → skeleton → build → retro lifecycle.

This is a snapshot of one working setup. It is not a product, not maintained for
general consumption, and not universally applicable. Read, adapt, cherry-pick.

---

## What you get

### The core pattern

```
you say "build X"
        │
        ▼
┌───────────────────────────┐
│ mol-feature (beads)       │  root epic + 10 step tasks + gates
└──────────┬────────────────┘
           │ step: discovery
           ▼
┌───────────────────────────┐
│ /discovery skill          │  adversarial overlay on OpenSpec CLI
│   └─ writes ──────────────┼──▶ openspec/changes/{name}/
│                           │     ├─ proposal.md
│                           │     ├─ design.md
│                           │     ├─ specs/*.md  (requirement IDs)
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
| **2. Skills** | `claude/skills/*/` | The "how" for each step — discovery, work-breakdown, execution |
| **3. Commands** | `claude/commands/*.md` | Slash-command shims (`/discovery`, `/work-breakdown`, etc.) |
| **4. Rules** | `claude/rules/*.md` | Global instructions — TDD, agent teams, outcome ownership |
| **5. Hooks** | `claude/hooks/*.py` | Enforcement (spec_id, openspec init, discovery gates) |
| **6. Bootstrap** | `scripts/project-bootstrap.sh` | SessionStart hook auto-inits openspec/beads in new repos |

Each layer adds value without requiring the ones above it. You can install just
the skills. You can install skills + formulas but skip hooks. You can install
everything. Start small.

---

## Prerequisites

| Tool | Install | Verify |
|------|---------|--------|
| `openspec` | `brew install openspec` | `openspec --version` |
| `bd` (beads) | [github.com/steveyegge/beads](https://github.com/steveyegge/beads) | `bd --version` (tested against v0.49.0) |
| `direnv` | `brew install direnv` | `direnv version` |
| `python3` | usually present | `python3 --version` (3.9+) |
| `jq` | `brew install jq` | `jq --version` |
| `git`, `bash` | usually present | — |

Claude Code itself must be installed and working.

---

## Install

```bash
git clone <this-repo> ~/GitHub/claude-workflow-setup
cd ~/GitHub/claude-workflow-setup
./INSTALL.sh
```

`INSTALL.sh` creates **symlinks** from `~/.claude/` and `~/.beads/` into this
repo — so `git pull` in this repo updates your live config.

Existing files are moved to `<file>.backup-<timestamp>` before being replaced.
Nothing is silently overwritten.

### Settings merge (you do this by hand)

Your `~/.claude/settings.json` probably exists and contains your personal
permissions and auth config. The installer does NOT overwrite it.

Instead, open `claude/settings.template.json` and manually merge the `hooks`
and `env` blocks into your existing `~/.claude/settings.json`. Or if you have
no existing settings, copy the template as a starting point:

```bash
cp claude/settings.template.json ~/.claude/settings.json
# then add your permissions.allow list, apiKeyHelper, etc.
```

---

## First run

After installing and merging settings:

1. Open Claude Code in a fresh git repo under `~/GitHub/` (the bootstrap script
   is gated on that path — edit `scripts/project-bootstrap.sh:24-27` to widen).
2. On SessionStart, the bootstrap script runs:
   - `direnv allow` on any `.envrc`
   - `openspec init --tools claude` if `openspec/` is missing
   - `bd init --prefix <repo-name>` if `.beads/` is missing
   - Prompts for serena onboarding (interactive)
3. Say: *"let's build a small feature to validate the setup — add a /status
   slash command"*
4. Claude should respond by pouring `mol-feature` and walking you through:
   brainstorm → discovery → review → breakdown → skeleton → build → retro.

If that flow happens end-to-end, everything is wired correctly.

---

## Anatomy

### The molecule formula (`beads/formulas/mol-feature.formula.json`)

Ten steps, two human gates, three phases (Design / Validate / Build / Learn):

```
brainstorm ──▶ discovery ──▶ [GATE: review-discovery] ──▶ work-breakdown
                                                                │
                                                                ▼
                              execute-skeleton ──▶ [GATE: review-skeleton]
                                                                │
                                                                ▼
                              execute-full ──▶ ceremony-retro ──▶ outcome-check
```

Each step's `description` tells Claude what to do — often "run /discovery" or
"dispatch named agents via TeamCreate". The formula is the script; the skills
are the subroutines.

### The skill stack

```
build        ← front-door router; classifies the work, pours the right molecule
  └─ brainstorming     ← "should we even build this?" pre-filter
       └─ discovery    ← adversarial wrapper on openspec CLI; produces design doc
            └─ work-breakdown  ← reads openspec, writes beads spec+task issues
                 └─ beads-execution  ← dispatches parallel agents for bd ready tasks
                      └─ dispatching-parallel-agents / subagent-driven-development
```

### The hook stack (what the rules can't enforce alone)

- **`openspec_init_guard.py`** — ensures `openspec init` runs before `openspec new change`
- **`spec_id_enforcement.py`** — blocks `bd create --type task` without `--spec-id`
- **`discovery-gate.py`** — blocks `bd create` on feature-scale work without discovery first
- **`mol_status_check.py`** — SessionStart hook that surfaces active molecules
- **`enforce_named_agents.py`** — blocks `Agent(...)` calls without `name` + `team_name`
- **`tdd-gate.py`** — requires a failing test before implementation in test-capable repos
- **`validate_no_shirking.py`** — catches premature "done" declarations

See each file's top-of-file docstring for exact trigger logic.

---

## ⚠️ Warnings

### This is opinionated

The `rules/` directory encodes strong opinions:
- **`planning-discipline.md`** — `mol-feature` on any non-trivial work
- **`tdd-enforcement.md`** — failing test FIRST in any test-capable repo
- **`agent-teams-default.md`** — default to `TeamCreate` + named agents for anything multi-step
- **`outcome-ownership.md`** — done = verified end-to-end, not "my change compiles"
- **`molecule-awareness.md`** — surface active molecules on every session start

Read the rules BEFORE installing. Edit to match your philosophy. These are not
universally applicable — the TDD rule in particular is load-bearing and will
feel restrictive if your project has no test infrastructure.

### Hooks are load-bearing

Skills produce guidance. Hooks produce enforcement. If you install skills
without hooks, Claude can and will drift from the workflow. If you install
hooks without skills, the hooks will block things without offering a path
forward.

Install both, or neither.

### Path assumptions

The bootstrap script (`scripts/project-bootstrap.sh:24-27`) is gated on
`~/GitHub/*`. If your repos live elsewhere, edit that case statement or
parameterize it.

Some rules reference `~/GitHub/` paths directly — grep before installing if
you're particular about that.

### Not shared

Deliberately excluded from this bundle:
- `~/.claude/settings.json` (contains personal auth + permissions) — only the
  `hooks` and `env` blocks are templated
- `~/.claude/projects/*/memory/` (personal memory)
- `~/.claude/hooks/` hooks unrelated to openspec/beads flow (statusline, etc.)
- `~/.beads/` databases

---

## Uninstall

```bash
./INSTALL.sh --uninstall
```

Removes all symlinks. Your `.backup-<timestamp>` files are left alone — rename
them back manually to restore your previous config.

---

## Credits and philosophy

This setup synthesizes ideas from:
- **OpenSpec** — structured change management for AI-assisted development
- **Beads** — graph-based task tracker designed for AI agents
- **Steven Gong's walking skeleton** — riskiest assumption first, 1-3 tasks, 30-60 min
- **Manager Tools, Radical Candor, Playing to Win** — the rules' flavor
- **Lencioni / Grove / Brené Brown** — outcome-ownership and psychological safety

The glue — molecule formulas, skill overlays, hook enforcement — is my own
iteration, not a product. Expect to modify.
