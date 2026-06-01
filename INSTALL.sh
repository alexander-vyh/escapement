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

run "mkdir -p '$CLAUDE_DIR'/{skills,rules,commands,hooks,harness,agents} '$CLAUDE_DIR'/harness/threads '$BEADS_DIR'/formulas"

# --- Symlink plan: (source_relative_to_repo, dest_absolute) ---
# Preserves directory structure. For skill directories, symlink the whole dir.
declare -a PLAN=(
  # Skills (whole directories)
  "claude/skills/discovery|$CLAUDE_DIR/skills/discovery"
  "claude/skills/work-breakdown|$CLAUDE_DIR/skills/work-breakdown"
  "claude/skills/brainstorming|$CLAUDE_DIR/skills/brainstorming"
  "claude/skills/build|$CLAUDE_DIR/skills/build"
  "claude/skills/beads-execution|$CLAUDE_DIR/skills/beads-execution"
  "claude/skills/behavioral-test-oracle-review|$CLAUDE_DIR/skills/behavioral-test-oracle-review"
  "claude/skills/dispatching-parallel-agents|$CLAUDE_DIR/skills/dispatching-parallel-agents"
  "claude/skills/subagent-driven-development|$CLAUDE_DIR/skills/subagent-driven-development"

  # Rules (individual files so user can keep their own alongside)
  "claude/rules/planning-discipline.md|$CLAUDE_DIR/rules/planning-discipline.md"
  "claude/rules/molecule-awareness.md|$CLAUDE_DIR/rules/molecule-awareness.md"
  "claude/rules/tdd-enforcement.md|$CLAUDE_DIR/rules/tdd-enforcement.md"
  "claude/rules/agent-teams-default.md|$CLAUDE_DIR/rules/agent-teams-default.md"
  "claude/rules/outcome-ownership.md|$CLAUDE_DIR/rules/outcome-ownership.md"
  "claude/rules/evidence-provenance.md|$CLAUDE_DIR/rules/evidence-provenance.md"
  "claude/rules/beads-worktree-integration.md|$CLAUDE_DIR/rules/beads-worktree-integration.md"
  "claude/rules/never-suppress.md|$CLAUDE_DIR/rules/never-suppress.md"
  "claude/rules/serena-first.md|$CLAUDE_DIR/rules/serena-first.md"
  "claude/rules/continuation-harness.md|$CLAUDE_DIR/rules/continuation-harness.md"
  "claude/rules/delicate-art-of-bureaucracy.md|$CLAUDE_DIR/rules/delicate-art-of-bureaucracy.md"
  "claude/rules/gate-design.md|$CLAUDE_DIR/rules/gate-design.md"
  "claude/rules/why-drilling.md|$CLAUDE_DIR/rules/why-drilling.md"

  # Agents (workflow-integral only — personal advisor agents live in the user's
  # own config, not in this framework. adversarial-reviewer is dispatched by
  # subagent-driven-development; test-quality-reviewer is the operational
  # counterpart to tdd-enforcement + behavioral-test-oracle-review.)
  "claude/agents/adversarial-reviewer.md|$CLAUDE_DIR/agents/adversarial-reviewer.md"
  "claude/agents/test-quality-reviewer.md|$CLAUDE_DIR/agents/test-quality-reviewer.md"

  # Commands
  "claude/commands/discovery.md|$CLAUDE_DIR/commands/discovery.md"
  "claude/commands/work-breakdown.md|$CLAUDE_DIR/commands/work-breakdown.md"
  "claude/commands/brainstorm.md|$CLAUDE_DIR/commands/brainstorm.md"
  "claude/commands/review.md|$CLAUDE_DIR/commands/review.md"

  # Hooks
  "claude/hooks/openspec_init_guard.py|$CLAUDE_DIR/hooks/openspec_init_guard.py"
  "claude/hooks/design_doc_location_guard.py|$CLAUDE_DIR/hooks/design_doc_location_guard.py"
  "claude/hooks/discovery-gate.py|$CLAUDE_DIR/hooks/discovery-gate.py"
  "claude/hooks/discovery_input_gate.py|$CLAUDE_DIR/hooks/discovery_input_gate.py"
  "claude/hooks/discovery-nudge.py|$CLAUDE_DIR/hooks/discovery-nudge.py"
  "claude/hooks/discovery-close-gate.py|$CLAUDE_DIR/hooks/discovery-close-gate.py"
  "claude/hooks/mol_status_check.py|$CLAUDE_DIR/hooks/mol_status_check.py"
  "claude/hooks/spec_id_enforcement.py|$CLAUDE_DIR/hooks/spec_id_enforcement.py"
  "claude/hooks/enforce_named_agents.py|$CLAUDE_DIR/hooks/enforce_named_agents.py"
  "claude/hooks/tdd-gate.py|$CLAUDE_DIR/hooks/tdd-gate.py"
  "claude/hooks/test_oracle_brief_gate.py|$CLAUDE_DIR/hooks/test_oracle_brief_gate.py"
  "claude/hooks/test_reminder.py|$CLAUDE_DIR/hooks/test_reminder.py"
  "claude/hooks/implementation_echo_test_gate.py|$CLAUDE_DIR/hooks/implementation_echo_test_gate.py"
  "claude/hooks/oracle_downgrade_warning_gate.py|$CLAUDE_DIR/hooks/oracle_downgrade_warning_gate.py"
  "claude/hooks/outcome_assertion_gate.py|$CLAUDE_DIR/hooks/outcome_assertion_gate.py"
  "claude/hooks/review_gate.py|$CLAUDE_DIR/hooks/review_gate.py"
  "claude/hooks/review_nudge.py|$CLAUDE_DIR/hooks/review_nudge.py"
  "claude/hooks/no_direct_send_guard.py|$CLAUDE_DIR/hooks/no_direct_send_guard.py"
  "claude/hooks/validate_no_shirking.py|$CLAUDE_DIR/hooks/validate_no_shirking.py"
  "claude/hooks/context_burn_detector.py|$CLAUDE_DIR/hooks/context_burn_detector.py"
  "claude/hooks/session_cleanup.py|$CLAUDE_DIR/hooks/session_cleanup.py"
  "claude/hooks/session_status.py|$CLAUDE_DIR/hooks/session_status.py"
  "claude/hooks/serena_preference_gate.py|$CLAUDE_DIR/hooks/serena_preference_gate.py"
  "claude/hooks/serena_preference_injection.py|$CLAUDE_DIR/hooks/serena_preference_injection.py"
  "claude/hooks/serena_onboarding_check.sh|$CLAUDE_DIR/hooks/serena_onboarding_check.sh"
  "claude/hooks/_gate_signal.py|$CLAUDE_DIR/hooks/_gate_signal.py"
  "claude/hooks/tests|$CLAUDE_DIR/hooks/tests"

  # Bin scripts (invokable from any repo cwd; resolve their own project root)
  "claude/bin|$CLAUDE_DIR/bin"

  # Continuation harness — code symlinked into ~/.claude/harness; runtime state
  # (threads/, incidents.jsonl) lives in ~/.claude/harness too (NOT the repo) and
  # is created by the mkdir below, so concurrent agents in any repo never write
  # into a project working tree.
  "harness/bin|$CLAUDE_DIR/harness/bin"
  "harness/schemas|$CLAUDE_DIR/harness/schemas"

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

# Verify the continuation-harness Stop gate is actually WIRED in the deployed
# settings — not merely present on disk. The harness code is symlinked above, but
# it does nothing unless ~/.claude/settings.json invokes stop_hook.py under Stop.
# This catches the distribution-drift bug where a user symlinks the harness but
# forgets to merge the Stop block (bead claude-workflow-setup-fxh.1).
verify_stop_gate_wired() {
  local settings="$CLAUDE_DIR/settings.json"
  if [[ ! -f "$settings" ]]; then
    echo "    ⚠  $settings not found — merge the template's Stop block (see step 1),"
    echo "       or the continuation-harness Stop gate will be inert."
    return 0
  fi
  if python3 - "$settings" <<'PY'
import json, sys
try:
    data = json.load(open(sys.argv[1]))
except Exception as e:
    print(f"    ⚠  could not parse settings.json ({e}) — verify the Stop block manually.")
    sys.exit(0)
cmds = [
    h.get("command", "")
    for grp in data.get("hooks", {}).get("Stop", [])
    for h in grp.get("hooks", [])
]
sys.exit(0 if any("stop_hook.py" in c for c in cmds) else 1)
PY
  then
    echo "    ✓  continuation-harness Stop gate is wired (stop_hook.py present under Stop)."
  else
    echo "    ⚠  continuation-harness Stop gate is NOT wired in $settings."
    echo "       The harness code is installed but DEAD until you add this under hooks.Stop:"
    echo '         { "hooks": [ { "type": "command",'
    echo '             "command": "python3 ~/.claude/harness/bin/stop_hook.py" } ] }'
    echo "       (additive — keep the existing validate_no_shirking.py entry too)."
  fi
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
  echo "==> verifying continuation-harness Stop gate wiring"
  verify_stop_gate_wired
  echo
  echo "    See README.md for full details."
else
  uninstall_plan
fi
