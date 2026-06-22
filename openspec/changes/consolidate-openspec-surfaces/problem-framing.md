# Problem Framing — consolidate-openspec-surfaces

## Problem
Each of the four OpenSpec operations (apply / archive / explore / propose) ships as
~3–4 separately hand-maintained bodies, and two of them are invisible to
`agent-surfaces/manifest.json` — the file CLAUDE.md names as the source of truth:

- Form 1 `openspec-*` skill — lives in BOTH `.claude/skills/openspec-*/` (Claude,
  **no manifest target**) and `.agents/skills/openspec-*/` (Codex, `codex=ready`).
  Upstream-vendored from the openspec CLI (`generatedBy: 1.2.0`, `author: openspec`).
- Form 2 `source-command-opsx-*` skill — `.agents/skills/` only, `codex=ready`. A
  hand-authored migration wrapper of Form 1.
- Form 3 `/opsx:*` command — `.claude/commands/opsx/*.md`, committed repo source; the
  manifest has **no `commands` key at all**.

Three verified consequences:
1. **The manifest lies about Form 1.** It marks the `openspec-*` skills
   `claude=unsupported` yet they ship in `.claude/skills/` and load live on Claude.
2. **The bead-integration overlay is dropped on the Claude tree.** The
   bead-tracking steps (create/close the bead; treat `tasks.md` as artifact-state
   only) exist on the `.agents` tree (→ Codex) and are **absent on the `.claude`
   tree (→ the Claude host actually in use)**. Verified per-op for `apply`:
   `.agents` = 3 bead mentions, `.claude` = 0. The primary host runs the
   bead-blind forms. **Git-verified cause:** the Claude copy was created bead-free in
   commit `4a0132a`; the bead steps were authored on the Codex side later in
   `49b014e` "Add Codex adapter parity surfaces" (2026-06-13), which touched only
   `.agents/` and was never backported. The relevant bead hooks
   (`openspec_task_reconciliation_gate`, `bd_prime`) are `ready` on *both* hosts and
   do not replicate the inline "create a bead before implementation" step — so the
   asymmetry is incomplete propagation (drift), not a deliberate Claude-vs-Codex
   division of labor.
3. **The drift is a shared dead pointer.** Both `/opsx:continue` (Form 3) and
   `openspec-continue-change` (Form 2) reference targets that exist on neither host.

The axis of divergence is the render **tree** (`.agents` vs `.claude`), and neither
tree is a clean superset: `apply`'s bead steps live in `.agents`; `archive`'s
`Task`-tool sync dispatch lives in `.claude` (and *must* be absent from Codex —
`test_agent_surfaces.py:344` forbids `Task`/`subagent_type` tokens in Codex skills).

## Why Now
This repo IS the workflow tooling. A Claude user and a Codex user are handed
**different instructions for the same OpenSpec op today**, and the Claude user
silently loses bead integration — a cross-surface correctness drift, not cosmetics.
The duplication has already drifted in three observable ways (continue-pointer,
bead-steps, AskUserQuestion-vs-direct), and the next upstream openspec-CLI bump will
re-vendor and clobber escapement's customizations unless the authoring model is fixed
first. This is duplicated *authority* (CLAUDE.md's DRY trigger), not similar text.

## Decision Authority
Alexander Vyhmeister — personal workflow tooling. Per-op Claude-surface decision
(command-only vs command+skill) delegated to discovery per the 2026-06-22 brainstorm.

## Behavioral Population
Claude Code and Codex agents invoking OpenSpec operations, plus
`render_agent_surfaces.py` (the renderer that must project one canonical body onto
each host's surface) and `test_agent_surfaces.py` (the drift oracle that must keep
the reconciliation from re-drifting).

## Riskiest Assumption
That a canonical-body format with **named, positionally-independent slots** can be
defined, and `render_agent_surfaces.py` extended to project it into a Codex skill +
Claude command — including host-conditional slot selection (Claude `Task` dispatch vs
Codex bead-fallback, stripping the `CODEX_SKILL_FORBIDDEN` token) — such that the
projection survives an upstream restructure. The 4-lens review established this is
**net-new multi-task machinery, not a cheap extension**: today the skill/command render
path is pure `read_text()` copy and the only assembly machinery is docs-only.

We will know this is true when: the slot format + projector, validated on the **`archive`**
op (the one that exercises host-conditional dispatch + the forbidden-token wall +
interleaved overlay at once) under a **simulated-restructure** re-vendor, produces a Codex
skill and Claude command that are byte-stable, carry the bead steps on both hosts, carry the
Task dispatch on Claude / absent on Codex, and survive the restructure — with the per-host
coverage and `wrapper_skills == source_skills` tests green. Validating on `apply` +
identical-base re-emit would prove none of this.

If false, we stop after one op's effort and reconsider — the drift may be cheaper to fix in
place than to re-architect authoring.

Secondary assumption: the manifest⇄reality lie is real and mechanically detectable. If a RED
bidirectional fidelity test comes back GREEN, the "surfaces have drifted" premise is wrong and
we DEFER.

## Success Criteria
Each of the four OpenSpec ops has exactly ONE hand-maintained canonical source, which
the renderer projects into every host's invocation surface (no surface hand-maintained);
the manifest's `claude` status matches what actually loads; every op keeps ≥1
host-appropriate invocation path on each supported host with the set-equality oracle
preserved (not loosened); the Claude host's ops regain the bead-tracking steps they lack
today (authority assembled per-step from the union across trees); the previously
ungoverned surfaces and the undocumented installer are brought under governance; the
dead `continue` pointer is resolved explicitly; and escapement's bead-aware overlay
survives a simulated upstream re-vendor. Full numbered, falsifiable form in `design.md`
§2.
