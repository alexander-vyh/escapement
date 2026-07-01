#!/usr/bin/env bash
# Test: serena_onboarding_check.sh (SessionStart) must instruct project ACTIVATION,
# not just onboarding.
#
# Business invariant: the shared Serena MCP server launches projectless
# (`serena-mcp-server --context ide-assistant`, no --project). So when a session
# starts inside an already-onboarded Serena project, Serena tools return
# "No active project" until the model calls mcp__serena__activate_project. The
# SessionStart hook must emit that activation instruction. Onboarding (memories on
# disk) and activation (this session's server has the project loaded) are DIFFERENT
# states; the hook must not conflate them and fall silent when memories already exist.
#
# Fragile implementations this rejects:
#   - only nudging when .serena/memories is empty (the original bug): an onboarded
#     repo with memories gets nothing, so activation never happens.
#   - echoing activate_project unconditionally: fires in non-project dirs too.
#   - keying activation on .git alone: would tell every git repo to activate a
#     Serena project it has not registered (registry pollution).
#
# Run: bash tests/test_serena_onboarding_check.sh
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOOK="$REPO/claude/hooks/serena_onboarding_check.sh"
fail=0
ok()  { printf '  ok: %s\n' "$*"; }
bad() { printf '  FAIL: %s\n' "$*"; fail=1; }

[ -f "$HOOK" ] || { echo "missing hook: $HOOK" >&2; exit 2; }

T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT

# Run the hook as if the session started in $1.
hook_output() { ( cd "$1" && bash "$HOOK" ); }

assert_contains() {
  local out="$1" needle="$2" label="$3"
  if printf '%s' "$out" | grep -qF "$needle"; then ok "$label"; else
    printf '  --- output ---\n%s\n  --------------\n' "$out"; bad "$label (missing: $needle)"
  fi
}
assert_not_contains() {
  local out="$1" needle="$2" label="$3"
  if printf '%s' "$out" | grep -qF "$needle"; then
    printf '  --- output ---\n%s\n  --------------\n' "$out"; bad "$label (unexpected: $needle)"
  else ok "$label"; fi
}
assert_empty() {
  local out="$1" label="$2"
  if [ -z "$out" ]; then ok "$label"; else
    printf '  --- output ---\n%s\n  --------------\n' "$out"; bad "$label (expected empty)"
  fi
}

# --- Positive control (the bug): onboarded Serena project (memories present) ---
ONBOARDED="$T/onboarded"
mkdir -p "$ONBOARDED/.git" "$ONBOARDED/.serena/memories"
printf 'project_name: onboarded\n' > "$ONBOARDED/.serena/project.yml"
printf 'some memory\n' > "$ONBOARDED/.serena/memories/overview.md"
out="$(hook_output "$ONBOARDED")"
assert_contains "$out" "activate_project" "onboarded Serena project is told to activate_project"
assert_contains "$out" "$ONBOARDED" "activation instruction names the resolved project path"
assert_not_contains "$out" "run mcp__serena__onboarding early" \
  "onboarded project is NOT told to re-onboard"

# --- Positive control: registered Serena project, not yet onboarded (empty memories) ---
FRESH="$T/fresh"
mkdir -p "$FRESH/.git" "$FRESH/.serena/memories"
printf 'project_name: fresh\n' > "$FRESH/.serena/project.yml"
out="$(hook_output "$FRESH")"
assert_contains "$out" "activate_project" "un-onboarded Serena project is still told to activate"
assert_contains "$out" "onboarding" "un-onboarded Serena project is also told to onboard"

# --- Negative control: plain git repo, no .serena → must NOT claim to activate ---
PLAIN="$T/plain"
mkdir -p "$PLAIN/.git"
out="$(hook_output "$PLAIN")"
assert_not_contains "$out" "activate_project" \
  "plain git repo (no .serena/project.yml) is NOT told to activate a Serena project"
assert_contains "$out" "onboarding" "plain git repo still gets the onboarding nudge"

# --- Negative control: not a project at all → silent ---
BARE="$T/bare/deep/nested"
mkdir -p "$BARE"
out="$(hook_output "$BARE")"
assert_empty "$out" "non-project directory produces no output"

echo
if [ "$fail" -eq 0 ]; then
  echo "PASS — serena onboarding hook activates onboarded projects"
  exit 0
else
  echo "FAIL — see above"
  exit 1
fi
