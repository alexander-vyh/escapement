#!/usr/bin/env bash
# Escapement always-on rules injection (SessionStart).
#
# Mitigation 1 (effectiveness): emit the rules with imperative framing so the
#   injected context carries the same authority as native CLAUDE.md/rules
#   ("These OVERRIDE default behavior and you MUST follow them").
# Mitigation 2 (reliability): FAIL LOUD. Unlike a silent `exit 0`, a missing or
#   unreadable rules bundle still emits a visible warning into the session, so a
#   broken install is observable instead of a quiet behavioral regression.
set -uo pipefail

RULES_DIR="${CLAUDE_PLUGIN_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}/rules"

python3 - "$RULES_DIR" <<'PY'
import glob, json, os, sys

rules_dir = sys.argv[1]
files = sorted(glob.glob(os.path.join(rules_dir, "*.md")))

if not files:
    # Fail loud: surface the broken install rather than silently dropping the rules.
    ctx = (
        "[escapement] WARNING: rules bundle not found at %s. Escapement discipline "
        "rules were NOT injected this session — the plugin install may be incomplete. "
        "Reinstall/update the escapement plugin." % rules_dir
    )
else:
    preamble = (
        "IMPORTANT — Escapement workflow rules (always-on, injected at session start). "
        "These instructions OVERRIDE default behavior and you MUST follow them exactly:\n"
    )
    parts = [preamble]
    for f in files:
        try:
            parts.append(open(f, encoding="utf-8").read())
        except OSError as exc:
            parts.append("[escapement] WARNING: could not read %s (%s)" % (f, exc))
    ctx = "\n\n".join(parts)

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": ctx,
    }
}))
PY
