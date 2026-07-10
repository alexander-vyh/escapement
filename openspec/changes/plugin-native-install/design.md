# Plugin-Native Install (+ Host-Neutral Model Tiering)

**Status:** design (revised) · **Date:** 2026-07-09, revised 2026-07-10
**Framing:** see `problem-framing.md`.

> ## ⚠️ Revision 2 — the v1 central claim was REFUTED
>
> v1 asserted: *"Codex plugins cannot ship hooks; escapement is mostly gates; gates are
> hooks; therefore the CLI must own Codex's gates."* **This is false.**
>
> **Codex plugins ship hooks today — escapement's already do.** `~/.codex/config.toml`
> holds **17 live registrations** of the form
> `[hooks.state."escapement@escapement-local:hooks/hooks.json:pre_tool_use:N:0"]`
> (+ `session_start` ×5, `pre_compact` ×1) — even though
> `plugins/escapement/.codex-plugin/plugin.json` declares **no** `hooks` key. Codex
> **default-discovers** `hooks/hooks.json` at the plugin root.
>
> v1's error: it read **absence of an explicit declaration** across 12 shipped plugins as
> **absence of capability**. The mechanism was implicit discovery. The negative evidence
> was real; the inference from it was not. This is why the claim was flagged as the
> riskiest assumption with a walking skeleton — the skeleton ran, and killed it.
>
> The correction *narrows* the CLI but surfaces a **worse** problem v1 missed entirely:
> **per-agent model tiering has no expression in Codex at all** (`escapement-8jsb`).

## Goal

Install is **the host's native plugin mechanism** — `/plugin install` on Claude,
`codex plugin add` on Codex — plus one small cross-host CLI for the residue no plugin
can reach. `INSTALL.sh` is deleted.

## Non-goals

- Rewriting the gates, skills, or harness. This is a **packaging** change.
- Changing the main-session model default. That is a user preference.
- Per-**subagent** model tiering on Codex. Not a scope choice — **not expressible**
  (see below).

## Verified capability matrix

Provenance marked. Codex column verified against the installed `codex-cli 0.144.1`,
live `~/.codex/config.toml` state, a real `codex exec` run, and the authoritative
`plugin-creator/references/plugin-json-spec.md` embedded in the binary.

| Surface | Claude plugin | Codex plugin | Notes |
|---|---|---|---|
| Hooks / gates | ✅ `hooks/hooks.json` | ✅ **`"hooks"` key *or* default discovery of `hooks/hooks.json`** | 17 escapement hooks live in Codex now |
| — `Stop` event | ✅ | ✅ **supported** | `codex exec` printed `hook: Stop`; `codex@openai-codex` registers one |
| — `PreToolUse` deny | ✅ | ✅ | Codex enforces the same `permissionDecision: deny` + non-empty reason contract |
| Skills | ✅ | ✅ `"skills"` | 12/12 shipped plugins |
| MCP servers | ✅ | ✅ `"mcpServers"` | path string or inline |
| Agents / subagents | ✅ `agents/*.md` with `model`, `effort` | ❌ **no manifest key** | Codex agents are user config (`~/.codex/agents/*.toml`) |
| Slash commands | ✅ | ❌ | must become skills |
| Base `model` / effort | ❌ user settings | ❌ user config | |
| **Per-agent `model`/effort** | ✅ frontmatter | ❌ **not expressible in Codex at all** | see `escapement-8jsb` |
| `fallbackModel` | ❌ | ❌ (no equivalent exists) | |
| Install-time script exec | ❌ | ❌ **no `postinstall`** | install is a pure file copy |
| Beads formulas (`~/.beads/`) | ❌ | ❌ at install; ✅ **via a `session_start` hook** | gated on hook trust |

### Codex-specific mechanics that shape the design

- **Claude manifests are natively read by Codex.** The binary accepts
  `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`. `superpowers`
  ships one repo with `.claude-plugin/`, `.codex-plugin/`, `.cursor-plugin/`,
  `.kimi-plugin/` manifests + per-host hook files. **That is the template.**
- **Trust model (deployment gotcha).** Every hook is keyed
  `<source>:<file>:<event>:<group>:<idx>` with a `trusted_hash`. **Untrusted hooks are
  silently skipped in non-interactive `exec`.** A fresh `codex plugin add` on a new
  machine lands hooks that *do nothing until trusted*. Editing a hook command changes its
  hash → re-trust. This — not gate delivery — is the CLI's real Codex job.
- **`marketplace upgrade` does not upgrade installs.** It refreshes the *catalog*
  snapshot only; to move an install you re-run `codex plugin add`. It also **errors on
  local marketplaces** (`escapement-local is not configured as a Git marketplace`).
- **Per-agent model is absent, not merely plugin-inaccessible.** The role-file validator
  accepts only `name`, `description`, `nickname_candidates`, `developer_instructions`
  (+ `permissions`/`filesystem`). `ConfigLayerSource` has **no `Agent` variant**, so a
  role file is a role definition, not a config layer that could carry `model`.

## Design

### 1. Claude: plugin-only

Delete the symlink deployment. The plugin already carries hooks (40/43), agents,
commands, rules, skills, `harness/bin`. Remaining work is subtraction:

- Migrate the 6 settings-only hooks, or classify as personal (`jixia_send_bounce.py`,
  `external_comment_gate.py` look personal; `oracle_downgrade_stop.py`,
  `pre-compact-save.sh`, `inject-timestamp.sh`, `project-bootstrap.sh` look core).
- Fix version resolution so updates occur (`escapement-9mki`).

### 2. Codex: plugin owns the gates too

Revised from v1. The Codex plugin can and should ship the gates:

- Declare `"hooks": "./hooks/hooks.json"` explicitly — stop relying on undocumented
  default discovery (`escapement-z506`).
- **Ship a `stop` hook.** The continuation-harness Stop gate has a real Codex home and
  currently ships none. Largest behavioral parity gap.
- Rename the marketplace `escapement-local` → `escapement`, and change `source` from
  `local` to a **Git** URL (`escapement-z506`).
- Consider a single dual-manifest plugin dir (`.claude-plugin/` + `.codex-plugin/`), per
  the `superpowers` precedent.

### 3. The `escapement` CLI — scope, corrected

The CLI is **much smaller than v1 claimed** — it does *not* install Codex's gates. It
owns only what no plugin on either host can reach:

```
bunx escapement init
  ├─ Claude: /plugin marketplace add + install
  │          + merge settings.json (model, fallbackModel)      ← residue
  ├─ Codex:  codex plugin marketplace add <git> && codex plugin add escapement@escapement
  │          + merge ~/.codex/config.toml ([features], model, model_reasoning_effort)
  │          + TRUST the plugin's hooks                        ← the real Codex job
  │          + write ~/.codex/agents/*.toml (roles only; NO model — unsupported)
  └─ both:   ~/.beads/formulas/*                               ← 3rd tool, no jurisdiction

bunx escapement dev       # local-scope install against the working tree (read-only cache otherwise)
bunx escapement update    # re-run `codex plugin add`; refresh formulas; re-merge config
bunx escapement doctor    # self-validating checks (see Oracle)
```

**`escapement dev` remains mandatory** — a plugin installs to a read-only cache, so
plugin-only install would otherwise destroy the instant-edit dev loop.

**Why a real language, not bash:** the CLI must *merge* user-owned `config.toml` and
`settings.json` without clobbering unknown keys. Bash cannot safely round-trip TOML.
Backup-then-additive, idempotent; doc surfaces use marker-delimited blocks.

**Beads formulas** cannot be seeded at install (no `postinstall` on either host). Either
the CLI writes them, or a `session_start` hook does — the latter only once trusted.

### 4. Model tiering — Claude-only, and say so

Per-role tiering is **plugin-deliverable on Claude** (agent frontmatter takes `model` and
`effort`) and **not expressible on Codex at any layer**.

| Tier | Role | Claude (plugin agent) | Codex |
|---|---|---|---|
| recon | `scout`, `Explore` | `model: haiku`, `effort: low` | ❌ no per-agent binding |
| mechanical | `mech-executor` | `model: sonnet`, `effort: low` | ❌ |
| judgment | `executor` | `model: opus`, `effort: medium` | ❌ |
| verify | `verifier` | `model: opus` | ❌ |
| security | `security-executor` | `model: opus`, `effort: high` | ❌ |
| orchestrator | main session | settings `model`/`fallbackModel` | ✅ top-level `config.toml` only |

Codex's only levers are **session-wide**: top-level `model`/`model_reasoning_effort`,
per-**profile** config (`--profile`), or `-c model=` at invocation. A profile is a
session-level lever, not a role-level one — **it is not equivalent** and must not be
presented as parity. Decision pending in `escapement-8jsb`.

Policy prose still names **roles**, never models. On Claude that buys real tiering; on
Codex it degrades gracefully to "every role runs at the session model."

**Architecture fork (owner's call):** *(A)* render tier bindings from
`agent-surfaces/manifest.json`, or *(B)* hand-author. Recommend **(A)** — and this is no
longer theoretical: PR #110 added `worktree-discipline.md` to `claude/rules/` without
running the generator, so the plugin shipped **without** it. Hand-maintained mirrors drift
within one PR. `escapement-a1x2`.

## Oracle

Behavioral config: parse checks are gates, never oracles. Every check must **observe**.

1. **No double-fire.** Intersection of scripts registered by the plugin's `hooks.json`
   and `~/.claude/settings.json` is **empty**; one Stop event → exactly one
   `validate_no_shirking` message. *(Negative control: re-adding one symlink registration
   must make this fail.)*
2. **Clean-machine install.** `INSTALL.sh` deleted; `bunx escapement init` alone yields a
   working escapement on both hosts.
3. **Auto-update is real.** A no-op commit + the update path changes the installed
   plugin's resolved version (Claude); `codex plugin add` re-run moves the cache (Codex).
4. **Dev loop survives.** After `escapement dev`, editing a hook's denial string shows the
   new string on next fire — no reinstall.
5. **Codex gates actually fire.** After `codex plugin add` + trust, a `codex exec` run
   emits `hook: SessionStart` and `hook: Stop` for escapement's hooks. *(Negative control:
   an untrusted hook must be silently skipped — proving the check can fail.)*
6. **Tier bindings take effect (Claude).** Dispatch `Explore`; assert the agent ran at the
   recon tier by **observing its model**, not by asserting frontmatter parses. *(Negative
   control: an agent with no `model` inherits the main-session model.)*
7. **Generated surfaces current.** `tools/render_agent_surfaces.py --check` exits 0 — and
   is a **required, blocking** status check (it currently is not; main merged red).

## Sequence

1. `escapement-ptzz` (P1) — kill the symlink deploy. **Blocks everything.**
2. `escapement-9mki` (P1) — fix Claude version resolution.
3. `escapement-z506` (P1) — Codex: explicit `hooks` key, ship a `stop` hook, rename
   marketplace, `local` → Git source.
4. `escapement-8jsb` (P1) — decide: tiering is Claude-only (recommended) vs. profiles.
5. Make the drift check a blocking required status check.
6. `escapement` CLI: `init` / `dev` / `update` / `doctor` (+ Codex hook trust).
7. Model tiering: Claude plugin agents.

## Open questions

- `escapement-8jsb`: accept Claude-only tiering, or express Codex tiering via profiles
  (session-level, **not** equivalent)?
- Which of the 6 settings-only hooks are core vs. the owner's personal surface?
- Should `model: "best"` ship as a default? **Recommend no** — user preference.
- Hook sandboxing on Codex: `HookMetadata` carries `writes`/`approve`. Unresolved whether
  a *trusted* hook may write outside cwd (i.e. seed `~/.beads/`). Needs a positive test.

## Prior art

Role→tier→model-free-policy borrowed from [pilotfish](https://github.com/Nanako0129/pilotfish)
(MIT). **Not** borrowed: its deliberate minimalism (no hooks, no per-project config) —
escapement is a gate bureaucracy by design. Its `curl | sh` install is also *worse* than
plugin-native: marketplaces give versioning, pinning, listing, removal as first-class ops.
**Borrow the tiering; keep the plugin.** And note the borrow only half-transfers: pilotfish
is a Claude-only tool, and its central mechanism has no Codex equivalent.
