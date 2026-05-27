# openspec-beads-staleness — design

## Problem Statement

After this work, when a Claude Code agent closes a bug or completes a chore
in a spec'd code area in a repo that uses openspec + beads, the agent is
mechanically prompted to either link the bead to the relevant spec
(`--spec-id`) or to record an explicit waiver with a documented reason. The
0/7 spec-id rate on cake's open bugs and 4/50 rate across open tasks (measured
2026-05-26) ceases to be invisible. Spec drift between code reality and the
specs that describe it becomes detectable on demand and mechanically harder
to introduce silently.

## Strategic Alternatives

Two paths were considered and rejected before settling on this design.

1. **Do nothing / continue rules-only enforcement.** Keep relying on the
   `discovery` skill, the `planning-discipline` rule, and agent attention.
   Rejected: the data shows the unprompted compliance rate is approximately
   zero. The rules-only approach has been observable for months and
   demonstrably failed to produce linkage. Continuing it produces the same
   result.
2. **LLM-judge classifier at gate time.** A per-`bd close` Haiku call
   comparing the bead's title+body against the spec corpus, with the model
   deciding "in spec'd area" or not. Rejected because: (a) per-call cost
   compounds across every close; (b) non-deterministic decisions in a gate
   path produce flaky enforcement; (c) the harness principle is deterministic
   tooling for behavioral gates; (d) LLM judges carry their own
   paraphrase-fragility shape — different mistakes, same class.
3. **Manual quarterly audit by Alexander.** Rejected: doesn't scale across
   the 9 user repos that use openspec+beads, drift accumulates between
   audits, and it doesn't change agent behavior at the point of bead-close.

## Non-Goals

1. **Won't validate specs against source code.** This work detects bead↔spec
   linkage drift, not code↔spec drift. If a spec says "auth requires MFA"
   and the code drops MFA without updating the spec, this feature won't
   catch it — that is `openspec validate`'s domain, separately.
2. **Won't deploy a coercive pre-commit hook for commits-without-beads.**
   The commits-without-beads audit (a planned post-skeleton increment) is
   *sumo wrestler*–shaped per the principle file: a periodic audit that
   files a remediation bead, not a `git commit` blocker. Pre-commit blocking
   is explicitly out of scope.
3. **Won't require the `openspec` binary at gate time.** Gates read the
   filesystem (markdown files under `openspec/changes/*/specs/` and
   `openspec/specs/`) directly. The binary is needed for authoring, not for
   gate execution.
4. **Won't require an LLM call at gate time.** The classifier is local
   sentence-transformer embeddings with deterministic cosine-similarity
   scoring. Same input → same output, every time.
5. **Won't auto-write specs.** When a bead is missing a `--spec-id`, the
   gate prompts the user to link or waive. It does not infer and write
   spec content automatically — that would conflict with the discovery
   skill's authorship model.

## Capabilities

### New Capabilities

- `spec-area-classifier` — deterministic local-embedding scorer that maps a
  bead's title+body to a ranked list of matching spec requirements
- `reverse-flow-gate` — PreToolUse hook on `bd close` that consults the
  classifier and prompts for `--spec-id` link or `--spec-waiver` reason when
  a bug is in a spec'd area
- `spec-drift-doctor` — on-demand audit command walking all open issues,
  classifying each, and reporting the spec-linkage gap
- `commits-without-beads-audit` — scheduled / on-demand audit that walks
  recent git commits, identifies commits with no bead reference, and files a
  remediation bead
- `waiver-mechanism` — explicit `--spec-waiver "<reason>"` flag with a
  ≥20-character free-text requirement; reason text becomes labeled training
  data
- `learning-loop` — waivers (false positives), manual `--spec-id` links
  (confirmed matches), and PR/file-overlap (auto-positive) feed back into
  the classifier's threshold + labeled corpus

### Modified Capabilities

None mechanically. This work is additive. Depends on prerequisite kaizen
change `fix-discovery-gate-directory` (shipped 2026-05-26, commit
`3f8d37b`) — without it the forward-flow gate is broken regardless of
what this design adds on the reverse flow.

## Impact

- **New hooks** under `claude/hooks/` for the reverse-flow gate
- **New scripts** under `claude/bin/` (or `harness/`) for the classifier,
  drift-doctor, and commits-without-beads audit
- **New cache file** `.beads/.spec-index.json` per repo, invalidated by
  spec-file mtime
- **Modified `~/.claude/settings.json`** — adds a PreToolUse hook entry for
  `bd close`. Existing entries unchanged.
- **New Python dependency** — `sentence-transformers` (~80MB CPU model on
  first run, cached locally)
- **No changes to beads** — reads `bd show --json` output, doesn't write
- **No changes to openspec** — reads filesystem structure

## Riskiest Assumption

**We believe** a deterministic local-embedding classifier over the spec
corpus can correctly classify ≥90% of cake's hand-labeled bugs (a corpus
of 10 bugs explicitly including paraphrased / cross-domain cases) as "in
spec'd area" or "not in spec'd area" without an LLM call at gate time.

**We will know this is true when**, against a hand-labeled corpus where
labels are written *before* the classifier runs, accuracy is ≥9/10 (90%)
AND the corpus includes at least 3 cases where the bug and the matching
requirement use *different vocabulary* (e.g., a bug titled "Snowflake
connection times out" against a requirement that says "data ingestion
reliability"). That paraphrase-diversity criterion forces the embedding
approach to do real work beyond keyword overlap.

**If false**, we fall back to nudge-only on the reverse flow (ask, don't
deny); keep the forward flow as the deterministic gate; document why
embedding-classification was insufficient. The forward-flow protection is
unaffected by this assumption.

**Embedded alternative (rejected):** an LLM-judge classifier (single Haiku
call per `bd close` comparing the bead to requirement summaries). Specific
enough to build if the riskiest assumption fails: ~200-line script using
the Anthropic SDK with per-bead caching keyed on bead-text hash. Rejected
for the reasons stated under Strategic Alternatives above.

## Walking Skeleton

Two tasks, ~45-60 min each, that test the riskiest assumption end-to-end.
The reverse-flow gate hook, drift-doctor, commits-without-beads audit,
waiver mechanism, and learning loop are all *post-skeleton increments*
purchased by skeleton validation.

1. **`build-spec-index`** (~45 min). Python script
   `claude/bin/spec_index_build.py`:
   - Walks `openspec/changes/*/specs/*.md` (excluding `archive/` directory
     — named tested invariant) AND `openspec/specs/*.md` (if exists)
   - Parses each `### Requirement:` block; extracts `requirement_id`,
     `## Purpose` text, scenario keywords
   - Embeds each requirement's combined text using
     `sentence-transformers/all-MiniLM-L6-v2`
   - Writes `.beads/.spec-index.json` with
     `{requirement_id: {text, keywords, embedding}}` keyed by spec-file mtimes
   - **Verify:** `python3 claude/bin/spec_index_build.py && jq -e '.requirements | length >= 1 and all(.[]; .embedding | length == 384)' .beads/.spec-index.json`

2. **`classify-bug-corpus`** (~60 min). Python script
   `claude/bin/classify_bugs.py`:
   - Takes the index + hand-labeled corpus
     `claude/bin/tests/fixtures/cake-bugs.json` (10 bugs: 7 of cake's open
     bugs + 3 random closed; hand-labeled with expected in/out + matching
     `requirement_id`s; corpus includes ≥3 paraphrased/cross-domain cases)
   - For each bug: embed title+body, score against each indexed requirement,
     classify as in/out at threshold 0.6 (tunable)
   - Output JSON: `{bug_id, classification, score, matched_requirements[], rationale_text}` — human-inspectable in seconds
   - **Verify:** accuracy ≥ 9/10 against hand labels AND rationale surfaces
     the matched requirement IDs for every "in" classification

Cutting test: this is the minimum that proves OR disproves the riskiest
assumption. Anything more — the gate hook, the drift command, the
commits-audit, the waiver field — is post-skeleton.

## Proof of Delivery

This is done when `python3 claude/bin/classify_bugs.py` against cake's 10
hand-labeled bugs reports accuracy ≥90%, AND every classification's
rationale (matched requirement IDs + similarity scores) is inspectable
from the output JSON in seconds, not minutes — so the user can audit a
specific decision before the gate ever blocks them.

## Anti-Metrics

1. **Mock bureaucracy (Wiesche, Schermann & Krcmar, 2013).** Agents
   satisfy the gate symbolically — fake `--spec-id` values pointing at
   non-existent requirements, throwaway waiver reason text matching
   patterns like "TBD", "n/a", < 20 chars, or repeating the bead title.
   Measured: percentage of `--spec-id` values that don't resolve to an
   indexed requirement; percentage of waiver-reasons failing the
   minimum-substance check. Either >5% in any 30-day window is failure.
   *This is the headline anti-metric.* Even an enabling-by-design gate
   can produce mock bureaucracy per Wiesche; we explicitly instrument
   against it.
2. **Per-`bd close` latency > 200ms** with cache warm. The classifier
   reads the cached `.spec-index.json` and embeds one bead's text. Above
   200ms steady-state, agents perceive workflow drag and route around the
   gate.
3. **Waiver count > `spec_id` link count after 30 days of enforcing
   mode.** If more bugs are waived than linked, either the classifier is
   wrong (false-positive heavy) or the friction is misallocated. Either
   way, the loop isn't closing.
4. **Classifier accuracy on real traffic drops below 75% within 30 days
   of enforcement.** Hand-labeled corpus said 90%; if real traffic shows
   below 75%, the corpus didn't represent real bugs and the riskiest
   assumption was tested on the wrong data — that's a failure regardless
   of whether the original skeleton verification passed.

## Decisions

1. **Deterministic local-embedding classifier.** Filesystem read +
   `sentence-transformers/all-MiniLM-L6-v2` (~80MB CPU model,
   ~5-20 ms/encode) + cosine similarity. Same input → same output. No
   network call. Alternatives: keyword/BM25 matching (rejected — fails
   on paraphrase, fails the riskiest-assumption test by construction);
   LLM-judge (rejected — non-deterministic, costly, paraphrase-fragile
   in its own shape); per-requirement hand-curated regex (rejected —
   high authoring cost, doesn't scale).

2. **Two source directories, semantic distinction (not the dual-source
   anti-pattern).** Gate scans `openspec/changes/*/specs/*.md` (active
   in-flight specs) AND `openspec/specs/*.md` (post-archive ratified
   specs, currently empty in cake — verified 2026-05-26). These are
   lifecycle stages, not parallel sources of truth.

3. **`archive/**` exclusion is a named, tested invariant.** Adversary
   panel flagged this as the single most load-bearing invariant —
   archived *change records* live under `openspec/changes/archive/`
   while their *specs* (if promoted) live in top-level `openspec/specs/`.
   Treating archived change records as still-spec'd area would generate
   false positives forever on every closed bug touching that area.
   Explicit unit test required in the skeleton.

4. **Shadow mode before enforcing mode.** Per the bureaucracy principle
   (`claude/rules/delicate-art-of-bureaucracy.md`), Operating Rule 3:
   design intent does not survive implementation. The reverse-flow gate
   ships in shadow mode (logs decisions to a side channel, does not
   deny) for ≥48 hours of real traffic. Threshold and message language
   calibrate from observed FP rate. Then flip to enforcing. Per Shook
   2010: behavior precedes belief — ship the observer first.

5. **Waiver follows the standard convention in
   `claude/rules/gate-design.md` Rule 1.** Flag shape `--spec-waiver
   "<reason>"`, reason required ≥20 characters, null patterns rejected
   (`TBD`, `n/a`, whitespace-only, bead-title echo). Reason text
   persists to `.beads/.gate-signal.jsonl` via the shared signal store
   (change `gate-signal-persistence-foundation`), where it accumulates
   as labeled training data for the learning loop. This change does
   NOT define a private waiver convention — it adopts the standard
   one so the user can grep one file instead of N.

6. **Commits-without-beads is sumo-wrestler-shaped, not coercive.** Per
   principle file Operating Rule 5: "coercion is a smell, not a
   strategy." Implementation: an on-demand or scheduled audit that walks
   recent git commits, identifies those with no bead reference in the
   commit message or branch name, and files a single remediation bead
   per audit run. Uses bd's existing weight rather than adding a new
   pre-commit blocker. The audit is enabling (it points the user at the
   gap), not coercive (it doesn't block work in flight).

7. **Internal-transparency in every denial message.** Per principle file
   Design Feature 2: the denial includes (a) the matched requirement
   IDs, (b) the classifier's confidence score, (c) two paths forward
   (link or waive), and (d) the exact commands to take each path.

8. **Depends on two prerequisite changes.**
   - `fix-discovery-gate-directory` (shipped 2026-05-26, commit
     `3f8d37b`) — unblocks the forward-flow gate that was previously
     denying every `bd create --type=feature` in this repo.
   - `gate-signal-persistence-foundation` (in flight, openspec change
     of same name) — provides the `.beads/.gate-signal.jsonl` store
     and the `_gate_signal.record()` API the learning-loop future
     increment consumes. The walking skeleton of this change does not
     depend on it (it just tests classifier accuracy on a hand-labeled
     corpus); the post-skeleton increments (reverse-flow gate, waiver
     mechanism, learning loop) all do. Build order: signal-persistence
     foundation ships first, then this change's increments adopt it.

## Risks & Trade-offs

- **Riskiest-assumption failure** (classifier can't hit 90%) →
  Documented fallback: nudge-only reverse flow, forward flow stays
  deterministic. Embedded alternative (LLM-judge) is specified above if
  the deterministic-only constraint relaxes.
- **`sentence-transformers` adds 80MB on first install** → Accepted.
  Model cached locally; ~5-20ms per encode steady-state stays well
  inside the 200ms anti-metric.
- **Parser coupling to `### Requirement:` block format** → Mitigation:
  JSON-schema-validate the parser's input. If openspec changes the spec
  schema, the index build fails loudly at rebuild time, not silently at
  classification time. (Operating Rule 1: every rule has a half-life;
  parser brittleness is one of the rule's surfaces.)
- **Mock bureaucracy** — agents waive everything → Mitigation:
  anti-metric #1 instruments this directly. Periodic user audit of
  waiver reasons. Wiesche's finding (both enabling and coercive designs
  can produce mock bureaucracy) means we cannot rely on enabling-design
  alone to prevent it.
- **`openspec/specs/` doesn't exist in cake yet** (verified 2026-05-26
  — no `openspec archive` has run there) → Accepted: skeleton tests
  against `openspec/changes/*/specs/` only. The `openspec/specs/` reader
  is wired in; corpus extension to post-archive specs is a separate
  validation when archiving begins.
- **Threshold tuning trade-off** — too aggressive yields false positives
  (developer friction → workaround); too permissive yields false
  negatives (stale specs slip through) → Accepted: ship at conservative
  threshold (0.6), lower as waiver-reason corpus accumulates and shows
  the boundary empirically.

## Future Increments

`[PLACEHOLDER]` — purchased only by walking-skeleton validation.

1. **Reverse-flow gate hook** (`claude/hooks/reverse_flow_spec_gate.py`)
   — wraps the classifier as a PreToolUse hook on `bd close`. Ships in
   shadow mode first; ≥48h of observation; calibrate threshold; then flip
   to enforcing.
2. **`bd doctor --check=spec-staleness`** — on-demand audit walking all
   open issues, classifying each, reporting the linkage gap. Output is a
   structured report, not a gate.
3. **Waiver field schema** — `spec_waiver_reason` bead field with
   ≥20-character substance requirement; `bd waiver list` audit command
   showing all waivers + reasons in a window.
4. **Commits-without-beads scheduled audit** — walks recent git commits,
   identifies those without bead reference, files one remediation bead
   per audit run. Cron-scheduled (e.g., weekly) and on-demand.
5. **Learning loop** — waivers (false positives), manual `--spec-id`
   links (confirmed matches), PR/file overlap (auto-positive signal)
   accumulate into a labeled corpus. Sklearn logistic regression on top
   of embedding similarity + structural features. Threshold tuned from
   accumulated labels rather than initial guess.
6. **Cross-repo deployment** — once cake validates, deploy to the 8
   other openspec+beads repos: crowdstrike-py, investigation,
   llm_gateway, kawa, reticle, sifi_web_app, eng-fin-review, plus any new
   ones the user adds.
7. **Code-touch linkage signal** — extend the classifier's input
   features to include which files the related PR/commit touched (via
   `git log --name-only` lookup), not just bead title+body. Requires git
   integration; post-MVP.
