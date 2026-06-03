#!/usr/bin/env bash
# beads-backup-check.sh — Oracle for the off-machine beads backup.
#
# Exits 0 ONLY if the backup genuinely happened end-to-end:
#   (1) every discovered .beads repo has a snapshot in the backup clone (coverage),
#   (2) NO repo is marked FAILED in the manifest (no silent export failures),
#   (3) the backup clone's HEAD is actually pushed to the remote (off-machine).
#
# This is an OUTCOME oracle, not an existence check: a touched-but-empty file from
# a failed export is caught by (2), and a local-only commit is caught by (3).
#
# Canonical copy in claude-workflow-setup/scripts/; symlinked to ~/.local/bin.
set -uo pipefail

BACKUP_CLONE="${BEADS_BACKUP_CLONE:-$HOME/.local/share/beads-backup}"
DISCOVER="${BEADS_DISCOVER:-$(command -v beads-discover.sh || echo "$(dirname "$0")/beads-discover.sh")}"

fail() { echo "FAIL: $*"; exit 1; }

[ -d "$BACKUP_CLONE/.git" ] || fail "backup clone missing at $BACKUP_CLONE"

discovered=$("$DISCOVER" | wc -l | tr -d ' ')
backed=$(find "$BACKUP_CLONE/repos" -name issues.jsonl 2>/dev/null | wc -l | tr -d ' ')
echo "discovered=$discovered backed=$backed"

[ "$discovered" -gt 0 ] || fail "no .beads repos discovered under ${SEARCH_ROOTS[*]}"
[ "$backed" -ge "$discovered" ] || fail "coverage gap: backed=$backed < discovered=$discovered"

# (2) no silent export failures
if [ -f "$BACKUP_CLONE/MANIFEST.tsv" ]; then
  nfailed=$(awk -F'\t' 'NR>1 && $6=="FAILED"' "$BACKUP_CLONE/MANIFEST.tsv" | wc -l | tr -d ' ')
  [ "$nfailed" -eq 0 ] || fail "$nfailed repo(s) marked FAILED in manifest"
else
  fail "MANIFEST.tsv missing"
fi

# (3) pushed off-machine
cd "$BACKUP_CLONE" || fail "cannot cd backup clone"
git fetch -q origin 2>/dev/null || true
local_head=$(git rev-parse HEAD 2>/dev/null)
remote_head=$(git rev-parse '@{u}' 2>/dev/null || git rev-parse origin/main 2>/dev/null || git rev-parse origin/HEAD 2>/dev/null)
[ -n "$remote_head" ] || fail "no upstream/remote ref to compare"
[ "$local_head" = "$remote_head" ] || fail "HEAD not pushed (local=$local_head remote=$remote_head)"

echo "PASS: $backed/$discovered repos backed up and pushed off-machine to GitHub"
exit 0
