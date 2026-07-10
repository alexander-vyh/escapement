# Problem Framing — plugin-native-install

Source: inline framing, confirmed in session 2026-07-09 with the repo owner.

## Problem

Escapement has **two live installs of itself** and they collide.

`INSTALL.sh` symlinks the repo into `~/.claude/` and registers 43 hooks in
`~/.claude/settings.json`. Independently, a Claude plugin (`plugins/escapement-claude/`)
registers 40 hooks via its own `hooks.json`. **37 scripts are registered by both.**
Claude Code does not dedupe them, so those gates fire twice per matching tool call.

This is observed, not theorized: on 2026-07-09 a single Stop event produced four
blocking messages — `validate_no_shirking.py` twice (once from `~/.claude/hooks/`, once
from `${CLAUDE_PLUGIN_ROOT}/hooks/`) and `stop_hook.py` twice, same split.

Two related defects fall out of the same root cause (two installers, one repo):

- `.claude-plugin/marketplace.json` advertises *"Tracks main for continuous
  auto-update"*, but `plugin.json` pins `"version": "1.0.0"`. Under the documented
  version-resolution rules an explicit version means the plugin updates **only when that
  field is bumped**; and third-party marketplaces default to auto-update **off**. The
  plugin has never auto-updated. (`escapement-9mki`)
- `plugins/escapement/hooks/hooks.json` (Codex) is referenced by nothing —
  `.codex-plugin/plugin.json` declares only `"skills": "./skills/"`. It implies a Codex
  gate parity that does not exist. (`escapement-e03p`)

## Why Now

Three forcing reasons, in order of hardness:

1. **The double-fire is active today**, costing 2× hook latency and 2× denial text
   across nearly the entire gate suite. It degraded this very session.
2. **Model tiering cannot be designed without resolving packaging first.** Per-role
   model bindings must live *somewhere*, and the capability matrix says Claude plugin
   agents can carry `model`/`effort` while Codex agents cannot ship in a plugin at all.
   Which surface owns the bindings is a packaging decision, not a tiering decision.
3. **`INSTALL.sh` is a `curl | sh`-shaped installer** in a repo that now has
   first-class plugin manifests on both hosts. Native marketplaces provide versioning,
   pinning, listing, and removal as first-class operations; the shell script provides
   none of them.

## Decision Authority

The repo owner (alexander-vyh), sole maintainer of escapement. No external stakeholder.
Scope and success criteria confirmed in-session; the render-vs-hand-author and
`model: "best"`-as-default questions are explicitly reserved to the owner.

## Behavioral Population

The owner's own agent sessions across **both hosts** (Claude Code and Codex), plus any
future adopter of escapement.

Behavior that must change:

- Install becomes `bunx escapement init` (or the two native plugin commands) instead of
  `./INSTALL.sh`.
- **The dev loop changes.** `INSTALL.sh --dev` symlinks `~/.claude` into the live
  working tree, so a hook edit takes effect immediately. A plugin installs into a
  **read-only cache**. Plugin-only install therefore removes instant-edit development
  unless the CLI provides an explicit `escapement dev` (local-scope, working-tree)
  mode. This is a hard requirement on the CLI, not an acceptable regression.

## Riskiest Assumption

**Betting** that a Codex plugin cannot deliver hooks or agents — so escapement's gates
and per-role model bindings on Codex must be installed by the `escapement` CLI rather
than by `codex plugin add`.

**Wrong when** a `hooks` (or `agents`) manifest key exists in the Codex plugin schema
and is simply unused by the 12 first-party plugins I sampled. The evidence is
convergent-empirical (no `hooks`/`agents` key in any of 12 shipped `plugin.json`; zero
`hooks.json` and zero `agents/` dirs found across every shipped plugin directory) but is
**not** a published schema.

**Would know within ~1 day** by authoring a minimal Codex plugin that declares a `hooks`
key with one trivial hook, installing it via `codex plugin add`, and observing whether
the hook fires. One trivial hook, one observation, one answer. If it fires, the CLI's
Codex scope collapses to config-merge + beads formulas and Codex reaches near-parity.

## Success Criteria

Observable, mechanically checkable, in the real environment:

1. **No double-fire.** The set intersection of scripts registered by the plugin's
   `hooks.json` and by `~/.claude/settings.json` is **empty**, and a single Stop event
   produces exactly **one** `validate_no_shirking` message. *(Negative control:
   re-adding one symlink registration must make this check fail.)*
2. **`INSTALL.sh` is deleted** and a clean machine reaches a working escapement on both
   hosts via `bunx escapement init` alone.
3. **Auto-update is real.** A no-op commit to `main`, followed by the update path,
   changes the installed plugin's resolved version.
4. **The dev loop survives.** `escapement dev` yields instant-effect hook edits from the
   working tree (edit a hook's denial string, observe the new string on next fire).
5. **Tier bindings take effect** — dispatching `Explore` runs at the recon tier, asserted
   by observing the agent's model, not by asserting the frontmatter parses. *(Negative
   control: an agent with no `model` must inherit the main-session model.)*
6. **No orphan files.** Nothing under `plugins/escapement/` is unreferenced by
   `.codex-plugin/plugin.json`.
