#!/bin/bash
# INSTALL.sh — Symlinks claude-workflow-setup into ~/.claude/ and ~/.beads/
#
# Usage:
#   ./INSTALL.sh             # install (backup existing, symlink new)
#   ./INSTALL.sh --uninstall  # remove symlinks (backups are left alone)
#   ./INSTALL.sh --dry-run    # show what would happen, change nothing
#
# Fail-fast. Backup-then-symlink — nothing is silently clobbered.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
BEADS_DIR="$HOME/.beads"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"

# --- Arg parsing ---
MODE="install"
DRY_RUN=false
for arg in "$@"; do
  case "$arg" in
    --uninstall) MODE="uninstall" ;;
    --dry-run)   DRY_RUN=true ;;
    --help|-h)
      sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) echo "Unknown arg: $arg" >&2; exit 1 ;;
  esac
done

run() {
  if [[ "$DRY_RUN" == true ]]; then
    echo "[dry-run] $*"
  else
    eval "$*"
  fi
}

# --- Pre-flight ---
echo "==> claude-workflow-setup installer"
echo "    repo:   $REPO_DIR"
echo "    claude: $CLAUDE_DIR"
echo "    beads:  $BEADS_DIR"
echo "    mode:   $MODE$([ "$DRY_RUN" == true ] && echo ' (dry-run)')"
echo

for tool in openspec bd direnv python3 jq git bash; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "WARN: '$tool' not found on PATH — some features will not work"
  fi
done

run "mkdir -p '$CLAUDE_DIR'/{skills,rules,commands,hooks} '$BEADS_DIR'/formulas"

# --- Symlink plan: (source_relative_to_repo, dest_absolute) ---
# Preserves directory structure. For skill directories, symlink the whole dir.
declare -a PLAN=(
  # Skills (whole directories)
  "claude/skills/discovery|$CLAUDE_DIR/skills/discovery"
  "claude/skills/work-breakdown|$CLAUDE_DIR/skills/work-breakdown"
  "claude/skills/brainstorming|$CLAUDE_DIR/skills/brainstorming"
  "claude/skills/build|$CLAUDE_DIR/skills/build"
  "claude/skills/beads-execution|$CLAUDE_DIR/skills/beads-execution"
  "claude/skills/dispatching-parallel-agents|$CLAUDE_DIR/skills/dispatching-parallel-agents"
  "claude/skills/subagent-driven-development|$CLAUDE_DIR/skills/subagent-driven-development"

  # Rules (individual files so user can keep their own alongside)
  "claude/rules/planning-discipline.md|$CLAUDE_DIR/rules/planning-discipline.md"
  "claude/rules/molecule-awareness.md|$CLAUDE_DIR/rules/molecule-awareness.md"
  "claude/rules/tdd-enforcement.md|$CLAUDE_DIR/rules/tdd-enforcement.md"
  "claude/rules/agent-teams-default.md|$CLAUDE_DIR/rules/agent-teams-default.md"
  "claude/rules/outcome-ownership.md|$CLAUDE_DIR/rules/outcome-ownership.md"
  "claude/rules/beads-worktree-integration.md|$CLAUDE_DIR/rules/beads-worktree-integration.md"

  # Commands
  "claude/commands/discovery.md|$CLAUDE_DIR/commands/discovery.md"
  "claude/commands/work-breakdown.md|$CLAUDE_DIR/commands/work-breakdown.md"
  "claude/commands/brainstorm.md|$CLAUDE_DIR/commands/brainstorm.md"
  "claude/commands/review.md|$CLAUDE_DIR/commands/review.md"

  # Hooks
  "claude/hooks/openspec_init_guard.py|$CLAUDE_DIR/hooks/openspec_init_guard.py"
  "claude/hooks/design_doc_location_guard.py|$CLAUDE_DIR/hooks/design_doc_location_guard.py"
  "claude/hooks/discovery-gate.py|$CLAUDE_DIR/hooks/discovery-gate.py"
  "claude/hooks/discovery-nudge.py|$CLAUDE_DIR/hooks/discovery-nudge.py"
  "claude/hooks/discovery-close-gate.py|$CLAUDE_DIR/hooks/discovery-close-gate.py"
  "claude/hooks/mol_status_check.py|$CLAUDE_DIR/hooks/mol_status_check.py"
  "claude/hooks/spec_id_enforcement.py|$CLAUDE_DIR/hooks/spec_id_enforcement.py"
  "claude/hooks/enforce_named_agents.py|$CLAUDE_DIR/hooks/enforce_named_agents.py"
  "claude/hooks/tdd-gate.py|$CLAUDE_DIR/hooks/tdd-gate.py"
  "claude/hooks/outcome_assertion_gate.py|$CLAUDE_DIR/hooks/outcome_assertion_gate.py"
  "claude/hooks/outcome-gate.sh|$CLAUDE_DIR/hooks/outcome-gate.sh"
  "claude/hooks/review_gate.py|$CLAUDE_DIR/hooks/review_gate.py"
  "claude/hooks/review_nudge.py|$CLAUDE_DIR/hooks/review_nudge.py"
  "claude/hooks/validate_no_shirking.py|$CLAUDE_DIR/hooks/validate_no_shirking.py"

  # Bootstrap
  "scripts/project-bootstrap.sh|$CLAUDE_DIR/project-bootstrap.sh"

  # Beads formulas
  "beads/formulas/mol-feature.formula.json|$BEADS_DIR/formulas/mol-feature.formula.json"
  "beads/formulas/mol-rapid.formula.json|$BEADS_DIR/formulas/mol-rapid.formula.json"
  "beads/mol-status.sh|$BEADS_DIR/mol-status.sh"
)

backup_if_exists() {
  local dest="$1"
  if [[ -L "$dest" ]]; then
    # Already a symlink — remove it (no backup needed, nothing real there)
    run "rm '$dest'"
  elif [[ -e "$dest" ]]; then
    local backup="${dest}.backup-${TIMESTAMP}"
    echo "    backup: $dest -> $backup"
    run "mv '$dest' '$backup'"
  fi
}

install_plan() {
  local installed=0
  for entry in "${PLAN[@]}"; do
    local src_rel="${entry%|*}"
    local dest="${entry#*|}"
    local src_abs="$REPO_DIR/$src_rel"

    if [[ ! -e "$src_abs" ]]; then
      echo "SKIP (source missing): $src_rel"
      continue
    fi

    backup_if_exists "$dest"
    run "ln -s '$src_abs' '$dest'"
    installed=$((installed + 1))
    echo "    link:   $dest -> $src_rel"
  done
  echo
  echo "==> installed $installed symlinks"
}

uninstall_plan() {
  local removed=0
  for entry in "${PLAN[@]}"; do
    local dest="${entry#*|}"
    if [[ -L "$dest" ]]; then
      run "rm '$dest'"
      removed=$((removed + 1))
      echo "    unlink: $dest"
    fi
  done
  echo
  echo "==> removed $removed symlinks"
  echo "    (any .backup-* files are left alone — rename manually to restore)"
}

# --- Execute ---
if [[ "$MODE" == "install" ]]; then
  install_plan
  echo
  echo "==> next steps"
  echo "    1. Merge hooks + env blocks from claude/settings.template.json into"
  echo "       your ~/.claude/settings.json (do NOT overwrite — merge)."
  echo "    2. Read claude/rules/*.md and edit to match your philosophy."
  echo "    3. Open Claude Code in a git repo under ~/GitHub/ to trigger bootstrap."
  echo
  echo "    See README.md for full details."
else
  uninstall_plan
fi
