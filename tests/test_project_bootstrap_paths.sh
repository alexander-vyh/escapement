#!/usr/bin/env bash
# Test: project-bootstrap.sh must not assume managed repos live under ~/GitHub.
#
# Business invariant: after INSTALL.sh wires the SessionStart bootstrap, opening
# Claude Code in any git repo should produce bootstrap context unless the user
# explicitly configured an allowlist that excludes that repo.
#
# Run: bash tests/test_project_bootstrap_paths.sh
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fail=0
ok()  { printf '  ok: %s\n' "$*"; }
bad() { printf '  FAIL: %s\n' "$*"; fail=1; }

require_tool() {
  local name="$1"
  command -v "$name" >/dev/null 2>&1 || { echo "missing required tool: $name" >&2; exit 2; }
}

require_tool git
require_tool jq

T="$(mktemp -d)"
trap 'rm -rf "$T"' EXIT

HOME_DIR="$T/home"
STUB_BIN="$T/bin"
mkdir -p "$HOME_DIR" "$STUB_BIN"

GIT_BIN="$(command -v git)"
JQ_BIN="$(command -v jq)"
cat >"$STUB_BIN/git" <<EOF
#!/usr/bin/env bash
exec "$GIT_BIN" "\$@"
EOF
cat >"$STUB_BIN/jq" <<EOF
#!/usr/bin/env bash
exec "$JQ_BIN" "\$@"
EOF
chmod +x "$STUB_BIN/git" "$STUB_BIN/jq"

TEST_PATH="$STUB_BIN:/usr/bin:/bin"

make_git_repo() {
  local path="$1"
  mkdir -p "$path"
  git -C "$path" init --quiet
}

bootstrap_output() {
  local cwd="$1"
  local roots="${2-__UNSET__}"
  if [[ "$roots" == "__UNSET__" ]]; then
    printf '{"cwd":"%s"}\n' "$cwd" \
      | HOME="$HOME_DIR" PATH="$TEST_PATH" bash "$REPO/scripts/project-bootstrap.sh"
  else
    printf '{"cwd":"%s"}\n' "$cwd" \
      | HOME="$HOME_DIR" PATH="$TEST_PATH" ESCAPEMENT_BOOTSTRAP_ROOTS="$roots" bash "$REPO/scripts/project-bootstrap.sh"
  fi
}

assert_session_context() {
  local output="$1"
  local label="$2"
  if [[ -z "$output" ]]; then
    bad "$label: expected SessionStart context, got empty output"
    return
  fi
  if printf '%s' "$output" | jq -e \
      '.hookSpecificOutput.hookEventName == "SessionStart"
       and (.hookSpecificOutput.additionalContext | contains("Agent Dispatch Rules"))' >/dev/null 2>&1; then
    ok "$label"
  else
    printf '%s\n' "$output"
    bad "$label: output was not bootstrap SessionStart JSON"
  fi
}

assert_no_output() {
  local output="$1"
  local label="$2"
  if [[ -z "$output" ]]; then
    ok "$label"
  else
    printf '%s\n' "$output"
    bad "$label: expected no output"
  fi
}

# Positive control: this repo is deliberately outside $HOME/GitHub. The old
# implementation exits before emitting anything here.
OUTSIDE_REPO="$T/workspaces/client-app"
make_git_repo "$OUTSIDE_REPO"
out="$(bootstrap_output "$OUTSIDE_REPO")"
assert_session_context "$out" "default bootstrap runs in a git repo outside ~/GitHub"

# Negative control: the path gate must not be replaced with an unconditional run.
NOT_GIT="$T/workspaces/not-git"
mkdir -p "$NOT_GIT"
out="$(bootstrap_output "$NOT_GIT")"
assert_no_output "$out" "bootstrap stays silent outside git repos"

# Negative control: an explicit allowlist constrains the machine-wide bootstrap.
ALLOWED_ROOT="$T/allowed"
EXCLUDED_REPO="$T/elsewhere/other-app"
make_git_repo "$EXCLUDED_REPO"
out="$(bootstrap_output "$EXCLUDED_REPO" "$ALLOWED_ROOT")"
assert_no_output "$out" "allowlist excludes git repos outside configured roots"

# Negative control: root matching must be path-boundary aware, not a raw string
# prefix match that accepts sibling names like "allowed-service".
SIBLING_PREFIX_REPO="$T/allowed-service"
make_git_repo "$SIBLING_PREFIX_REPO"
out="$(bootstrap_output "$SIBLING_PREFIX_REPO" "$ALLOWED_ROOT")"
assert_no_output "$out" "allowlist does not accept sibling paths with the same string prefix"

# Negative control: the allowlist must not bypass git-repo detection.
NOT_GIT_ALLOWED="$ALLOWED_ROOT/not-git"
mkdir -p "$NOT_GIT_ALLOWED"
out="$(bootstrap_output "$NOT_GIT_ALLOWED" "$ALLOWED_ROOT")"
assert_no_output "$out" "allowlist stays silent for non-git directories"

# Positive control: the allowlist is colon-separated, ignores missing roots, and
# permits repos under any configured root.
MISSING_ROOT="$T/missing-root"
SECOND_ROOT="$T/second-root"
SECOND_REPO="$SECOND_ROOT/service"
make_git_repo "$SECOND_REPO"
out="$(bootstrap_output "$SECOND_REPO" "$MISSING_ROOT:$SECOND_ROOT")"
assert_session_context "$out" "allowlist supports colon-separated roots and ignores missing entries"

# Positive control: a single allowlist root permits repos under that root.
ALLOWED_REPO="$ALLOWED_ROOT/service"
make_git_repo "$ALLOWED_REPO"
out="$(bootstrap_output "$ALLOWED_REPO" "$ALLOWED_ROOT")"
assert_session_context "$out" "allowlist permits git repos under configured roots"

echo
if [[ "$fail" -eq 0 ]]; then
  echo "PASS — project bootstrap path selection is portable"
  exit 0
else
  echo "FAIL — see above"
  exit 1
fi
