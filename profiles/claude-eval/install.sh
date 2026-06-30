#!/usr/bin/env bash
set -euo pipefail

PROFILE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$PROFILE_DIR/../.." && pwd)"
TARGET="${HOME}/.claude"
BEADS_TARGET=""
MODE="symlink"
PROFILE="gates"
FORCE=false
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"

usage() {
  cat <<'EOF'
Usage: profiles/claude-eval/install.sh [options]

Options:
  --target PATH       Claude config directory to populate (default: ~/.claude)
  --beads-target PATH Beads config directory for workflow profile
                      (default: sibling .beads next to target .claude)
  --mode MODE         symlink or copy (default: symlink)
  --profile NAME      gates or workflow (default: gates)
  --force            Backup existing target files/directories before replacing
  --help             Show this help

Use an empty scratch target for benchmark runs.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target)
      TARGET="$2"
      shift 2
      ;;
    --beads-target)
      BEADS_TARGET="$2"
      shift 2
      ;;
    --mode)
      MODE="$2"
      shift 2
      ;;
    --profile)
      PROFILE="$2"
      shift 2
      ;;
    --force)
      FORCE=true
      shift
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

case "$MODE" in
  symlink|copy) ;;
  *)
    echo "--mode must be symlink or copy" >&2
    exit 1
    ;;
esac

case "$PROFILE" in
  gates|workflow) ;;
  *)
    echo "--profile must be gates or workflow" >&2
    exit 1
    ;;
esac

if [[ -z "$BEADS_TARGET" ]]; then
  BEADS_TARGET="$(dirname "$TARGET")/.beads"
fi

backup_or_fail() {
  local dest="$1"
  if [[ ! -e "$dest" && ! -L "$dest" ]]; then
    return 0
  fi
  if [[ "$FORCE" != true ]]; then
    echo "Refusing to replace existing path without --force: $dest" >&2
    exit 1
  fi
  mv "$dest" "${dest}.backup-${TIMESTAMP}"
}

install_path() {
  local src="$1"
  local dest="$2"
  mkdir -p "$(dirname "$dest")"
  backup_or_fail "$dest"
  if [[ "$MODE" == "copy" ]]; then
    cp -R "$src" "$dest"
  else
    ln -s "$src" "$dest"
  fi
}

install_glob() {
  local src_dir="$1"
  local dest_dir="$2"
  shift 2
  mkdir -p "$dest_dir"
  local pattern path
  for pattern in "$@"; do
    for path in "$src_dir"/$pattern; do
      [[ -e "$path" ]] || continue
      install_path "$path" "$dest_dir/$(basename "$path")"
    done
  done
}

echo "==> Installing Escapement Claude eval profile"
echo "    repo:   $REPO_DIR"
echo "    target: $TARGET"
echo "    beads:  $BEADS_TARGET"
echo "    mode:   $MODE"
echo "    profile: $PROFILE"

mkdir -p "$TARGET"/{hooks,skills,rules,commands,agents,harness/bin,harness/schemas}

if [[ "$PROFILE" == "workflow" ]]; then
  install_path "$PROFILE_DIR/settings.workflow.json" "$TARGET/settings.json"
else
  install_path "$PROFILE_DIR/settings.json" "$TARGET/settings.json"
fi

install_glob "$REPO_DIR/claude/hooks" "$TARGET/hooks" "*.py" "*.sh"
install_glob "$REPO_DIR/claude/rules" "$TARGET/rules" "*.md"
install_glob "$REPO_DIR/claude/commands" "$TARGET/commands" "*.md"
install_glob "$REPO_DIR/claude/agents" "$TARGET/agents" "*.md"
install_glob "$REPO_DIR/harness/bin" "$TARGET/harness/bin" "*.py" "verify"
install_glob "$REPO_DIR/harness/schemas" "$TARGET/harness/schemas" "*.json"

for skill in "$REPO_DIR"/claude/skills/*; do
  [[ -d "$skill" ]] || continue
  install_path "$skill" "$TARGET/skills/$(basename "$skill")"
done

if [[ "$PROFILE" == "workflow" ]]; then
  mkdir -p "$BEADS_TARGET/formulas"
  install_glob "$REPO_DIR/beads/formulas" "$BEADS_TARGET/formulas" "*.json"
  install_path "$REPO_DIR/beads/mol-status.sh" "$BEADS_TARGET/mol-status.sh"
fi

python3 "$PROFILE_DIR/doctor.py" --target "$TARGET"
if [[ "$PROFILE" == "workflow" ]]; then
  python3 "$PROFILE_DIR/doctor.py" --target "$TARGET" --beads-target "$BEADS_TARGET" --profile workflow
fi

echo "==> Claude eval profile installed"
