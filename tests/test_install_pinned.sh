#!/usr/bin/env bash
# Test: INSTALL.sh deploys ~/.claude symlinks from a PINNED checkout, not the live
# working tree (bead claude-workflow-setup-ft1).
#
# Business invariant: after `INSTALL.sh`, a deployed symlink (e.g. a hook) must
# resolve into a pinned checkout that is INDEPENDENT of the dev working tree's
# branch — so a branch switch in the source repo can never break machine-wide
# hooks. The fragile implementation this rejects is the prior behavior: symlinking
# straight into the source working tree ($REPO_DIR).
#
# Offline + isolated: runs the installer against a throwaway HOME, pinning from the
# LOCAL repo as the remote (ESCAPEMENT_PIN_REMOTE) so no network and no touch to real ~/.claude.
#
# Run: bash tests/test_install_pinned.sh
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fail=0
note() { printf '  %s\n' "$*"; }
ok()   { printf '  ok: %s\n' "$*"; }
bad()  { printf '  FAIL: %s\n' "$*"; fail=1; }

# --- default install: symlinks must point into the pinned checkout --------------
T1="$(mktemp -d)"; trap 'rm -rf "$T1" "${T2:-}"' EXIT
HOME="$T1" ESCAPEMENT_PIN_REMOTE="$REPO" ESCAPEMENT_PIN_REF="main" \
  bash "$REPO/INSTALL.sh" >"$T1/out.log" 2>&1 || { cat "$T1/out.log"; bad "installer exited non-zero"; }

PIN="$T1/.claude/.escapement-pinned"
LINK="$T1/.claude/hooks/spec_id_enforcement.py"

[ -d "$PIN/.git" ] && ok "pinned checkout created at ~/.claude/.escapement-pinned" \
                   || bad "no pinned checkout created (expected $PIN/.git)"

if [ -L "$LINK" ]; then
  tgt="$(readlink "$LINK")"
  case "$tgt" in
    *"/.escapement-pinned/"*) ok "deployed hook points into the pinned checkout" ;;
    *)                 bad "deployed hook points outside pinned checkout: $tgt" ;;
  esac
  # Negative control: must NOT point into the live source working tree.
  case "$tgt" in
    "$REPO"/*) bad "deployed hook points into the live working tree ($REPO) — fragile model" ;;
    *)         ok "deployed hook does NOT point into the live working tree" ;;
  esac
  [ -e "$LINK" ] && ok "deployed hook resolves to a real file" || bad "deployed hook is broken (target missing)"
else
  bad "no hook symlink deployed at $LINK"
fi

# --- --dev escape hatch: symlinks SHOULD point into the live working tree -------
T2="$(mktemp -d)"
HOME="$T2" bash "$REPO/INSTALL.sh" --dev >"$T2/out.log" 2>&1 || { cat "$T2/out.log"; bad "--dev install exited non-zero"; }
DLINK="$T2/.claude/hooks/spec_id_enforcement.py"
if [ -L "$DLINK" ]; then
  dtgt="$(readlink "$DLINK")"
  case "$dtgt" in
    "$REPO"/*) ok "--dev mode points into the live working tree (instant-edit opt-in)" ;;
    *)         bad "--dev mode did not point into the working tree: $dtgt" ;;
  esac
else
  bad "--dev install produced no hook symlink"
fi

echo
if [ "$fail" -eq 0 ]; then echo "PASS — installer deploys from a pinned checkout (and --dev opts back to live tree)"; exit 0
else echo "FAIL — see above"; exit 1; fi
