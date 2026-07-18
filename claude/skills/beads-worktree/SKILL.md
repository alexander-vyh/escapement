---
name: beads-worktree
description: Use when creating, removing, or listing git worktrees in a project that uses beads (a `.beads/` directory exists), or when tracker resolution needs checking inside a worktree. Explains why new worktrees use `bd worktree create` instead of `git worktree add`, and how Beads 1.0.5 shares state through Git's common directory.
---

# Beads + Git Worktrees

In a project with a `.beads/` directory, **create new worktrees with
`bd worktree create`, not `git worktree add`.** This keeps creation on the
repository-managed path and lets the location guard prevent indexers from
scanning an unignored worktree. A `PreToolUse` hook,
`beads_worktree_guard.py`, enforces that creation rule.

## Existing linked worktrees

Beads 1.0.5 resolves a linked worktree's tracker through Git's common
directory; a `.beads/redirect` file is not required. Once a linked worktree
exists, normal Git operations such as commit, push, merge, and rebase must be
allowed. Check its state with:

```bash
bd worktree info
git rev-parse --path-format=absolute --git-common-dir
bd show <known-issue-id>
```

The last command should return the same issue state from the primary checkout
and the linked worktree. **Do not run `bd init` inside a worktree.**

## Commands

| Action | Command |
|--------|---------|
| Create worktree | `bd worktree create <path> -b <branch>` |
| Remove worktree | `bd worktree remove <path>` |
| List worktrees | `bd worktree list` |

## If tracker resolution fails

1. Run `bd worktree info` from the linked worktree and inspect the reported
   main repository.
2. Compare `bd show <known-issue-id>` from the linked worktree and primary
   checkout.
3. If the results differ, stop and investigate the actual Beads/Git layout;
   do not create a new database with `bd init` or remove `.beads/` blindly.
