#!/bin/bash
# OMP owns its package transaction; Escapement verifies the installed outcome.
set -euo pipefail
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec python3 "$REPO_DIR/scripts/verify_omp_plugin.py" --upgrade --source "$REPO_DIR" "$@"
