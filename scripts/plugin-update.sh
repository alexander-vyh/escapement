#!/bin/bash
# plugin-update.sh — refresh the installed escapement plugin to current main.
#
# WHY THIS EXISTS (escapement-06g): the plugin declares a static version
# "1.0.0" and its SessionStart inject-rules.sh does NOT git-pull, so
# `claude plugin update` is a no-op ("already at latest 1.0.0") even when the
# git-subdir source (ref: main) has moved. The only mechanism that actually
# refetches main HEAD is uninstall+reinstall. This script wraps that safely.
#
# Usage:
#   ./scripts/plugin-update.sh            # refresh plugin cache to main HEAD
#   ./scripts/plugin-update.sh --dry-run  # show what would happen, change nothing
#
# SAFE PRE- AND POST-CUTOVER:
#   - Preserves the plugin's enabled/disabled state (reinstall re-enables; we
#     restore whatever it was) and the settings.json `model` key (reinstall has
#     been observed to drop/rewrite it).
#   - Repoints ~/.claude/harness/bin ONLY if it already resolves into a plugin
#     installPath (i.e. the machine is already cut over). If it points at the
#     legacy pin (pre-cutover), it is left untouched — an update must not perform
#     the cutover.
#
# Fail-fast.
set -euo pipefail

CLAUDE_DIR="$HOME/.claude"
SETTINGS="$CLAUDE_DIR/settings.json"
PLUGIN_ID="escapement@escapement"
INSTALLED="$CLAUDE_DIR/plugins/installed_plugins.json"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"

DRY_RUN=false
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=true ;;
    --help|-h) sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown arg: $arg" >&2; exit 1 ;;
  esac
done

run() { if [[ "$DRY_RUN" == true ]]; then echo "    [dry-run] $*"; else eval "$*"; fi; }

command -v claude >/dev/null || { echo "FATAL: 'claude' CLI not on PATH" >&2; exit 1; }
[[ -f "$SETTINGS" ]] || { echo "FATAL: no settings.json at $SETTINGS" >&2; exit 1; }

# --- Resolve current installPath (canonical: installed_plugins.json). ---
resolve_install_path() {
  python3 - "$INSTALLED" <<'PY'
import json, sys, glob, os
try:
    d = json.load(open(sys.argv[1]))
    entries = d.get("plugins", {}).get("escapement@escapement", [])
    for e in entries:
        p = e.get("installPath")
        if p and os.path.isdir(p):
            print(p); sys.exit(0)
except Exception:
    pass
# glob fallback
hits = sorted(glob.glob(os.path.expanduser("~/.claude/plugins/cache/escapement/escapement/*")))
print(hits[-1] if hits else "")
PY
}

# --- Capture pre-state we must preserve across the reinstall. ---
pre_enabled="$(python3 -c "import json;print(json.load(open('$SETTINGS')).get('enabledPlugins',{}).get('$PLUGIN_ID'))")"
pre_model="$(python3 -c "import json;print(json.load(open('$SETTINGS')).get('model') or '')")"
harness_link="$CLAUDE_DIR/harness/bin"
harness_target="$(readlink "$harness_link" 2>/dev/null || echo '')"

echo "==> escapement plugin-update"
echo "    pre-state: enabled=$pre_enabled  model='${pre_model:-<unset>}'"
echo "    harness/bin -> ${harness_target:-<none>}"

# --- Backup settings.json (reinstall rewrites it). ---
BK="$CLAUDE_DIR/.cutover-backup-$TIMESTAMP"
run "mkdir -p '$BK' && cp '$SETTINGS' '$BK/settings.json'"
echo "    backup: $BK"

# --- Force-refresh: uninstall then install fetches main HEAD. ---
run "claude plugin uninstall '$PLUGIN_ID' >/dev/null 2>&1 || true"
run "claude plugin install '$PLUGIN_ID' >/dev/null"

# --- Restore preserved state. ---
# Restore enabled/disabled to whatever it was (reinstall force-enables).
if [[ "$DRY_RUN" != true ]]; then
  if [[ "$pre_enabled" == "False" ]]; then
    claude plugin disable "$PLUGIN_ID" >/dev/null 2>&1 || true
  fi
  # Restore model key if the reinstall changed it.
  now_model="$(python3 -c "import json;print(json.load(open('$SETTINGS')).get('model') or '')")"
  if [[ "$now_model" != "$pre_model" ]]; then
    python3 - "$SETTINGS" "$pre_model" <<'PY'
import json, sys
p, model = sys.argv[1], sys.argv[2]
d = json.load(open(p))
if model:
    d["model"] = model
else:
    d.pop("model", None)
json.dump(d, open(p, "w"), indent=2)
PY
    echo "    restored model key: '${pre_model:-<unset>}' (reinstall had set '${now_model:-<unset>}')"
  fi
fi

# --- Repoint harness/bin ONLY if already cut over (points into a plugin path). ---
new_path="$(resolve_install_path)"
if [[ -z "$new_path" ]]; then
  echo "FATAL: could not resolve plugin installPath after reinstall" >&2; exit 1
fi

# Self-heal the exec bit (escapement-rkl5): the plugin vendors harness/bin/* as
# text (git mode 100644), but verify/workflow_status are invoked BARE by the
# continuation-harness rule and need +x. A reinstall re-clones them non-executable,
# so restore it on every refresh.
if [[ "$DRY_RUN" == true ]]; then
  echo "    [dry-run] chmod +x $new_path/harness/bin/*"
else
  chmod +x "$new_path"/harness/bin/* 2>/dev/null || true
  echo "    restored +x on vendored harness executables"
fi

if [[ "$harness_target" == *"/plugins/cache/escapement/"* ]]; then
  run "ln -sfn '$new_path/harness/bin' '$harness_link'"
  echo "    repointed harness/bin -> $new_path/harness/bin (post-cutover)"
else
  echo "    harness/bin left at legacy pin (pre-cutover) — update did not cut over"
fi

# --- Verify freshness against repo main (canary: stop_hook.py). ---
if [[ "$DRY_RUN" != true ]]; then
  REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  canary="$new_path/harness/bin/stop_hook.py"
  repo_canary="$REPO_DIR/plugins/escapement-claude/harness/bin/stop_hook.py"
  if [[ -f "$canary" && -f "$repo_canary" ]]; then
    if diff -q "$canary" "$repo_canary" >/dev/null; then
      echo "==> OK: plugin cache refreshed to match repo main."
    else
      echo "WARN: plugin cache differs from THIS checkout's plugin source." >&2
      echo "      (expected if this checkout is not at the deployed main ref)" >&2
    fi
  fi
fi
echo "==> done."
