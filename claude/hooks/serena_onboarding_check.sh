#!/usr/bin/env bash
# Serena onboarding nudge for SessionStart.
# Silent unless CWD is inside a substantive project AND Serena has no memories yet.

dir="$PWD"
while [ "$dir" != "/" ]; do
    if [ -d "$dir/.git" ] || [ -f "$dir/pyproject.toml" ] || [ -f "$dir/package.json" ] \
        || [ -f "$dir/Gemfile" ] || [ -f "$dir/Cargo.toml" ] || [ -f "$dir/go.mod" ]; then
        if [ ! -d "$dir/.serena/memories" ] || [ -z "$(ls -A "$dir/.serena/memories" 2>/dev/null)" ]; then
            echo "Serena not onboarded for this project ($dir) — run mcp__serena__onboarding early."
        fi
        exit 0
    fi
    dir="$(dirname "$dir")"
done
