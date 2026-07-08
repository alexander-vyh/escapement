#!/usr/bin/env bash
# Test: scripts/plugin-update.sh refreshes the escapement plugin to main HEAD
# while PRESERVING state across the reinstall (bead escapement-06g).
#
# Business invariant: `claude plugin update` is a no-op for this plugin (static
# version 1.0.0), so the refresh path force-reinstalls. A reinstall re-enables
# the plugin and drops the settings.json `model` key. The script must undo BOTH
# side effects, and must NOT perform the cutover (repoint ~/.claude/harness/bin)
# when the machine is still on the legacy pin.
#
# Fragile implementations this rejects:
#   - refresh that leaves the plugin ENABLED (double-fire risk pre-cutover)
#   - refresh that DROPS the model key (the real 2026-07 side effect)
#   - refresh that repoints harness/bin off the pin BEFORE an attended cutover
#
# Offline + isolated: stubs the `claude` CLI and runs against a throwaway HOME.
# Run: bash tests/test_plugin_update.sh
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fail=0
ok()  { printf '  ok: %s\n' "$*"; }
bad() { printf '  FAIL: %s\n' "$*"; fail=1; }

TD="$(mktemp -d)"; trap 'rm -rf "$TD"' EXIT
HOME_DIR="$TD/home"; BIN="$TD/bin"
mkdir -p "$BIN" "$HOME_DIR/.claude/plugins/cache/escapement/escapement/1.0.0/harness/bin"
mkdir -p "$HOME_DIR/.claude/harness"

CACHE="$HOME_DIR/.claude/plugins/cache/escapement/escapement/1.0.0"
# Canary file the script diffs against the repo's plugin source; make it match so
# the freshness check reports OK (its mismatch path only WARNs, never fails).
cp "$REPO/plugins/escapement-claude/harness/bin/stop_hook.py" "$CACHE/harness/bin/stop_hook.py"
# Vendored NON-executable (git mode 100644, as the renderer writes it) — the
# self-heal must restore +x (escapement-rkl5).
printf '#!/bin/bash\nexit 0\n' > "$CACHE/harness/bin/verify"
chmod 644 "$CACHE/harness/bin/verify"

# Pre-state: plugin DISABLED, an explicit model key set, harness/bin -> legacy pin.
mkdir -p "$HOME_DIR/.claude/.escapement-pinned/harness/bin"
ln -sfn "$HOME_DIR/.claude/.escapement-pinned/harness/bin" "$HOME_DIR/.claude/harness/bin"
cat > "$HOME_DIR/.claude/settings.json" <<JSON
{
  "model": "opus[1m]",
  "enabledPlugins": { "escapement@escapement": false },
  "hooks": {}
}
JSON
cat > "$HOME_DIR/.claude/plugins/installed_plugins.json" <<JSON
{ "version": 2, "plugins": { "escapement@escapement": [
  { "scope": "user", "installPath": "$CACHE", "version": "1.0.0" } ] } }
JSON

# --- Stub `claude`: simulate the real reinstall side effects. ---
cat > "$BIN/claude" <<'STUB'
#!/usr/bin/env bash
# minimal stub: `claude plugin {install,uninstall,disable}`
S="$HOME/.claude/settings.json"
set_json() { python3 - "$S" "$@" <<'PY'
import json,sys
p=sys.argv[1]; op=sys.argv[2]; d=json.load(open(p))
if op=="enable":
    d.setdefault("enabledPlugins",{})["escapement@escapement"]=True
    d.pop("model",None)                      # reinstall drops the model key
elif op=="disable":
    d.setdefault("enabledPlugins",{})["escapement@escapement"]=False
json.dump(d,open(p,"w"),indent=2)
PY
}
case "$2 $3" in
  "plugin install")   set_json enable ;;     # install re-enables + drops model
  "plugin uninstall") : ;;
  "plugin disable")   set_json disable ;;
esac
exit 0
STUB
chmod +x "$BIN/claude"

# --- CASE 1: pre-cutover (harness/bin -> pin). ---
HOME="$HOME_DIR" PATH="$BIN:$PATH" bash "$REPO/scripts/plugin-update.sh" >"$TD/out.log" 2>&1 \
  || { cat "$TD/out.log"; bad "plugin-update.sh exited non-zero"; }

enabled="$(python3 -c "import json;print(json.load(open('$HOME_DIR/.claude/settings.json')).get('enabledPlugins',{}).get('escapement@escapement'))")"
model="$(python3 -c "import json;print(json.load(open('$HOME_DIR/.claude/settings.json')).get('model'))")"
htarget="$(readlink "$HOME_DIR/.claude/harness/bin")"

if [ "$enabled" = "False" ]; then ok "plugin left DISABLED (enabled state preserved)"
else bad "plugin left enabled=$enabled — refresh did not restore disabled state"; fi
if [ "$model" = "opus[1m]" ]; then ok "model key PRESERVED across reinstall"
else bad "model key = '$model' — refresh dropped/changed it (the real bug)"; fi
case "$htarget" in
  *"/.escapement-pinned/"*) ok "harness/bin left on legacy pin (no premature cutover)" ;;
  *) bad "harness/bin repointed to '$htarget' pre-cutover — update must not cut over" ;;
esac
# escapement-rkl5: bare-invoked harness executables must be +x after a refresh.
if [ -x "$CACHE/harness/bin/verify" ]; then ok "verify exec bit restored (self-heal)"
else bad "verify not executable after refresh — ~/.claude/harness/bin/verify would 'permission denied'"; fi

# --- CASE 2: post-cutover (harness/bin already -> plugin) repoints to installPath. ---
ln -sfn "$CACHE/harness/bin" "$HOME_DIR/.claude/harness/bin"
HOME="$HOME_DIR" PATH="$BIN:$PATH" bash "$REPO/scripts/plugin-update.sh" >"$TD/out2.log" 2>&1 \
  || { cat "$TD/out2.log"; bad "plugin-update.sh (post-cutover) exited non-zero"; }
htarget2="$(readlink "$HOME_DIR/.claude/harness/bin")"
case "$htarget2" in
  "$CACHE/harness/bin") ok "harness/bin repointed to plugin installPath (post-cutover)" ;;
  *) bad "harness/bin = '$htarget2' — expected repoint to $CACHE/harness/bin" ;;
esac

[ "$fail" -eq 0 ] && echo "PASS: plugin-update.sh preserves state + gates cutover" || echo "FAILURES above"
exit "$fail"
