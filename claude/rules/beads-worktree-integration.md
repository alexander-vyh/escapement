# Beads + Git Worktrees — Global Rule

## Always Use `bd worktree create` Instead of `git worktree add`

When beads is present in a project (`.beads/` directory exists), **always** use `bd worktree create` to create worktrees. This sets up a `.beads/redirect` file so the worktree shares the main repo's Dolt database.

Using bare `git worktree add` in a beads project creates a broken state: the worktree gets an empty `.beads/` directory with no database, `bd` commands fail with "database not found", and `bd init` inside the worktree makes it worse by starting a separate empty Dolt server that shadows the main repo's working database.

## Commands

| Action | Command |
|--------|---------|
| Create worktree | `bd worktree create <path> -b <branch>` |
| Remove worktree | `bd worktree remove <path>` |
| List worktrees | `bd worktree list` |

## Safety Net

The cake repo's `.envrc` exports `BEADS_DIR` pointing to the main repo's `.beads/`. This ensures that even if a worktree is created with plain `git worktree add`, beads commands still find the correct database. But `bd worktree create` is still preferred because it also handles the redirect file.

## If Beads Breaks in a Worktree

1. Stop the local Dolt server: `bd dolt stop`
2. Remove the worktree's `.beads/` directory: `rm -rf .beads/`
3. Verify: `bd count` should show the main repo's issues

Do NOT run `bd init` inside a worktree — this recreates the broken state.
