#!/bin/bash
# project-bootstrap.sh — SessionStart hook
# Ensures git projects have the full tool stack initialized.
# Idempotent. Fail-open. Worktree-aware. Fast (< 2s warm).
#
# Phases:
#   1. Environment gate (optional root allowlist + git repo)
#   2. Worktree detection
#   3. Silent init (direnv, openspec)
#   4. Announced init (beads, serena)
#   5. Check-and-report (CLAUDE.md)
#   6. Emit bootstrap context (JSON additionalContext)

# Fail-open: trap any unexpected error, emit nothing, exit 0
trap 'exit 0' ERR

# --- Read hook input from stdin ---
INPUT=$(cat)
SESSION_CWD=$(printf '%s' "$INPUT" | jq -r '.cwd // empty' 2>/dev/null)
CWD="${SESSION_CWD:-$(pwd)}"

# --- Phase 1: Environment gate ---
if [[ ! -d "$CWD" ]]; then
  exit 0
fi
CWD=$(cd "$CWD" 2>/dev/null && pwd -P) || exit 0

normalize_bootstrap_root() {
  local root="$1"
  case "$root" in
    "~") root="$HOME" ;;
    "~/"*) root="$HOME/${root#"~/"}" ;;
  esac
  [[ -d "$root" ]] || return 1
  (cd "$root" 2>/dev/null && pwd -P)
}

within_bootstrap_roots() {
  local roots="${ESCAPEMENT_BOOTSTRAP_ROOTS:-}"
  [[ -n "$roots" ]] || return 0

  local root normalized
  IFS=':' read -r -a _bootstrap_roots <<< "$roots"
  for root in "${_bootstrap_roots[@]}"; do
    [[ -n "$root" ]] || continue
    normalized=$(normalize_bootstrap_root "$root") || continue
    if [[ "$CWD" == "$normalized" || "$CWD" == "$normalized"/* ]]; then
      return 0
    fi
  done
  return 1
}

if ! within_bootstrap_roots; then
  exit 0
fi

if ! git -C "$CWD" rev-parse --git-dir >/dev/null 2>&1; then
  exit 0  # Not a git repo
fi

# --- Phase 2: Worktree detection ---
TOPLEVEL=$(git -C "$CWD" rev-parse --show-toplevel 2>/dev/null) || exit 0
GIT_COMMON=$(git -C "$CWD" rev-parse --git-common-dir 2>/dev/null) || exit 0

# Resolve GIT_COMMON to absolute path (it may be relative)
if [[ "$GIT_COMMON" != /* ]]; then
  GIT_COMMON="$CWD/$GIT_COMMON"
fi
GIT_COMMON=$(cd "$GIT_COMMON" 2>/dev/null && pwd) || exit 0

# Parent of .git is the main repo root
MAIN_REPO_ROOT=$(dirname "$GIT_COMMON")
IS_WORKTREE=false
if [[ "$TOPLEVEL" != "$MAIN_REPO_ROOT" ]]; then
  IS_WORKTREE=true
fi

REPO_NAME=$(basename "$MAIN_REPO_ROOT")

# Accumulate report lines
ACTIONS=()
REPORT=()

# --- Phase 3: Silent init ---

bootstrap_direnv() {
  # Each worktree can have its own .envrc, so this runs everywhere
  if [[ ! -f "$CWD/.envrc" ]]; then
    return 0
  fi
  # Check if already allowed — direnv status prints "Found RC allowed 0" (0=allowed, 1=not)
  local status_out
  status_out=$(cd "$CWD" && direnv status 2>/dev/null) || return 0
  if printf '%s' "$status_out" | grep -q "Found RC allowed 0"; then
    return 0  # Already allowed
  fi
  if direnv allow "$CWD" 2>/dev/null; then
    ACTIONS+=("direnv: allowed .envrc")
  else
    REPORT+=("WARN: direnv allow failed -- run manually: direnv allow")
  fi
}

bootstrap_openspec() {
  # Skip in worktrees — openspec/ lives at repo root
  if [[ "$IS_WORKTREE" == "true" ]]; then
    return 0
  fi
  if [[ -d "$CWD/openspec" ]]; then
    return 0  # Already initialized
  fi
  if ! command -v openspec >/dev/null 2>&1; then
    return 0  # openspec not installed, skip silently
  fi
  if (cd "$CWD" && openspec init --tools claude . >/dev/null 2>&1); then
    ACTIONS+=("openspec: initialized with claude tools")
  else
    REPORT+=("WARN: openspec init failed -- run manually: openspec init --tools claude")
  fi
}

# --- Phase 4: Announced init ---

bootstrap_beads() {
  # Skip in worktrees — .beads/ lives at repo root
  if [[ "$IS_WORKTREE" == "true" ]]; then
    return 0
  fi
  if [[ -d "$CWD/.beads" ]]; then
    return 0  # Already initialized
  fi
  # Check if bd is available and dolt server is reachable
  if ! command -v bd >/dev/null 2>&1; then
    return 0  # bd not installed, skip silently
  fi
  if ! bd version >/dev/null 2>&1; then
    REPORT+=("NOTE: bd/dolt not reachable -- skipping beads init")
    return 0
  fi
  # --skip-hooks: never auto-install beads git hooks (post-checkout/post-merge/
  # pre-commit/pre-push/prepare-commit-msg). The checkout/merge hooks re-import
  # issues.jsonl and have silently reverted bd closes (jsonl-desync). There is no
  # persistent bd config for this in 1.0.5 — the flag is the only lever.
  if (cd "$CWD" && bd init --skip-hooks --prefix "$REPO_NAME" --quiet >/dev/null 2>&1); then
    ACTIONS+=("beads: initialized with prefix '$REPO_NAME' (git hooks skipped)")
  else
    REPORT+=("WARN: bd init failed -- run manually: bd init --skip-hooks --prefix $REPO_NAME")
  fi
}

repair_beads() {
  # Quick health check for beads — runs in both main repos and worktrees.
  # Catches: dead Dolt servers, missing metadata.json, worktree .beads/ shadowing.
  if ! command -v bd >/dev/null 2>&1; then
    return 0
  fi

  # Determine if beads should be available here
  local beads_dir="${BEADS_DIR:-}"
  if [[ -z "$beads_dir" && ! -d "$CWD/.beads" ]]; then
    return 0  # No beads in this project
  fi

  # Quick check: can bd count succeed? (fast — single SQL query)
  if (cd "$CWD" && bd count >/dev/null 2>&1); then
    return 0  # Healthy
  fi

  # --- Unhealthy. Try common repairs. ---

  if [[ "$IS_WORKTREE" == "true" && -d "$CWD/.beads" ]]; then
    # Worktree has its own .beads/ shadowing the main repo — remove it
    (cd "$CWD" && bd dolt stop 2>/dev/null)
    rm -rf "$CWD/.beads"
    if (cd "$CWD" && bd count >/dev/null 2>&1); then
      ACTIONS+=("beads: removed shadowing .beads/ from worktree — now using main repo's database")
      return 0
    fi
  fi

  if [[ "$IS_WORKTREE" == "false" && -d "$CWD/.beads" ]]; then
    # Main repo with broken beads — try stop + reinit
    (cd "$CWD" && bd dolt stop 2>/dev/null)
    if (cd "$CWD" && bd init --force --skip-hooks --prefix "$REPO_NAME" >/dev/null 2>&1); then
      # Try restoring backup if available
      if [[ -d "$CWD/.beads/backup" ]]; then
        (cd "$CWD" && bd backup restore >/dev/null 2>&1)
      fi
      if (cd "$CWD" && bd count >/dev/null 2>&1); then
        local count
        count=$(cd "$CWD" && bd count 2>/dev/null)
        ACTIONS+=("beads: auto-repaired database (${count} issues restored)")
        return 0
      fi
    fi
    REPORT+=("WARN: beads database broken and auto-repair failed — run: bd dolt stop && bd init --force --skip-hooks --prefix $REPO_NAME")
  fi
}

bootstrap_serena() {
  # Skip in worktrees — .serena/ lives at repo root
  if [[ "$IS_WORKTREE" == "true" ]]; then
    return 0
  fi
  if [[ -d "$CWD/.serena" ]]; then
    return 0  # Already onboarded
  fi
  # Flag for Claude to handle interactively (serena onboarding is interactive)
  ACTIONS+=("serena: needs onboarding")
  REPORT+=("ACTION: Run serena onboarding for this project (set languages, project name)")
}

# --- Phase 5: Check and report ---

check_claude_md() {
  if [[ ! -f "$CWD/CLAUDE.md" ]]; then
    REPORT+=("NOTE: No CLAUDE.md found -- consider creating project-specific instructions")
  fi
}

# --- Execute all phases ---
bootstrap_direnv
bootstrap_openspec
bootstrap_beads
repair_beads
bootstrap_serena
check_claude_md

# --- Phase 6: Agent team reminder (always emitted) ---
AGENT_PRIME="## Agent Dispatch Rules
When dispatching 2+ agents, ALWAYS: (1) TeamCreate first, (2) name + team_name on every Agent call.
The enforce_named_agents hook will BLOCK the second teamless agent. Do not test this — just use TeamCreate."

# --- Phase 7: Emit context ---
if [[ ${#ACTIONS[@]} -eq 0 && ${#REPORT[@]} -eq 0 ]]; then
  # Nothing to report from bootstrap — still emit agent prime
  jq -n --arg ctx "$AGENT_PRIME" '{
    hookSpecificOutput: {
      hookEventName: "SessionStart",
      additionalContext: $ctx
    }
  }'
  exit 0
fi

# Build the markdown report using $'\n' to avoid printf '%b' backslash injection
NL=$'\n'
OUTPUT="# Project Bootstrap Report${NL}"
OUTPUT+="Project: $REPO_NAME"
if [[ "$IS_WORKTREE" == "true" ]]; then
  OUTPUT+=" (worktree)"
fi
OUTPUT+="${NL}"

if [[ ${#ACTIONS[@]} -gt 0 ]]; then
  OUTPUT+="${NL}## Initialized${NL}"
  for action in "${ACTIONS[@]}"; do
    OUTPUT+="- ${action}${NL}"
  done
fi

if [[ ${#REPORT[@]} -gt 0 ]]; then
  OUTPUT+="${NL}## Attention${NL}"
  for line in "${REPORT[@]}"; do
    OUTPUT+="- ${line}${NL}"
  done
fi

# Append agent prime to output
OUTPUT+="${NL}${AGENT_PRIME}${NL}"

# Emit as SessionStart hook output using jq for safe JSON encoding
jq -n --arg ctx "$OUTPUT" '{
  hookSpecificOutput: {
    hookEventName: "SessionStart",
    additionalContext: $ctx
  }
}'

exit 0
