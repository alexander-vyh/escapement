# Plugin-Native Install (+ Host-Neutral Model Tiering)

**Status:** design · **Date:** 2026-07-09 · **Branch:** `feat/cost-tiering-from-pilotfish`
**Framing:** see `problem-framing.md` (six fields confirmed in-session).

## Goal

Install is **the host's native plugin mechanism** — `/plugin install` on Claude,
`codex plugin add` on Codex — plus one small cross-host CLI for the residue no plugin
can reach. `INSTALL.sh` is deleted.

## Non-goals

- Rewriting the gates, skills, or harness. This is a **packaging** change.
- Changing the main-session model default (`model: "best"`). That is a user preference,
  not a packaging decision.
- Codex hook parity *via plugin*. Structurally impossible (see capability matrix).

## Verified capability matrix

Provenance marked. Nothing load-bearing here is a guess.

| Surface | Claude plugin | Codex plugin | Codex real home |
|---|---|---|---|
| Hooks / gates | ✅ `hooks/hooks.json` [verified: code.claude.com plugins-reference § Hook configuration] | ❌ | `.codex/hooks.json` (project) |
| Agents | ✅ `agents/*.md`; frontmatter supports `model`, `effort`, `tools`, `disallowedTools`, `isolation` [verified: ibid. § Agents] | ❌ | `~/.codex/agents/*.toml` (user) |
| Skills | ✅ | ✅ `"skills"` | plugin |
| Slash commands | ✅ | ❌ (not observed) | — |
| MCP servers | ✅ | ✅ `"mcpServers"` | plugin |
| Executable scripts (`harness/bin`) | ✅ via `${CLAUDE_PLUGIN_ROOT}` [verified: ibid. § Environment variables] | ❌ | — |
| Base model / effort | ❌ user-scoped | ❌ | `~/.codex/config.toml` |
| `fallbackModel`, `permissions` | ❌ [inferred: plugins sandboxed to `pluginConfigs.<name>`; a plugin-root `settings.json` supports only `agent` + `subagentStatusLine`; unknown keys silently ignored] | ❌ | — |
| Beads formulas | ❌ [verified: paths traversing outside plugin root are not copied to cache; cache is read-only] | ❌ | `~/.beads/formulas/` |

**Codex plugin ceiling — `skills` + `mcpServers` only.** The manifest-key union across
all 12 shipped OpenAI plugins (bundled + primary-runtime) is `{name, version, interface,
description, author, homepage, license, keywords, skills, repository, mcpServers,
bundledContentVariant, apps, openaiCapabilities}`. No `hooks`, no `agents`. A `find`
across every shipped plugin dir returns zero `hooks.json` and zero `agents/` dirs.
*[12/12 convergent empirical evidence; NOT a published schema — this is the riskiest
assumption; see `problem-framing.md`.]*

### The consequence

Escapement is mostly **gates**, and gates are **hooks**. A Codex plugin cannot ship
hooks. Therefore **"just a plugin" is achievable on Claude and structurally impossible
on Codex.** Codex's "equivalent ease" must come from the CLI, not the plugin. This
asymmetry is a property of the hosts, not a design preference — record it, don't paper
over it (cf. the Codex adapter note: *"Unsupported Claude-only behavior stays explicit
rather than being copied into a Codex surface as prose."*).

## Design

### 1. Claude: plugin-only

Delete the symlink deployment. The plugin already carries hooks (40/43), agents,
commands, rules, skills, and `harness/bin`. The remaining work is subtraction:

- Migrate the 6 settings-only hooks into the plugin's `hooks.json`, or classify them as
  personal/user-scope. Likely **personal**, not escapement-core: `jixia_send_bounce.py`,
  `external_comment_gate.py`. Likely **core, must migrate**: `oracle_downgrade_stop.py`,
  `pre-compact-save.sh`, `inject-timestamp.sh`, `project-bootstrap.sh`.
- Fix version resolution so updates actually occur (`escapement-9mki`).

### 2. Codex: plugin for skills/MCP, CLI for everything else

- Change `.agents/plugins/marketplace.json` from `"source": "local"` to a **Git**
  source. `codex plugin marketplace upgrade` refreshes *Git* snapshots only, so a local
  source can never update.
- Delete the dead `plugins/escapement/hooks/` (`escapement-e03p`).
- The CLI installs `.codex/hooks.json`, `~/.codex/agents/*.toml`, and merges
  `~/.codex/config.toml`.

### 3. The `escapement` CLI (bun/TS) — the residue installer

Its scope is defined **by the capability matrix**, not by taste. It owns exactly what no
plugin can reach.

```
bunx escapement init
  ├─ Claude: /plugin marketplace add + install        (plugin does the work)
  │          + merge settings.json  (model, fallbackModel)      ← residue
  │          + write ~/.beads/formulas/*                        ← residue
  └─ Codex:  codex plugin add escapement@escapement   (skills + MCP only)
             + write .codex/hooks.json                          ← the gates
             + write ~/.codex/agents/*.toml                     ← agents + tier bindings
             + merge ~/.codex/config.toml  ([features] hooks, model, effort)
             + write ~/.beads/formulas/*

bunx escapement dev       # local-scope install pointed at the working tree (see below)
bunx escapement update    # codex marketplace upgrade; refresh formulas; re-merge config
bunx escapement doctor    # self-validating checks (see Oracle)
```

**`escapement dev` is mandatory, not optional.** `INSTALL.sh --dev` symlinks `~/.claude`
into the live working tree so a hook edit takes effect instantly. A plugin installs into
a **read-only cache**, so plugin-only install would otherwise destroy escapement's own
development loop. `dev` must restore instant-effect edits (local-scope install against
the working tree).

**Why a real language, not bash:** the CLI must *merge* into user-owned `config.toml`
and `settings.json` without clobbering unknown keys. Bash cannot safely round-trip TOML.
Merges are backup-then-additive and idempotent; doc-shaped surfaces use marker-delimited
blocks so uninstall is exact.

**Why `bunx`:** "no install, always latest" is most of the auto-update story for free.

### 4. Model tiering rides on top

The tiering splits cleanly along the plugin/residue seam — which is *why* the CLI earns
its existence. Without tiering the residue is only beads formulas, arguably not worth a
package.

| Tier | Role | Claude (plugin agent) | Codex (CLI-written agent) | Effort |
|---|---|---|---|---|
| recon | `scout`, `Explore` | `model: haiku` | `model = "gpt-5.6-luna"` | low |
| mechanical | `mech-executor` | `model: sonnet` | `model = "gpt-5.6-terra"` | low |
| judgment | `executor` | `model: opus` | `model = "gpt-5.6-terra"` | medium |
| verify | `verifier` | `model: opus` | `model = "gpt-5.6-sol"` | medium |
| security | `security-executor` | `model: opus` | `model = "gpt-5.6-sol"` | high |
| orchestrator | (main session) | settings `model`/`fallbackModel` | `config.toml` `model` | high |

*[GPT-5.6 Sol/Terra/Luna tier names and their flagship/balanced/cheap positioning come
from third-party trackers (July 2026). `openai.com/index/gpt-5-6/` returned HTTP 403 and
was never read. Confirm identifiers against OpenAI's live model/pricing page before
pinning them.]*

Policy prose names **roles**, never models — so a deprecation is a one-line edit in the
tier table, and the shared onboarding fragment renders identically into `CLAUDE.md` and
`AGENTS.md`.

**Known asymmetry:** Claude has true aliases (`best`/`opus`/`sonnet`/`haiku`) plus a
`fallbackModel` chain. No Codex `fallbackModel` equivalent was found — a deprecated
Codex tier is a manual bump, not a graceful degrade. Recorded, not hidden.

**Architecture fork (owner's call):** *(A)* render tier bindings from
`agent-surfaces/manifest.json` into both hosts' agent files, or *(B)* hand-author both.
Recommend **(A)** — escapement's own adapter law is "add through the manifest first,
then render to the host surface," and the current `claude/agents` + `plugins` mirror +
`INSTALL.sh` triplication is exactly the drift that not rendering produces.

## Oracle

Behavioral config: parse checks are gates, never oracles. Every check must **observe**.

1. **No double-fire.** Intersection of scripts registered by the plugin's `hooks.json`
   and by `~/.claude/settings.json` is **empty**; a Stop event produces exactly **one**
   `validate_no_shirking` message. *(Negative control: re-adding a symlink registration
   must make this fail.)*
2. **Clean-machine install.** `INSTALL.sh` deleted; `bunx escapement init` alone yields
   a working escapement on both hosts.
3. **Auto-update is real.** A no-op commit to `main` + the update path changes the
   installed plugin's resolved version.
4. **Dev loop survives.** After `escapement dev`, editing a hook's denial string shows
   the new string on the next fire — no reinstall.
5. **Tier bindings take effect.** Dispatch `Explore`; assert the agent ran at the recon
   tier by observing its model — *not* by asserting the frontmatter parses. *(Negative
   control: an agent with no `model` must inherit the main-session model, proving the
   assertion is capable of failing.)*
6. **No orphan files.** Nothing under `plugins/escapement/` is unreferenced by
   `.codex-plugin/plugin.json`.

## Walking skeleton

Validates the riskiest assumption before any build:

> Author a minimal Codex plugin declaring a `hooks` key with one trivial hook. Install
> via `codex plugin add`. Observe whether it fires.

One trivial hook, one observation, one answer. If it fires, the CLI's Codex scope
collapses to config-merge + beads formulas and the whole design simplifies.

## Sequence

1. `escapement-ptzz` (P1) — kill the symlink deploy; plugin becomes the sole Claude
   surface. **Blocks everything**: a plugin-only install cannot be tested while both are
   live.
2. `escapement-9mki` (P1) — fix version resolution so updates occur.
3. Walking skeleton — settle the Codex `hooks` question.
4. `escapement-e03p` (P2) — delete dead Codex hooks; document the skills+MCP ceiling.
5. Codex marketplace `local` → Git source.
6. `escapement` CLI: `init` / `dev` / `update` / `doctor`.
7. Model tiering: plugin agents (per-role) + CLI (base model), both hosts.

## Open questions

- **[blocking, delegated]** Can a Codex plugin merge `~/.codex/config.toml` or write
  `~/.codex/agents/*.toml`? Assumed **no**. If yes, the CLI's Codex scope shrinks.
- **[blocking, delegated]** Does `codex plugin marketplace upgrade` upgrade *installed*
  plugins, or only refresh the snapshot (requiring a re-`add`)?
- Which of the 6 settings-only hooks are escapement-core vs. the owner's personal surface?
- Should `model: "best"` ship as a default? **Recommend: no** — it changes every
  session's default model; that is a user preference, not a packaging concern.

## Prior art

The role→tier→model-free-policy structure is borrowed from
[pilotfish](https://github.com/Nanako0129/pilotfish) (MIT). **Not** borrowed: its
deliberate minimalism (no hooks, no per-project config, global-only) — escapement is a
gate bureaucracy by design, and pilotfish's "deliberately left out" list is a list of
things escapement intentionally has. Its `curl | sh`-shaped install is also *worse* than
plugin-native: native marketplaces give versioning, pinning, listing, and removal as
first-class operations. **Borrow the tiering; keep the plugin.**
