# Design — consolidate-openspec-surfaces

> Discovery output, **revised 2026-06-22 after a 4-lens review** (blinded adversarial
> + QA roundtable: renderer / oracle / migration). The review VERIFIED the problem
> diagnosis and the BUILD-as-reconciliation decision, but REJECTED the original
> fix-model on two counts (false starting state; oracle blind to its target). This
> version corrects the topology, reframes the fix, and hardens the oracles. Research
> basis: `.research/opsx-duplex-20260622/` (01 surface-map, 02–04 brainstorm, 05
> synthesis, 06 adversary, 07 renderer, 08 oracle, 09 migration).

## 1. Problem Statement

The four OpenSpec ops (apply/archive/explore/propose) are authored as 3–4 drifting
hand-maintained bodies per op. **Corrected topology (git-verified):** the live Claude
surfaces — `.claude/commands/opsx/*` and `.claude/skills/openspec-*` — are **committed
repo source**, hand-authored in commit `4a0132a`; they are NOT produced by the renderer
(its source trees `claude/commands/`, `claude/skills/` contain no opsx/openspec) and NOT
deployed by an installer (`INSTALL.sh` has no opsx/openspec entry). They load on Claude
because the repo's own `.claude/` is read directly when this repo is the project. The
Codex surfaces (`.agents/skills/openspec-*`, `.agents/skills/source-command-opsx-*`) are
the bead-aware lineage. The manifest marks the `openspec-*` skills `claude=unsupported`
while they are committed-and-live — the "manifest lie."

The goal is **one canonical body per op, with named positionally-independent slots,
rendered to each host's surface by the renderer (which becomes the writer of record)**,
guarded by oracles that catch drift and reject the regression. Not "pick one file,
delete the rest" (deletes the bead check); not "adopt the Claude bodies verbatim"
(freezes the bead-naive regression as canon — an oracle echo trap).

See `problem-framing.md` for the verified evidence and provenance.

## 2. Success Criteria

Numbered, observable, falsifiable. Each host-conditional criterion carries a **paired
positive + negative** check (the review found one-directional checks are gamed by a
"remove it everywhere" implementation).

1. **One authoring source per op.** Exactly one canonical body per op; hand-maintained
   bodies drop from 3–4 to 1. *Check:* an inventory keyed on a **declared op identifier**
   (not id-string matching) returns exactly one canonical source per op.
2. **Every host surface is generated AND the formerly-committed surfaces are now in the
   rendered set.** Each Codex skill + Claude command (+ optional Claude skill) is produced
   by the renderer; `.claude/commands/opsx/*` and `.claude/skills/openspec-*` are now
   `rendered_targets` (or removed). *Check (positive):* delete any rendered surface,
   re-render, it reproduces byte-for-byte. *Check (negative / anti-echo):* the render
   output for an op must NOT byte-equal the pre-revision bead-naive `.claude` body — i.e.
   adoption did not freeze the regression. `render --check` covers the opsx/openspec
   surfaces (today it provably does not). **Necessary-not-sufficient (adversary B3):**
   byte-stability is gameable by a stub renderer emitting empty/wrong content, so SC2 is
   valid only PAIRED with SC5's content controls — byte-stability proves the mechanism is
   deterministic; SC5 proves it carried the right body.
3. **The manifest stops lying — bidirectionally.** *Positive:* every `claude=ready` skill
   traces to a real rendered source. *Negative:* no `claude=unsupported` skill exists under
   `.claude/skills/`. *Check:* the bidirectional fidelity test (Task A) is GREEN; flipping
   the four entries to `claude=ready` without rendering them must FAIL the positive side.
4. **Per-host invocation coverage, asserted existentially per host.** Every op retains ≥1
   host-appropriate path on EACH supported host (Codex skill; Claude command and/or skill
   per the per-op decision). *Check:* a per-host existential assertion derived from the
   declared op key — retiring both Codex families while keeping 4 Claude commands must FAIL
   (a union-over-hosts check would wrongly pass). The existing `wrapper_skills ==
   source_skills` set-equality is **kept, never loosened to `<=`/membership**.
5. **No authority-bearing step dropped — split by kind, each with a positive control.**
   (a) **Bead steps → both hosts:** *positive:* rendered `apply` on Claude AND Codex each
   contain the create/update/close-bead steps; *negative:* deleting the bead slot makes
   EVERY host's render go RED. (b) **Host-divergent dispatch → host-parameterized:**
   *positive:* rendered `archive` on Claude contains the `subagent_type: general-purpose`
   Task dispatch; *negative:* rendered `archive` on Codex contains no `Task`/`subagent_type`
   token (`CODEX_SKILL_FORBIDDEN`). The positive control proves the slot SELECTED the step
   rather than rendering EMPTY. *Reject the fragile impl:* emit the bead-naive body + append
   a "(bead-aware)" sentence (passes a grep-for-"bead"); or drop the dispatch on both hosts
   (passes the Codex-absent check via global absence).
6. **The committed orphans are mechanically governed.** *Check:* every
   `.claude/skills/openspec-*` and `.claude/commands/opsx/*` path is EITHER a
   `rendered_target` OR an explicitly-governed adopted source — else FAIL. (Without this,
   SC1–SC5 can go GREEN while the committed orphans persist, 0 bead steps, loading live —
   the exact production state the change exists to fix.)
7. **The dead `continue` pointer is removed (decided).** All ~8 dangling `continue`
   references are struck from the canonical body during union-assembly. *Check:* no rendered
   surface references a `continue` target (none exists on either host; creating one violates
   Non-Goal 2). *Reject:* union-assembly silently inheriting the pointer.
8. **Customizations survive an upstream re-vendor RESTRUCTURE.** The overlay is a
   named-slot templated-include model, not a positional patch. *Check:* re-run the generator
   into a temp dir **with the base steps reordered/renumbered**; the bead steps still land in
   their slots (a positional patch would break/misapply — re-emitting an identical base is
   NOT a sufficient check).

## 3. Non-Goals

1. **Not collapsing the Codex skill and Claude command into one shared surface.** Locks in
   host-mechanic projection (Codex has no slash commands).
2. **Not changing any op's behavior beyond reconciling drift.** Canonical body = union of
   existing authority-bearing steps, host-parameterized; no new steps, no workflow redesign.
   (This is *why* SC7 removes `continue` rather than creating the op.)
3. **Not permanently forking from the upstream openspec CLI.** Thin overlay (named slots)
   over the vendored base.
4. **Not adding an auto-trigger Claude skill where one earns no keep.** `propose` →
   command-only (`/discovery`+`/brainstorm` own the ambient role); `apply`/`archive`/`explore`
   evaluated per-op at breakdown.
5. **Not adopting the committed `.claude` bodies verbatim as canon.** They are bead-naive
   and carry the Codex-forbidden `Task` token; canon is `.agents`-seeded + host-conditional.

## 4. Riskiest Assumption

**A canonical-body format with named, positionally-independent slots can be defined, and the
renderer extended to project it into a Codex skill + Claude command — including
host-conditional slot selection (Claude `Task` dispatch vs Codex bead-fallback, with the
`CODEX_SKILL_FORBIDDEN` token stripped) — such that the projection survives an upstream
restructure.** Today the skill/command render path is pure `read_text()` copy
(`render_agent_surfaces.py:382-388`); the only assembly machinery (`_render_document`) is
docs-only. So this is **net-new multi-task machinery, not a 60-min extension** — that
misestimate was the original design's core error.

**Resolving the data-flow inversion (adversary B1) — load-bearing topology decision.** Today
the renderer READS `.agents/skills/*`, `claude/skills/*`, `claude/commands/*` as inputs and
WRITES only into the plugin trees. Path A requires the opsx/openspec host surfaces to become
renderer OUTPUTS — but a dir cannot be both a hand-edited input and a generated output without
colliding with `check()`'s byte-equality. Resolution: **the canonical slot-bodies live at a NEW
source path that no host reads and the renderer never writes** (proposed:
`agent-surfaces/openspec/<op>.md`), and the renderer gains explicit write paths for the host
surfaces (`.agents/skills/openspec-*`, `.claude/commands/opsx/*`, and any Claude skill). Canon
= read-only input; every host surface = write-only output; no dir is both. The committed
hand-edited `.claude`/`.agents` opsx bodies are deleted (`git rm`) and re-generated from canon.
Establishing this clean source/target topology IS the core of Task B, not a detail.

**Liveness test:** build the slot format + projector and validate on **`archive`** (the only
op that exercises host-conditional dispatch + the forbidden-token wall + interleaved-overlay
at once) under a **simulated-restructure** re-vendor. `apply` + identical-base re-emit tests
none of these and would pass green while leaving the bet unproven.

**Secondary (cheap, RED-first):** the manifest⇄reality lie is mechanically detectable (Task A).

## 5. Walking Skeleton

Each task traces to a success criterion and tests an assumption before any retirement.

- **Task A → SC3 (oracle, RED-first).** Add the bidirectional manifest⇄filesystem fidelity
  test to `test_agent_surfaces.py`. Goes RED on the four `openspec-*` ids today. ~30 min.
  Reusable oracle; retires nothing.
- **Task B → SC8/SC5/SC2 (the riskiest bet).** Author the **named-slot canonical-body-format
  spec** (resolves Q3 — a GATING decision), then extend the renderer to project **`archive`**
  from that canonical body into the Codex skill + Claude command, and prove: byte-stable
  re-render; bead steps present on both hosts; Task dispatch present on Claude / absent on
  Codex; AND survives a simulated-restructure re-vendor. This is a multi-task spike, not 60
  min — scope it as its own skeleton task. **Lands GREEN before the migration commit.**
- **Task C → SC6 (decide the fork; the installer hunt is retired).** Git provenance is already
  resolved (committed source, commit `4a0132a`; no installer). Task C's deliverable is the
  **decision**: adopt-as-source (add `claude/skills/openspec-*` + `claude/commands/opsx/`
  source + manifest + `rendered_targets`) — taken — plus the mechanized SC6 governance check.
  ~30 min, no forensics.

If Task B fails (slot projection on `archive` can't be built cheaply), we stop having spent
one op's effort — the skeleton doing its job.

## 6. Proof of Delivery

> After this ships: each op has one canonical named-slot body the renderer projects into every
> host's surface; the formerly-committed `.claude` opsx/openspec surfaces are in the rendered
> set (and `render --check` covers them); the manifest's `claude` status matches reality
> bidirectionally; the Claude host's ops carry the bead steps (and the render does NOT byte-equal
> the old bead-naive body); the dead `continue` pointer is gone; and the projection survives a
> simulated upstream restructure — proven on `archive`, the op that stresses every mechanism.

## 7. Constraints (guardrails, revised)

- **G0 (retired-as-blocker).** The "undocumented installer" was a phantom; the surfaces are
  committed source. No forensic gate — Task C just records the fork decision.
- **G1.** Skeleton-first: the bidirectional fidelity test (Task A) ships RED before any family
  is touched.
- **G2.** Preserve `wrapper_skills == source_skills`; add the per-host existential coverage
  assertion (SC4). **Adversary B2 clarification:** `wrapper_skills == source_skills`
  (`test_agent_surfaces.py:100-111`) is a *Codex-plugin copy-fidelity* check (`.agents` vs the
  Codex wrapper) — it references NO Claude surface, so deleting a Claude path leaves it GREEN.
  The Claude-coverage protection is the **new per-op-per-host existential assertion (SC4)**, not
  `==`. Keep `==` (it guards Codex copy fidelity) AND add the per-host assertion; neither
  substitutes for the other. Loosening `==` remains a forbidden `never-suppress` downgrade.
- **G3 (corrected).** Atomic commit: `.agents` canon, manifest (incl. a commands
  representation + honest `claude` status), test fixtures, the `discovery` skill cross-ref
  (names `openspec-propose`), bead `escapement-98r` text, AND **`git rm` (or convert to
  `rendered_target`) the committed `.claude/commands/opsx/*` + `.claude/skills/openspec-*`**
  — the previously-missing orphan-removal step. The host-side `rm` script is struck (moot:
  these files were never symlinked into `~/.claude`; `git revert` reverses them). The atomic
  commit APPLIES an already-proven projector (Task B landed first).
- **G4.** Survivor chosen by AUTHORITY, assembled per-step from the union; canon is
  `.agents`-seeded (bead-aware) — never the bead-naive `.claude` body adopted verbatim (SC2
  anti-echo control enforces this).
- **G5.** Thin overlay = **named-slot templated-includes**, not a positional patch; SC8's
  check simulates a restructure.

## 8. Decisions Recorded (forks the review surfaced)

- **Approach → PATH A: single-source + projection** (user decision 2026-06-22, over the cheaper
  "sync-in-place" Path B). Rationale: permanent single-authoring-source (SC1) is worth the
  net-new projector build; accepts the data-flow-inversion cost, resolved via the distinct-canon
  topology in §4.
- **Adversary BLOCKs resolved in-design (not deferred to impl):** B1 (data-flow inversion) → §4
  distinct-canon-path topology; B2 (`==` is Codex-only) → G2 clarification + the per-host SC4
  assertion is the Claude protector; B3 (SC2 circular/content-blind) → SC2 paired with SC5
  content controls.
- **SC2↔SC6 fork → ADOPT-AS-SOURCE** (renderer becomes writer of record), with the
  **replace-not-verbatim** guard (SC2 anti-echo control). Canon at a new path
  (`agent-surfaces/openspec/`), host surfaces become write-only outputs (§4).
- **SC7 → REMOVE all `continue` refs** (creating a `continue` op violates Non-Goal 2).
- **Q3 (overlay representation) → NAMED-SLOT templated-includes** — promoted from a tail
  detail to a gating Task-B decision.
- **Per-op Claude surface:** `propose` = command-only (decided); `apply`/`archive`/`explore`
  evaluated at work-breakdown.
