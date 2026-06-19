# Escapement Core Discipline

- Use `bd` (beads) for all task tracking. Do not use ad-hoc TODO lists.
- Before non-trivial implementation, make the business outcome and the
  independent oracle explicit. Prefer behavioral checks over implementation echoes.
- Never suppress a failure to make it invisible (no blanket skips, `# noqa`,
  `except: pass`, or oracle-weakening). Fix why it fails.
- Verify the real user-facing outcome before declaring work done. "Tests pass"
  counts only when the tests exercise the actual outcome and reject known-bad
  implementations.
- Preserve user work; avoid destructive cleanup without an explicit decision.
- A claim a decision rests on must be marked verified vs. inferred — never assert
  an inference with the confidence of a measured fact.
