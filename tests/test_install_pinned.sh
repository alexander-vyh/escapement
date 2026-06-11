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

# ===========================================================================
# B — --update pin-dir drift (bead claude-workflow-setup-egk)
#
# A CWS-era machine has ~/.claude/* symlinks resolving into ~/.claude/.cws-pinned.
# A bare `./INSTALL.sh --update` (no env override) currently refreshes
# ~/.claude/.escapement-pinned (a checkout NOTHING links to) while .cws-pinned
# stays stale. THE FIX: --update resolves the EFFECTIVE pin dir from where a
# deployed sentinel symlink actually points, and updates THAT.
#
# Hermetic: a throwaway HOME; a local clone acting as the "remote" so we can
# advance it and observe whether the LIVE pinned dir fast-forwards.
# ===========================================================================

# Build a local bare-ish remote we control (clone of REPO at main) so we can add
# a commit and see whether --update pulls it into the LIVE pin dir.
T3="$(mktemp -d)"; trap 'rm -rf "$T1" "${T2:-}" "${T3:-}"' EXIT
REMOTE="$T3/remote"
git clone --quiet "$REPO" "$REMOTE" >/dev/null 2>&1 || bad "could not clone local remote"
git -C "$REMOTE" checkout --quiet main 2>/dev/null || git -C "$REMOTE" checkout --quiet -b main

# --- B-setup: simulate a CWS-era install whose symlinks point into .cws-pinned -
# Install with CWS_PIN_DIR set so the pinned checkout lands at .cws-pinned and the
# symlinks resolve there (the legacy layout the drift bug lives in).
HOME="$T3" CWS_PIN_DIR="$T3/.claude/.cws-pinned" \
  ESCAPEMENT_PIN_REMOTE="$REMOTE" ESCAPEMENT_PIN_REF="main" \
  bash "$REPO/INSTALL.sh" >"$T3/install.log" 2>&1 || { cat "$T3/install.log"; bad "CWS-era install exited non-zero"; }

CWS_PIN="$T3/.claude/.cws-pinned"
ESC_PIN="$T3/.claude/.escapement-pinned"
SENTINEL="$T3/.claude/hooks/spec_id_enforcement.py"

if [ -L "$SENTINEL" ]; then
  stgt="$(readlink "$SENTINEL")"
  case "$stgt" in
    *"/.cws-pinned/"*) ok "B-setup: CWS-era symlinks resolve into .cws-pinned" ;;
    *) bad "B-setup: expected symlink into .cws-pinned, got $stgt" ;;
  esac
else
  bad "B-setup: no sentinel symlink deployed"
fi

# Record the live pin dir's commit, then advance the remote by one commit.
cws_before="$(git -C "$CWS_PIN" rev-parse HEAD 2>/dev/null || echo MISSING)"
( cd "$REMOTE" && echo "drift-test $(date +%s)" > _drift_marker.txt \
    && git add _drift_marker.txt && git -c user.email=t@t -c user.name=t commit --quiet -m "drift advance" ) \
  || bad "could not advance the local remote"

# --- B1 + B4: a BARE --update (no env override) must refresh the LIVE pin dir ---
HOME="$T3" ESCAPEMENT_PIN_REMOTE="$REMOTE" ESCAPEMENT_PIN_REF="main" \
  bash "$REPO/INSTALL.sh" --update >"$T3/update.log" 2>&1
upd_rc=$?

cws_after="$(git -C "$CWS_PIN" rev-parse HEAD 2>/dev/null || echo MISSING)"

# B1: the dir the symlinks resolve into (.cws-pinned) must have advanced.
if [ "$cws_after" != "$cws_before" ] && [ "$cws_after" != "MISSING" ]; then
  ok "B1: bare --update advanced the LIVE pin dir (.cws-pinned) the symlinks point into"
else
  bad "B1: bare --update did NOT advance .cws-pinned (before=$cws_before after=$cws_after) — drift: it refreshed a dir nothing links to"
fi

# B4: it must NOT have silently created/advanced a .escapement-pinned that nothing
# links to while leaving .cws-pinned stale. (If the impl chooses 'fail loudly'
# instead of redirect, a non-zero rc with .cws-pinned untouched is also acceptable;
# the forbidden outcome is silent wrong-dir success.)
if [ "$cws_after" != "$cws_before" ]; then
  ok "B4: no silent wrong-dir update (live dir advanced)"
elif [ "$upd_rc" -ne 0 ]; then
  ok "B4: --update failed loudly rather than silently updating the wrong dir"
else
  bad "B4: --update exited 0 but the live pin dir is stale — the silent drift this gate forbids"
fi

# --- B2: an explicit ESCAPEMENT_PIN_DIR override must WIN over symlink resolution -
# Point the override at .escapement-pinned explicitly; that dir (not .cws-pinned)
# should be the one created/refreshed.
HOME="$T3" ESCAPEMENT_PIN_DIR="$ESC_PIN" ESCAPEMENT_PIN_REMOTE="$REMOTE" ESCAPEMENT_PIN_REF="main" \
  bash "$REPO/INSTALL.sh" --update >"$T3/update_override.log" 2>&1 \
  || bad "B2: explicit-override --update exited non-zero"
if [ -d "$ESC_PIN/.git" ]; then
  ok "B2: explicit ESCAPEMENT_PIN_DIR override refreshed the named dir (.escapement-pinned)"
else
  bad "B2: explicit override did not act on the named dir ($ESC_PIN)"
fi

# --- B3: a FRESH install (no deployed symlinks) keeps current default behavior ---
T4="$(mktemp -d)"; trap 'rm -rf "$T1" "${T2:-}" "${T3:-}" "${T4:-}"' EXIT
HOME="$T4" ESCAPEMENT_PIN_REMOTE="$REMOTE" ESCAPEMENT_PIN_REF="main" \
  bash "$REPO/INSTALL.sh" --update >"$T4/update_fresh.log" 2>&1 \
  || bad "B3: fresh --update exited non-zero"
if [ -d "$T4/.claude/.escapement-pinned/.git" ]; then
  ok "B3: fresh --update (no symlinks to resolve) uses the default .escapement-pinned"
else
  bad "B3: fresh --update did not create the default pinned checkout"
fi

echo
if [ "$fail" -eq 0 ]; then echo "PASS — installer deploys from a pinned checkout (and --dev opts back to live tree); --update tracks the live pin dir"; exit 0
else echo "FAIL — see above"; exit 1; fi
