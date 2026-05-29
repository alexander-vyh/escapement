# Project Instructions for AI Agents

This file provides instructions and context for AI coding agents working on this project.

## Vocabulary

Foundational terms for this repo's workflow system — multi-agent organization, beads,
molecules, the continuation-harness, gate/bureaucracy design, oracles — are defined and
anchored to their base principles in [`docs/VOCABULARY.md`](docs/VOCABULARY.md). Consult
it when a term is unclear; it is the single source of truth when local vocab sections drift.

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:7510c1e2 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/SYNC_CONCEPTS.md for details and anti-patterns.

## Session Completion

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File issues for remaining work** - Create issues for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **PUSH TO REMOTE** - This is MANDATORY:
   ```bash
   git pull --rebase
   git push
   git status  # MUST show "up to date with origin"
   ```
5. **Clean up** - Clear stashes, prune remote branches
6. **Verify** - All changes committed AND pushed
7. **Hand off** - Provide context for next session

**CRITICAL RULES:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- NEVER say "ready to push when you are" - YOU must push
- If push fails, resolve and retry until it succeeds
<!-- END BEADS INTEGRATION -->


## Guiding Principle: This Repo IS a Bureaucracy

This repo's hooks, skills, rules, and harnesses are a structured set of routines
that turn problem-solving successes into reusable practice. That makes the repo
a *bureaucracy* in Schwartz's sense — and bureaucracies decay in predictable
directions (bloated, petrified, coercive, mock) unless designed to stay
**lean, learning, and enabling**.

Every gate, hook, rule, and skill in this repo must pass the four Adler & Borys
(1996) design tests: **repair**, **internal transparency**, **global
transparency**, **flexibility**. A gate that fails one of these tests is
designed for compliance, not for the work the compliance is supposed to enable.

See `claude/rules/delicate-art-of-bureaucracy.md` for the full rule, the four
operational tests, the four failure modes, and the citation lineage. This is a
load-bearing principle for every design decision in this repo.

## Build & Test

_Add your build and test commands here_

```bash
# Example:
# npm install
# npm test
```

## Architecture Overview

_Add a brief overview of your project architecture_

## Conventions & Patterns

_Add your project-specific conventions here_
