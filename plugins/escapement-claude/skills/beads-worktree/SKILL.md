---
name: beads-worktree
description: Use when creating, removing, or listing git worktrees in a project that uses beads (a `.beads/` directory exists), or when `bd` commands fail inside a worktree ("database not found", empty `.beads/`, or a worktree's bd seems to have its own separate issues). Explains why `bd worktree create` is required instead of `git worktree add`, and how to recover a worktree that was created the wrong way.
---

# Beads + Git Worktrees

In a project with a `.beads/` directory, **always create worktrees with
`bd worktree create`, never `git worktree add`.** `bd worktree create` writes a
`.beads/redirect` file so the new worktree shares the main repo's Dolt
database. (A `PreToolUse` hook, `beads_worktree_guard.py`, also enforces this
mechanically — it denies `git worktree add` in beads projects and redirects you
here.)

## Why `git worktree add` breaks beads

A bare `git worktree add` in a beads project creates a broken state:

- the worktree gets an empty `.beads/` directory with no database;
- `bd` commands fail with "database not found";
- running `bd init` to "fix" it makes things worse — it starts a separate empty
  Dolt server that shadows the main repo's working database.

## Commands

| Action | Command |
|--------|---------|
| Create worktree | `bd worktree create <path> -b <branch>` |
| Remove worktree | `bd worktree remove <path>` |
| List worktrees | `bd worktree list` |

## Safety net

Some repos (e.g. cake) export `BEADS_DIR` in `.envrc`, pointing at the main
repo's `.beads/`. That lets `bd` find the right database even if a worktree was
created with plain `git worktree add` — but `bd worktree create` is still
preferred because it also writes the redirect file.

## If beads already broke in a worktree

1. Stop the local Dolt server: `bd dolt stop`
2. Remove the worktree's `.beads/` directory: `rm -rf .beads/`
3. Verify: `bd count` should show the main repo's issues.

**Do NOT run `bd init` inside a worktree** — that recreates the broken state.
