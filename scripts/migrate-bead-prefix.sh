#!/usr/bin/env bash
# One-off migration: rename the beads issue prefix
#   claude-workflow-setup-  ->  escapement-
# to match the repo name, PRESERVING readable suffixes and molecule hierarchy
# (e.g. claude-workflow-setup-egc -> escapement-egc;
#       claude-workflow-setup-mol-5s2 -> escapement-mol-5s2;
#       claude-workflow-setup-fxh.3 -> escapement-fxh.3).
#
# WHY NOT `bd rename-prefix escapement --repair`:
#   The DB has two DETECTED prefixes (claude-workflow-setup + claude-workflow-setup-mol,
#   an artifact of the molecule IDs). rename-prefix then forces --repair, which
#   RE-IDs every issue to a RANDOM HASH (escapement-791c3ebf), destroying readable
#   suffixes and molecule parent/child structure. Per-issue `bd rename` preserves them.
#
# SAFETY:
#   - DRY-RUN BY DEFAULT. Pass --execute to actually apply.
#   - The beads DB is SHARED. Run only when concurrent sessions are idle — this
#     changes IDs out from under any in-progress work.
#   - Historical git commit messages referencing the old prefix are immutable and
#     will NOT be rewritten (that is expected; they are a historical record).
#
# Usage:
#   scripts/migrate-bead-prefix.sh            # dry-run: print every change, apply nothing
#   scripts/migrate-bead-prefix.sh --execute  # apply the migration
set -euo pipefail

OLD="claude-workflow-setup-"
NEW="escapement-"
EXECUTE=0
[ "${1:-}" = "--execute" ] && EXECUTE=1

run() { if [ "$EXECUTE" = 1 ]; then eval "$@"; else echo "  DRY-RUN: $*"; fi; }

cd "$(git rev-parse --show-toplevel)"

echo "== Pre-flight =================================================="
# Non-beads working-tree changes (beads runtime churn is expected and ignored).
dirty=$(git status --porcelain | grep -vE '\.beads/|^\?\? ' || true)
if [ -n "$dirty" ]; then
  echo "WARNING: working tree has non-beads changes — commit/stash before --execute:"
  echo "$dirty"
fi
# Concurrent in-progress work whose IDs this will change.
inprog=$(bd list --status=in_progress --json 2>/dev/null \
  | python3 -c 'import json,sys; print(len(json.load(sys.stdin)))' 2>/dev/null || echo "?")
echo "in-progress beads (IDs will change under any active session): $inprog"
if [ "$EXECUTE" = 1 ] && [ "$inprog" != "0" ]; then
  echo "  !! $inprog in-progress beads. Coordinate with active sessions before --execute. !!"
fi

echo "== Step 1: rename ${OLD}* -> ${NEW}* (suffix preserved) ========"
ids=$(bd list --all --json 2>/dev/null \
  | python3 -c "import json,sys; print('\n'.join(i['id'] for i in json.load(sys.stdin) if i['id'].startswith('$OLD')))")
n=$(printf '%s\n' "$ids" | grep -c . || true)
echo "issues to rename: $n"
printf '%s\n' "$ids" | while IFS= read -r old; do
  [ -z "$old" ] && continue
  new="${NEW}${old#"$OLD"}"
  run "bd rename '$old' '$new'"
done

echo "== Step 2: sweep tracked file references (excludes .beads/) ====="
files=$(git grep -lI "$OLD" -- ':!.beads/' || true)
echo "files to sweep: $(printf '%s\n' "$files" | grep -c . || true)"
printf '%s\n' "$files" | while IFS= read -r f; do
  [ -z "$f" ] && continue
  # perl -i is portable across macOS/Linux (unlike sed -i)
  run "perl -pi -e 's/\\Q${OLD}\\E/${NEW}/g' '$f'"
done

echo "== Step 3: update issue-prefix in .beads/config.yaml ==========="
run "bd config set issue-prefix escapement"

echo "== Step 4: re-export jsonl + verify ============================"
run "bd export > .beads/issues.jsonl"
run "python3 tools/render_agent_surfaces.py --check"
run "pytest tests/ claude/hooks/tests/ -q --ignore=e9v4-session-isolation"

echo "== Done (EXECUTE=$EXECUTE) ====================================="
if [ "$EXECUTE" = 1 ]; then
  echo "Review 'git status', then commit on a feature branch + open a PR."
else
  echo "This was a DRY-RUN. Re-run with --execute (when sessions are idle) to apply."
fi
