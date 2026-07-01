#!/usr/bin/env bash
# Serena SessionStart hook. Two responsibilities, keyed off the resolved project root:
#   1. ACTIVATION: the shared Serena MCP server launches projectless
#      (serena-mcp-server --context ide-assistant, no --project), so a session that
#      starts inside a registered Serena project (.serena/project.yml present) hits
#      "No active project" on every Serena call until the model activates it.
#      Onboarded != activated: memories on disk say the project was set up once;
#      they say nothing about whether THIS session's server has it loaded. So the
#      activation nudge must fire even when memories already exist.
#   2. ONBOARDING: if the project has no Serena memories yet, nudge to onboard.
# Silent unless CWD is inside a substantive project.

dir="$PWD"
while [ "$dir" != "/" ]; do
    if [ -d "$dir/.git" ] || [ -f "$dir/pyproject.toml" ] || [ -f "$dir/package.json" ] \
        || [ -f "$dir/Gemfile" ] || [ -f "$dir/Cargo.toml" ] || [ -f "$dir/go.mod" ] \
        || [ -f "$dir/.serena/project.yml" ]; then

        if [ -f "$dir/.serena/project.yml" ]; then
            echo "Serena project registered at $dir, but the shared Serena server starts projectless — Serena tools return 'No active project' until you activate. As your FIRST Serena action this session, call mcp__serena__activate_project with project='$dir' (idempotent; safe if already active)."
        fi

        if [ ! -d "$dir/.serena/memories" ] || [ -z "$(ls -A "$dir/.serena/memories" 2>/dev/null)" ]; then
            echo "Serena not onboarded for this project ($dir) — run mcp__serena__onboarding early (after activating, if it is a Serena project)."
        fi
        exit 0
    fi
    dir="$(dirname "$dir")"
done
