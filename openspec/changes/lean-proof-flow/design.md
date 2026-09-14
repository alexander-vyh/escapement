## Context

Three existing owners already perform the relevant work: the behavioral-oracle skill reviews test plans, the Beads execution skill dispatches spec review, and the worktree finisher computes a cleanup decision from Git and GitHub. The gaps are local: the oracle review does not require a constructible acceptance path, the reviewer is primed with the implementer's report, and the finisher discards fields from a `preserve` decision when converting it to `pending`.

The change must remain net-simple. Current sources of truth and lifecycle boundaries stay in place.

## Goals / Non-Goals

**Goals:**

- Make acceptance review reject an outcome that cannot be traced from a literal input through a public path to a final observation.
- Let the spec reviewer form its first verdict from requirements and repository evidence before seeing the implementer's claims.
- Return cleanup evidence already computed for a preserved worktree.
- Preserve existing successful paths and generated/package parity.

**Non-Goals:**

- Adding a gate, ledger, schema, CLI, agent role, classifier, or persistent state type.
- Claiming that in-session agent review is an independent authority boundary.
- Adding owner or next-action taxonomies to cleanup results.
- Expanding cleanup beyond the existing safe-removal transaction.

## Decisions

### Strengthen the existing oracle review in prose

The behavioral-oracle skill will require the reviewer to name the literal fixture or input, the public entry point, and the final observable assertion for each acceptance outcome. An unconstructible path fails review. This belongs beside the existing negative control, positive control, and fragile-implementation challenge; no separately parsed field or hook is added.

### Review in two passes

The spec-review prompt will initially contain the requested behavior plus the exact implementer worktree path and base/head revisions, but not the implementer's report. The reviewer records a first verdict from that immutable diff and repository evidence rather than the coordinator's baseline checkout. Only then does the coordinator provide the report for a discrepancy check. This changes ordering rather than adding another reviewer or artifact. Where an independently authored requirement or prior behavior is unavailable, the review remains useful but must not be described as independent verification.

### Preserve, do not re-model, cleanup evidence

`with_safe_removal` already returns repository, worktree, branch, candidate SHA, disposition, health, and reason for preserved work. `finish_lifecycle` will persist its existing pending receipt and return those fields with `status: pending` rather than replacing them with a smaller object. Other pending and completed results keep their current behavior.

## Risks / Trade-offs

- **Instruction-only acceptance review can still be performed poorly.** -> Keep the claim advisory and verify it with a planted unconstructible acceptance case; do not add a semantic-looking parser.
- **Two-pass review costs one additional message to the same reviewer.** -> Reuse the existing reviewer and make the second pass a short discrepancy check; do not dispatch another agent.
- **Pending JSON gains additive fields for one path.** -> Preserve existing `status`, `reason`, and `lifecycle_id` so consumers remain compatible.
- **Packaged skill copies can drift.** -> Update their existing owners and run the repository's generated/package parity checks.

## Migration Plan

No data migration is required. Rollback is a normal code revert because no new persistent format or authority is introduced.

## Open Questions

None.
