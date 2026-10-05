#!/bin/bash
# Refresh every installed host on Escapement's declared deployment path.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
bash "$REPO_DIR/scripts/plugin-update.sh"
bash "$REPO_DIR/scripts/codex-plugin-update.sh"
bash "$REPO_DIR/scripts/omp-plugin-update.sh"
