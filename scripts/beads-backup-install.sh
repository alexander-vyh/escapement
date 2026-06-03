#!/usr/bin/env bash
# beads-backup-install.sh — install the off-machine beads backup for the CURRENT user.
#
# Idempotent, path-portable (nothing hardcoded — everything derived from $HOME and
# the running user at install time). It:
#   1. symlinks the beads-backup tooling into ~/.local/bin
#   2. seeds ~/.config/beads-backup/owned-remotes.txt (ownership allowlist)
#   3. generates a per-user launchd job from a template and (re)loads it
#
# Usage:
#   ./beads-backup-install.sh              # install / refresh for $USER
#   ./beads-backup-install.sh --uninstall  # remove the job + symlinks (keeps data/config)
#   BEADS_BACKUP_INTERVAL=7200 ./beads-backup-install.sh   # custom cadence (seconds)
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"          # .../scripts
BIN_DIR="$HOME/.local/bin"
LABEL="com.beads-backup-all"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/Library/Application Support/beads-snapshots"
CONFIG_DIR="$HOME/.config/beads-backup"
INTERVAL="${BEADS_BACKUP_INTERVAL:-14400}"                        # default 4h
BREW_BIN="$( (command -v brew >/dev/null 2>&1 && printf '%s/bin' "$(brew --prefix)") || echo /opt/homebrew/bin )"
SCRIPTS=(beads-discover.sh beads-backup-all.sh beads-backup-check.sh bd-init)
UID_NUM="$(id -u)"

uninstall() {
  launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null \
    || launchctl unload "$PLIST" 2>/dev/null || true
  rm -f "$PLIST"
  for s in "${SCRIPTS[@]}"; do [ -L "$BIN_DIR/$s" ] && rm -f "$BIN_DIR/$s"; done
  echo "uninstalled $LABEL + symlinks (config + backup data left intact)"
}

[ "${1:-}" = "--uninstall" ] && { uninstall; exit 0; }

# 1. Symlink tooling into ~/.local/bin
mkdir -p "$BIN_DIR"
for s in "${SCRIPTS[@]}"; do ln -sf "$REPO_DIR/$s" "$BIN_DIR/$s"; done

# 2. Seed the ownership allowlist (only if absent — never clobber user edits)
mkdir -p "$CONFIG_DIR"
if [ ! -f "$CONFIG_DIR/owned-remotes.txt" ]; then
  cat > "$CONFIG_DIR/owned-remotes.txt" <<'EOF'
# owned-remotes.txt — regexes (one per line) for git remotes you consider YOURS
# (your team's repos). A repo whose `origin` matches → bd-init lets beads commit
# in-place. Built-ins (always owned): github.com/alexander-vyh/* and /secure/*.
# Add your team's repos below, e.g.:
#   github\.com[:/]simplifi/simplifi-mcp-server
EOF
fi

# 3. Generate the per-user launchd plist (paths resolved for THIS user/machine)
mkdir -p "$LOG_DIR" "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$BIN_DIR/beads-backup-all.sh</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>$BREW_BIN:/usr/bin:/bin:/usr/sbin:/sbin</string>
        <key>HOME</key>
        <string>$HOME</string>
    </dict>
    <key>StartInterval</key>
    <integer>$INTERVAL</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$LOG_DIR/backup-all.out.log</string>
    <key>StandardErrorPath</key>
    <string>$LOG_DIR/backup-all.err.log</string>
</dict>
</plist>
EOF

# 4. (Re)load the job
launchctl bootout "gui/$UID_NUM/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$UID_NUM" "$PLIST" 2>/dev/null || launchctl load -w "$PLIST"

echo "installed $LABEL"
echo "  cadence:   every ${INTERVAL}s (set BEADS_BACKUP_INTERVAL to change)"
echo "  scripts:   symlinked ${#SCRIPTS[@]} into $BIN_DIR"
echo "  logs:      $LOG_DIR/backup-all.{out,err}.log"
echo "  allowlist: $CONFIG_DIR/owned-remotes.txt"
