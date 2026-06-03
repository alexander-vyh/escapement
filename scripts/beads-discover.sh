#!/usr/bin/env bash
# beads-discover.sh — print the canonical list of beads repos to back up.
#
# A .beads dir qualifies ONLY if:
#   • its repo is a PRIMARY git checkout (.git is a directory) — excludes git
#     worktrees and submodules, whose .git is a FILE and whose beads data is
#     shared with / duplicated from the primary repo;
#   • the .beads sits at the repo's git toplevel — excludes nested .beads dirs
#     left in subdirectories (openspec/, tools/, data folders);
#   • it holds real data — a Dolt DB (.beads/dolt) OR a non-empty issues.jsonl.
#
# Prints one absolute repo path per line. SHARED by the backup and the verify
# oracle so the "discovered" set is identical for both (no coverage drift).
set -uo pipefail
SEARCH_ROOTS=("${BEADS_BACKUP_ROOTS:-$HOME/GitHub}")

find "${SEARCH_ROOTS[@]}" -type d -path '*/.beads' -prune 2>/dev/null | sort | while IFS= read -r b; do
  repo="$(dirname "$b")"
  [ -d "$repo/.git" ] || continue                                          # primary repo only
  [ "$(git -C "$repo" rev-parse --show-toplevel 2>/dev/null)" = "$repo" ] || continue  # toplevel only
  if [ -d "$b/dolt" ] || [ -s "$b/issues.jsonl" ]; then                    # has real data
    printf '%s\n' "$repo"
  fi
done
