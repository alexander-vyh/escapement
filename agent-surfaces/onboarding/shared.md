# Escapement Shared Workflow

Escapement is the host-neutral workflow layer for agentic coding sessions. Claude
Code and Codex are adapters over the same underlying practices: beads for work
state, OpenSpec for design/spec artifacts, test-oracle discipline for
implementation, and the continuation harness for verified outcomes.

The host adapter may change which hooks, tools, and config files are available.
The workflow invariants do not change:

- use `bd` for task tracking;
- make outcome and oracle explicit before non-trivial implementation;
- prefer behavioral checks over implementation echoes;
- verify the real user-facing outcome before closing work;
- preserve user work and avoid destructive cleanup without an explicit decision;
- keep files under 500 lines (complexity proxy); a PreToolUse hook enforces this globally — extract a cohesive responsibility into a sibling module when approaching the limit.
