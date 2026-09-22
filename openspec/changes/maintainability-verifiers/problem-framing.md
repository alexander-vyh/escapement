# Problem Framing — maintainability-verifiers

## Problem

Escapement's own repository is accumulating rework rather than architecture rot.
Measured over 325 non-merge commits (2026-04-17 → 2026-09-18):

- Fix-commit share rose 17% (May) → 23% (Jun) → 52% (Jul) → 59% (Aug) → 70% (Sep).
- Of 263 repair-touches on source files, **49% repair code changed within 24 hours**
  and 68% within 7 days.
- Real intra-tree co-change coupling is flat (~2 source files per commit, p90 3–7).
  The apparent per-commit spread increase came from the generated `plugins/**` trees,
  not from design decay.
- Nothing in the repository has ever proven that a test failed before its fix.
  `tdd-gate.py` only checks that test files were *touched* first (severity `ask`);
  `oracle_strength_diff.py` deliberately dropped its blocking tier; formulas request
  a failing test in prose only.
- No signal attributes post-landing repair back to the change or molecule that caused
  it, so the loop cannot learn which landings were defective.

The repository declares `auto_merge_on_green: true` with
`intended_outcome: merged-and-deployed`, while `repo_outcome.authorizes_auto_merge`
never observes check status. Work therefore lands with neither a human diff read nor a
mechanically verified green.

**Corrected during design (2026-09-22):** an earlier reading of this evidence claimed
the 275 duplicated files under `plugins/**` were hand-synced, and proposed generating
them. That was wrong. `tools/render_agent_surfaces.py:663-703` already vendors hooks,
skills, commands, agents, rules and `harness/bin` into all three plugin trees, and
`.github/workflows/tests.yml:52` runs its `--check` drift mode in CI. The duplication
is a committed build output of a `git-subdir` distribution, costs one edit rather than
four, and is already enforced. It inflates per-commit file counts and nothing else. No
work is needed there; the measurement simply has to exclude it, which it now does.

## Why now

Rework is now the majority commit class and still rising, and the owner has ruled out
human diff review as the control. The controls that remain must be mechanical, and the
cheapest of them (an executed negative control) does not exist yet. Every other oracle
gate already shipped — `implementation_echo_test_gate`, `outcome_assertion_gate`,
`magic_number_echo` — sits downstream of tests that have never been proven non-vacuous.

## Decision authority

alexander-vyh, repo owner. Sole authority for the *what* and *why*.

## Behavioral population

Agent sessions landing changes in Escapement-governed repositories (Claude, Codex, Pi)
must clear the new landing check and will be denied or asked when a change carries no
test that failed pre-patch. Secondary: the repo owner, who continues to review
structural design (tracked as a separate P1 research bead) but does not read diffs.

## Riskiest assumption + liveness

We are betting that **"did any changed test fail against pre-patch production code?" is
mechanically decidable per change, cheaply enough to run at landing, without false-firing
on honest changes that legitimately carry no new failing test** (refactors, generated
surfaces, docs, config).

Wrong when a replay over this repository's 325-commit history either blocks a majority of
honest landings, or passes the commits that were repaired within 24 hours.

Known within ~2 weeks by replaying the check over that history and comparing its verdicts
against the observed repair-within-24h outcome.

## Success criteria

1. Every landing in a governed repo either carries a test demonstrably failing against
   pre-patch code, or a recorded, human-readable waiver naming why none applies.
2. The repair-within-7d share of source touches (currently 27%, 529 of 1,940) is
   *measured continuously* and attributed to landings. **Revised 2026-09-22:** this was
   originally written as "declines," with the pre-patch check as the mechanism. The
   skeleton replay falsified that link — a weak oracle predicts repair at 11% versus
   47.5% when a changed test genuinely detected the change. No mechanism in this change
   is expected to move the rate, so claiming the decline as a success criterion would be
   unfalsifiable credit-taking. The rate stays as the instrument any future candidate
   mechanism is judged against.
3. The repair ledger attributes each repair to the landing that induced it, so the
   question "which landings cost the most afterwards" is answerable from data rather
   than from recollection.
