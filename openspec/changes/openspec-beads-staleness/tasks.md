# Walking skeleton tasks — openspec-beads-staleness

Walking skeleton ONLY. Future-increment tasks (reverse-flow gate hook,
drift-doctor, commits-without-beads audit, waiver mechanism, learning
loop) are listed as deferred in `design.md` and produce no tasks here.

## 1. Build the spec-index prototype

- [ ] 1.1 **Write `claude/bin/spec_index_build.py`** that walks
  `openspec/changes/*/specs/*.md` (excluding `archive/`) and
  `openspec/specs/*.md`, parses every `### Requirement: <name>` block
  (capturing the requirement name, `## Purpose` text, and any
  `#### Scenario:` keyword tokens), embeds the combined text with
  `sentence-transformers/all-MiniLM-L6-v2`, and persists the result to
  `.beads/.spec-index.json` keyed by spec-file mtimes.
  (spec: *Index spec corpus from openspec directories*)
  **Verify:** running the script in this repo produces a file at
  `.beads/.spec-index.json` such that
  `jq -e '.requirements | length >= 1 and all(.[]; .embedding | length == 384)'`
  exits 0.

- [ ] 1.2 **Implement and test the archive-exclusion invariant.**
  Construct a fixture under `claude/bin/tests/fixtures/archive_exclusion/`
  containing one active change and one archived change, each with one
  requirement. Run `spec_index_build.py` against the fixture and assert
  the resulting index contains exactly one entry, sourced from the
  active change.
  (spec: *Exclude the archive directory*)
  **Verify:** `python3 claude/bin/tests/test_archive_exclusion.py` exits
  0; the test fails if the archive's requirement ever appears in the
  index.

## 2. Build the bug-classifier and run the riskiest-assumption test

- [ ] 2.1 **Hand-label the cake bug corpus.** Create
  `claude/bin/tests/fixtures/cake-bugs.json` containing 10 cake bugs
  (7 currently open + 3 closed) with structured labels:
  `{bug_id, title, body, expected_classification, expected_requirement_ids[]}`.
  At least 3 of the labeled "in spec'd area" cases MUST involve a bug
  whose title shares zero keyword tokens with the matched
  requirement's `## Purpose` text (the paraphrase-diversity criterion).
  Document the labeling rationale in a sidecar
  `cake-bugs.labels-rationale.md`.
  (spec: *Riskiest-assumption corpus accuracy* — corpus construction)
  **Verify:** `jq -e '. | length == 10 and ([.[] | select(.expected_classification == "in" and (.title | ascii_downcase | split(" ")) as $bt | .expected_requirement_ids | length > 0)] | length >= 3)' claude/bin/tests/fixtures/cake-bugs.json` exits 0.

- [ ] 2.2 **Write `claude/bin/classify_bugs.py`** that loads the index
  produced in 1.1, embeds each bug's title+body, scores against every
  indexed requirement via cosine similarity, classifies each bug at
  threshold 0.6, and emits a JSON report per bug containing
  `{bug_id, classification, score, matched_requirements[], rationale}`.
  Include an `--corpus` flag that runs against the hand-labeled fixture
  and reports overall accuracy + per-bug correctness.
  (spec: *Score a beads issue against the index deterministically*)
  **Verify:** `python3 claude/bin/classify_bugs.py --corpus claude/bin/tests/fixtures/cake-bugs.json`
  prints `accuracy >= 0.9` AND the JSON output's rationale field for
  every "in" classification names the top-matched requirement IDs.

- [ ] 2.3 **Test determinism.** Run `classify_bugs.py` twice in
  succession on the same fixture; diff the outputs.
  (spec: *Score a beads issue against the index deterministically* —
  scenario "Same input yields same output")
  **Verify:** `diff <(python3 classify_bugs.py --corpus ... 2>/dev/null)
  <(python3 classify_bugs.py --corpus ... 2>/dev/null)` produces zero
  bytes of output.

## What this validates

Completion of all three tasks validates (or invalidates) the riskiest
assumption stated in `design.md`: that a deterministic local-embedding
classifier can correctly classify ≥90% of cake's real bugs as "in
spec'd area" or "not in spec'd area" without an LLM call. If accuracy
≥0.9: future increments unlock (reverse-flow gate, drift-doctor,
waiver, learning loop, cross-repo deployment). If accuracy <0.9: the
documented fallback per `design.md` is nudge-only on reverse flow with
the forward flow remaining the only deterministic gate.
