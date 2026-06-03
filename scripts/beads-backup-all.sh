#!/usr/bin/env bash
# beads-backup-all.sh — Off-machine backup of ALL beads repos.
#
# Discovers every primary .beads repo (via beads-discover.sh), snapshots each
# repo's issue data (including bd-remember memories), and commits + pushes the
# snapshots to a private GitHub repo (alexander-vyh/beads-backup). DATA ONLY —
# this never writes beads data into the host repos, so it can never pollute a
# repo you don't own.
#
# Reusable + extensible: repos are discovered at runtime, so any NEW or EXISTING
# repo that later gains a .beads dir is picked up automatically on the next run.
#
# Canonical copy in claude-workflow-setup/scripts/; symlinked into ~/.local/bin.
# Exit 0 on success (committed+pushed, or nothing changed); non-zero if the
# clone/commit/push fails — a real, surfaced failure.
set -uo pipefail   # deliberately NOT -e: one bad repo must not abort the sweep

# --- Config (override via env for testing) ------------------------------------
BACKUP_SLUG="${BEADS_BACKUP_SLUG:-alexander-vyh/beads-backup}"
BACKUP_CLONE="${BEADS_BACKUP_CLONE:-$HOME/.local/share/beads-backup}"
EXPORT_TIMEOUT="${BEADS_BACKUP_EXPORT_TIMEOUT:-20}"
BD="${BD_BIN:-$(command -v bd || echo /opt/homebrew/bin/bd)}"
GH="${GH_BIN:-$(command -v gh || echo /opt/homebrew/bin/gh)}"
DISCOVER="${BEADS_DISCOVER:-$(command -v beads-discover.sh || echo "$(dirname "$0")/beads-discover.sh")}"

LOG_TS="$(date -u +%FT%TZ)"
log() { printf '%s %s\n' "$LOG_TS" "$*" >&2; }

# Portable timeout: gtimeout/timeout if present, else perl alarm (always on macOS).
_timeout() {
  local secs="$1"; shift
  if command -v gtimeout >/dev/null 2>&1; then gtimeout "$secs" "$@"
  elif command -v timeout >/dev/null 2>&1; then timeout "$secs" "$@"
  else perl -e 'my $s=shift; alarm $s; exec @ARGV' "$secs" "$@"; fi
}

# --- 1. Ensure the backup clone exists ----------------------------------------
if [ ! -d "$BACKUP_CLONE/.git" ]; then
  mkdir -p "$(dirname "$BACKUP_CLONE")"
  log "cloning $BACKUP_SLUG -> $BACKUP_CLONE"
  "$GH" repo clone "$BACKUP_SLUG" "$BACKUP_CLONE" >/dev/null 2>&1 \
    || { log "FATAL: could not clone $BACKUP_SLUG"; exit 1; }
fi
cd "$BACKUP_CLONE" || { log "FATAL: cannot cd $BACKUP_CLONE"; exit 1; }

# Pin the clone's push credential to the backup repo's owning account, headlessly.
# launchd has no GH_TOKEN and ~/.local/share is outside any ~/GitHub includeIf scope,
# so without this the clone falls back to the global (work) credential -> 404.
# Uses the user's own per-account helper (gh-cred) if present; idempotent.
ACCOUNT="${BACKUP_SLUG%%/*}"
if [ -x "$HOME/.local/bin/gh-cred" ]; then
  git config --local --unset-all credential.https://github.com.helper 2>/dev/null || true
  git config --local --add credential.https://github.com.helper ""
  git config --local --add credential.https://github.com.helper "!$HOME/.local/bin/gh-cred --user $ACCOUNT"
fi

git pull --quiet --ff-only 2>/dev/null || true

# --- 2. Snapshot each discovered repo -----------------------------------------
mkdir -p "$BACKUP_CLONE/repos"
MANIFEST="$BACKUP_CLONE/MANIFEST.tsv"
printf 'repo\tsource_path\tissues\tbytes\tjsonl_mtime\tmode\n' > "$MANIFEST"

discovered=0
failed=0
while IFS= read -r repodir; do
  [ -z "$repodir" ] && continue
  beadsdir="$repodir/.beads"
  rel="${repodir#"$HOME/GitHub/"}"
  name="$(printf '%s' "$rel" | tr '/ ' '__')"
  [ -z "$name" ] && name="$(basename "$repodir")"
  dest="$BACKUP_CLONE/repos/$name"
  mkdir -p "$dest"
  discovered=$((discovered + 1))

  ondisk="$beadsdir/issues.jsonl"
  mode="FAILED"

  if [ -s "$ondisk" ]; then
    # Preferred: copy the on-disk export (fast, no Dolt wake — beads keeps it
    # fresh via export.auto after each write).
    cp "$ondisk" "$dest/issues.jsonl" && mode="ondisk-copy"
  elif [ -d "$beadsdir/dolt" ]; then
    # Dolt-only repo (no on-disk JSONL): force a fresh export, bounded so a hung
    # Dolt server can't wall the sweep. Exit 0 with 0 issues = genuinely empty.
    if ( cd "$repodir" && _timeout "$EXPORT_TIMEOUT" "$BD" export --all -o "$dest/issues.jsonl" ) >/dev/null 2>&1 \
       && [ -f "$dest/issues.jsonl" ]; then
      mode="export-fresh"
    else
      : > "$dest/issues.jsonl"   # placeholder; explicitly FAILED for the oracle
    fi
  elif [ -f "$ondisk" ]; then
    cp "$ondisk" "$dest/issues.jsonl" && mode="EMPTY-OK"   # exists but empty
  fi

  # Belt-and-suspenders: copy the append-only interactions audit if present.
  [ -s "$beadsdir/interactions.jsonl" ] && cp "$beadsdir/interactions.jsonl" "$dest/interactions.jsonl"

  bytes=$(wc -c < "$dest/issues.jsonl" 2>/dev/null | tr -d ' ')
  issues=$(grep -c '"id"' "$dest/issues.jsonl" 2>/dev/null || echo 0)
  mtime=$(stat -f '%Sm' -t '%Y-%m-%dT%H:%M' "$ondisk" 2>/dev/null || echo "-")
  [ "$mode" = "FAILED" ] && failed=$((failed + 1))
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$name" "$repodir" "$issues" "$bytes" "$mtime" "$mode" >> "$MANIFEST"
  log "snapshot $name: $mode ($issues issues, $bytes bytes)"
done < <("$DISCOVER")

log "discovered=$discovered failed=$failed"

# --- 3. Commit + push ---------------------------------------------------------
cd "$BACKUP_CLONE" || exit 1
git add -A
if git diff --cached --quiet; then
  log "no changes to back up"
  exit 0
fi
git commit -q -m "backup $LOG_TS: $discovered repos ($failed failed)" \
  || { log "FATAL: commit failed"; exit 1; }
git push -q origin HEAD || { log "FATAL: push failed — backup NOT off-machine"; exit 1; }
log "pushed snapshot of $discovered repos to $BACKUP_SLUG"
exit 0
