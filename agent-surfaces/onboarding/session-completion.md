# Session Completion

Prefer a feature branch plus PR for repo changes. Do not push an ephemeral branch
unless the user or orchestrator explicitly authorizes it.

Before reporting completion:

1. Close or update completed beads.
2. Run the relevant tests, linters, or generated-surface checks.
3. Check `git status`.
4. Report remaining residue with a concrete owner or decision.

Do not ask whether to stop, keep going, wrap, pause, or call the current state a
stopping point. If there is a next in-scope action, take it. If the outcome is
verified, state the verified result. If a real blocker prevents progress, name
the blocker and the exact decision or access needed.

Work is complete only when the requested outcome is verified end to end and any
remaining residue is intentional.
