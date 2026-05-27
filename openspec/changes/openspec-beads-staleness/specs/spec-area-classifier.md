<!-- Spec: spec-area-classifier -->

## Purpose

Deterministic local-embedding classifier that maps a beads issue's
title+body to a ranked list of matching spec requirements, used by the
reverse-flow gate (deferred) and the drift doctor (deferred) to detect
spec-linkage gaps. This is the walking-skeleton capability whose
performance gates the rest of the feature.

## Requirements

### Requirement: Index spec corpus from openspec directories

The classifier SHALL build an index covering every requirement defined in
`openspec/changes/*/specs/*.md` (active in-flight specs) AND
`openspec/specs/*.md` (post-archive ratified specs, if present). The
index entry for each requirement MUST contain the requirement's text, its
extracted keywords, and a 384-dimensional embedding produced by the
`sentence-transformers/all-MiniLM-L6-v2` model. The index MUST be
persisted to `.beads/.spec-index.json` and keyed by the spec-file mtimes
so that stale entries are detectable.

#### Scenario: A change with one requirement is indexed
- **WHEN** the classifier runs in a repo with exactly one
  `openspec/changes/example-change/specs/example.md` containing exactly
  one `### Requirement: example-requirement` block
- **THEN** `.beads/.spec-index.json` contains exactly one entry whose
  `requirement_id` resolves to the requirement, whose `embedding` has
  length 384, and whose `text` field includes the requirement's
  description

#### Scenario: Multiple specs across changes are merged into one index
- **WHEN** the classifier runs in a repo with three changes each
  containing one requirement
- **THEN** the index contains exactly three entries, each keyed by a
  distinct `requirement_id`, and each entry's `source_path` field
  points to the spec file it came from

### Requirement: Exclude the archive directory

The classifier MUST NOT index any requirement found under
`openspec/changes/archive/**`. Archived *change records* live there, but
their *specs* (when promoted) live in top-level `openspec/specs/` —
treating archived change records as still-spec'd area would generate
false positives forever on every closed bug touching that area. This is
a named, tested invariant.

#### Scenario: Archived change is skipped
- **WHEN** the classifier runs in a repo with a change at
  `openspec/changes/archive/old-feature/specs/old.md` containing a
  requirement
- **THEN** that requirement is NOT present in the resulting
  `.beads/.spec-index.json`

#### Scenario: Active change and archived change side by side
- **WHEN** the classifier runs in a repo with both
  `openspec/changes/active/specs/active.md` and
  `openspec/changes/archive/old/specs/old.md`
- **THEN** the index contains the requirement from `active/specs/`
  but not from `archive/old/specs/`

### Requirement: Score a beads issue against the index deterministically

Given a beads issue's title and body, the classifier SHALL produce a
score in [0.0, 1.0] for each indexed requirement, computed as the cosine
similarity between the issue's embedding (from the same model) and the
requirement's stored embedding. The output JSON MUST include, for every
classification, the matched-requirement IDs above the configured
threshold, their similarity scores, and a human-readable rationale text
naming which requirement keywords or text most contributed.

#### Scenario: Same input yields same output
- **WHEN** the same beads issue text is classified twice against the
  same index on the same machine
- **THEN** the two output JSON results are byte-identical

#### Scenario: Vocabulary-divergent match is detected
- **WHEN** a beads issue titled "Snowflake connection times out" is
  classified against an index that contains a requirement using the
  vocabulary "data ingestion reliability" but no overlapping keywords
- **THEN** the requirement appears in the matched-requirements list
  with a similarity score above 0.5

#### Scenario: Unrelated issue is not matched
- **WHEN** a beads issue titled "Fix typo in README" is classified
  against an index of technical requirements unrelated to documentation
- **THEN** no requirement appears in the matched-requirements list at
  the default threshold (0.6)

### Requirement: Riskiest-assumption corpus accuracy

When the classifier runs against the hand-labeled corpus at
`claude/bin/tests/fixtures/cake-bugs.json` (10 cake bugs: 7 open + 3
closed, each labeled "in spec'd area" or "not in spec'd area" with the
matching `requirement_id` if in), the classifier's accuracy SHALL be
≥9/10 (90%) at the default threshold. The corpus MUST include at least
3 cases where the bug and the matching requirement use *different
vocabulary* — that paraphrase-diversity criterion ensures the
embedding approach is actually validated against the failure mode that
rules out a keyword-only classifier.

#### Scenario: Corpus accuracy meets the bar
- **WHEN** `python3 claude/bin/classify_bugs.py
  --corpus claude/bin/tests/fixtures/cake-bugs.json` runs
- **THEN** the output JSON reports `accuracy >= 0.9` AND at least 3 of
  the correctly-classified "in" cases involve bug-requirement pairs
  where the bug title shares zero keyword tokens with the requirement's
  `## Purpose` text

#### Scenario: Misclassification is auditable
- **WHEN** the classifier misclassifies a bug
- **THEN** the rationale field on that bug's output JSON entry names
  which requirement was the next-closest match and what its similarity
  score was, so the user can see what the classifier was "thinking"

## Deferred capabilities (post-skeleton validation)

The following capabilities are described in `design.md` Future
Increments and have specs DEFERRED until the walking-skeleton's
riskiest-assumption test passes:

- `reverse-flow-gate` [DEFERRED: pending skeleton validation]
- `spec-drift-doctor` [DEFERRED: pending skeleton validation]
- `commits-without-beads-audit` [DEFERRED: pending skeleton validation]
- `waiver-mechanism` [DEFERRED: pending skeleton validation]
- `learning-loop` [DEFERRED: pending skeleton validation]
