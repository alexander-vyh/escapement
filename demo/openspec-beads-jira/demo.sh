#!/usr/bin/env bash
# =============================================================================
# demo.sh — OpenSpec <> beads <> harness <> Jira, end to end, LIVE.
#
# Tells one story: a single spec-id thread is woven through four tools, and
# every hop is enforced by a gate you can watch fire. Nothing here is mocked —
# the OpenSpec spec is real, the beads are real (created and torn down), the
# enforcement hook is the real one, the contract is really derived.
#
# Usage:
#   ./demo.sh             # interactive: pauses between acts (presenter mode)
#   ./demo.sh --no-pause  # run straight through, no pauses
#   ./demo.sh --check     # non-interactive + ASSERT every link  (the oracle)
#
# Safe & repeatable: every bead it creates is prefixed OBJDEMO and deleted on
# exit (even on Ctrl-C); the derived contract is written to an isolated demo
# session dir and removed; any Jira config it sets is saved and restored.
# =============================================================================
set -uo pipefail

# ---- modes ------------------------------------------------------------------
PAUSE=1; CHECK=0
for a in "$@"; do
  case "$a" in
    --no-pause) PAUSE=0 ;;
    --check)    PAUSE=0; CHECK=1 ;;
    -h|--help)  echo "usage: $0 [--no-pause] [--check]"; exit 0 ;;
    *) echo "unknown arg: $a" >&2; exit 64 ;;
  esac
done

# ---- locate repo root (script lives at <repo>/demo/openspec-beads-jira/) ----
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO" || { echo "cannot cd to repo root" >&2; exit 1; }

# ---- real artifacts the demo leans on ---------------------------------------
SPEC_REL="openspec/changes/continuation-harness/specs/outcome-contract.md"
GOOD_ANCHOR="Contract-structure"          # matches "### Requirement: Contract structure"
BAD_ANCHOR="Nonexistent-requirement"      # matches nothing — the negative control
HOOK="claude/hooks/spec_id_enforcement.py"
PREFLIGHT="claude/bin/spec_id_preflight.py"
DERIVE="harness/bin/derive_contract.py"
DEMO_SESSION="objdemo-$$"
PREFIX="OBJDEMO"

# ---- cosmetics --------------------------------------------------------------
if [ -t 1 ]; then
  B=$'\e[1m'; G=$'\e[32m'; R=$'\e[31m'; Y=$'\e[33m'; C=$'\e[36m'; D=$'\e[2m'; X=$'\e[0m'
else B=; G=; R=; Y=; C=; D=; X=; fi

CREATED_BEADS=()
FAILS=0

# ---- teardown (always runs) -------------------------------------------------
cleanup() {
  for id in "${CREATED_BEADS[@]:-}"; do
    [ -n "$id" ] && bd delete "$id" --cascade --force >/dev/null 2>&1
  done
  rm -rf "$HOME/.claude/harness/threads/$DEMO_SESSION" 2>/dev/null
  if [ -n "${_JIRA_URL_SAVED+x}" ];  then bd config set jira.url     "$_JIRA_URL_SAVED"  >/dev/null 2>&1; fi
  if [ -n "${_JIRA_PROJ_SAVED+x}" ]; then bd config set jira.project "$_JIRA_PROJ_SAVED" >/dev/null 2>&1; fi
}
trap cleanup EXIT

# ---- output helpers ---------------------------------------------------------
hr()    { printf '%s\n' "${D}──────────────────────────────────────────────────────────────${X}"; }
act()   { echo; hr; printf '%s\n' "${B}${C}$*${X}"; hr; }
say()   { printf '%s\n' "$*"; }
note()  { printf '  %s%s%s\n' "$D" "$*" "$X"; }
run()   { printf '  %s$ %s%s\n' "$Y" "$*" "$X"; }
good()  { printf '  %s%s%s\n' "$G" "$*" "$X"; }
bad()   { printf '  %s%s%s\n' "$R" "$*" "$X"; }
pause() { [ "$PAUSE" = 1 ] && { printf '\n%s  ▸ press enter%s' "$D" "$X"; read -r _ || true; }; return 0; }

# ---- assertion: counts failures; ✓ shown only in --check, ✗ always ----------
expect() { # expect "<label>" "<expected>" "<actual>"
  if [ "$2" = "$3" ]; then
    [ "$CHECK" = 1 ] && printf '  %s✓ %s%s\n' "$G" "$1" "$X"
  else
    printf '  %s✗ %s  (expected=%s got=%s)%s\n' "$R" "$1" "$2" "$3" "$X"
    FAILS=$((FAILS + 1))
  fi
}

# ---- create a bead and echo its id ------------------------------------------
# NOTE: callers run this via $(...) which is a SUBSHELL — array mutations here
# would not survive to the parent, so tracking for teardown is the caller's job
# via track() in the parent scope. (Getting this wrong silently leaks beads.)
bd_new() { # bd_new "title" [extra bd-create args...]
  local title="$1"; shift
  bd create "$title" "$@" --json 2>/dev/null \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); d=d[0] if isinstance(d,list) else d; print(d["id"])'
}

# ---- register a bead id for teardown (must run in the PARENT shell) ----------
track() { CREATED_BEADS+=("$1"); }

# ---- run the REAL enforcement hook over a synthesized PreToolUse event ------
# Echoes the verdict the hook would return to Claude Code: DENY or ALLOW.
verdict() { # verdict "<bd create command string>"
  local ev out
  ev=$(REPO="$REPO" python3 -c 'import json,os,sys; print(json.dumps({"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":sys.argv[1]},"cwd":os.environ["REPO"]}))' "$1")
  out=$(printf '%s' "$ev" | python3 "$HOOK" 2>/dev/null)
  if printf '%s' "$out" | grep -q '"permissionDecision": *"deny"'; then echo DENY; else echo ALLOW; fi
}

# =============================================================================
# ACT 0 — the thread
# =============================================================================
act "OpenSpec ⇄ beads ⇄ harness ⇄ Jira — one spec-id, four tools, live"
cat <<EOF

  ${B}design intent${X}        ${B}task state${X}         ${B}"is it done?"${X}        ${B}org tracker${X}
  ┌───────────────┐    ┌────────────┐     ┌──────────────┐     ┌──────────┐
  │   OpenSpec    │    │   beads    │     │  continuation│     │   Jira   │
  │  ### Require- │───▶│ bd create  │────▶│   -harness   │     │  native  │
  │  ment: ...    │    │ --spec-id  │     │ contract.json│     │ bd jira  │
  └───────────────┘    └────────────┘     └──────────────┘     └──────────┘
          │                  │                    │                  ▲
          └──────────────────┴── spec-id: path#anchor ───────────────┘
                 the one thread that survives every hop

  OpenSpec owns *why* (design). beads owns *what's left* (tasks).
  The harness owns *are we done* (a runnable oracle). Jira is a projection.
  The spec-id is the join key — and a gate guards every hop.
EOF
pause

# =============================================================================
# ACT 1 — OpenSpec is the source of truth
# =============================================================================
act "ACT 1 · Design intent lives in OpenSpec (real file, real requirement)"
run "grep -n '### Requirement:' $SPEC_REL"
grep -n '### Requirement:' "$SPEC_REL" | sed 's/^/    /'
note "A spec-id will anchor to one of these headings. This is the authority on"
note "design intent — beads never re-states it, it points at it."
REQ_COUNT=$(grep -c '### Requirement:' "$SPEC_REL")
expect "spec file has Requirement headings to anchor to" "true" "$([ "$REQ_COUNT" -gt 0 ] && echo true || echo false)"
pause

# =============================================================================
# ACT 2 — the spec-id is validated by VALUE, not presence
# =============================================================================
act "ACT 2 · The spec-id gate validates the value resolves (not just presence)"
note "spec_id_enforcement.validate_spec_id() — the same function the live hook uses."
for kind in good bad placeholder; do
  case "$kind" in
    good)        SID="$SPEC_REL#$GOOD_ANCHOR"; want=VALID ;;
    bad)         SID="$SPEC_REL#$BAD_ANCHOR";  want=INVALID ;;
    placeholder) SID="none";                   want=INVALID ;;
  esac
  res=$(SID="$SID" REPO="$REPO" python3 - <<'PY'
import os, sys
sys.path.insert(0, os.path.join(os.environ["REPO"], "claude", "hooks"))
from pathlib import Path
from spec_id_enforcement import validate_spec_id
ok, err = validate_spec_id(os.environ["SID"], Path(os.environ["REPO"]))
print("VALID" if ok else "INVALID")
print(err)
PY
)
  verdict_word=$(printf '%s' "$res" | sed -n 1p)
  reason=$(printf '%s' "$res" | sed -n 2p)
  run "validate_spec_id(\"$SID\")"
  if [ "$verdict_word" = VALID ]; then good "  → VALID  (resolves to a real ### Requirement: heading)"
  else bad "  → INVALID  ${reason:+— $reason}"; fi
  expect "spec-id value check ($kind)" "$want" "$verdict_word"
done
note "The 'bad anchor' and 'placeholder' cases are negative controls: a presence-only"
note "gate would pass --spec-id none. This one reads the file and checks the anchor."
pause

# =============================================================================
# ACT 3 — beads carries the link, and the gate ENFORCES it (live hook)
# =============================================================================
act "ACT 3 · The gate fires on real bd create commands (watch it block)"
EPIC=$(bd_new "$PREFIX mol-feature epic"); track "$EPIC"
bd label add "$EPIC" mol-feature >/dev/null 2>&1
note "Created a mol-feature molecule epic: $EPIC  (auto-deleted at exit)"
echo

declare -a CASES=(
  "missing spec-id|bd create \"child\" --parent $EPIC|DENY"
  "bad anchor     |bd create \"child\" --parent $EPIC --spec-id $SPEC_REL#$BAD_ANCHOR|DENY"
  "good spec-id   |bd create \"child\" --parent $EPIC --spec-id $SPEC_REL#$GOOD_ANCHOR|ALLOW"
  "weak waiver    |bd create \"child\" --parent $EPIC --spec-waiver 'too short'|DENY"
  "real waiver    |bd create \"child\" --parent $EPIC --spec-waiver 'spec deferred while we de-risk the parser approach in a spike'|ALLOW"
)
for row in "${CASES[@]}"; do
  IFS='|' read -r label cmd want <<<"$row"
  got=$(verdict "$cmd")
  run "$cmd"
  if [ "$got" = DENY ]; then bad "  → DENY  (gate blocked it)"; else good "  → ALLOW (gate let it through)"; fi
  expect "gate verdict — $(echo "$label" | xargs)" "$want" "$got"
done
note "Same molecule, five commands. The gate blocks the three that break"
note "traceability and allows the two that preserve it — including the"
note "first-class waiver escape (with a substantive reason)."
echo
# Now actually create the linked child we'll carry forward.
ACC=$'Bead spec link resolves and the demo chain stays intact.\n\n```verify\npython3 claude/bin/spec_id_preflight.py\n```'
CHILD=$(bd_new "$PREFIX child task" --parent "$EPIC" --spec-id "$SPEC_REL#Contract structure" --acceptance "$ACC"); track "$CHILD"
SPEC_ON_BEAD=$(bd show "$CHILD" --json 2>/dev/null | python3 -c 'import json,sys;o=json.load(sys.stdin);o=o[0] if isinstance(o,list) else o;print(o.get("spec_id") or "")')
run "bd show $CHILD --json   # spec_id is a first-class field"
good "  spec_id = $SPEC_ON_BEAD"
expect "bead carries the spec-id as a first-class field" "$SPEC_REL#Contract structure" "$SPEC_ON_BEAD"
pause

# =============================================================================
# ACT 4 — the bead's "done" oracle becomes a harness contract
# =============================================================================
act "ACT 4 · bead → continuation-harness contract (oracle declared ONCE)"
note "The bead declares its machine oracle inside acceptance criteria, in a"
note "\`\`\`verify fence. derive_contract.py turns that into the contract the"
note "Stop-gate runs. The goal+oracle are authored once, on the bead — not re-typed."
run "CLAUDE_CODE_SESSION_ID=<demo> derive_contract.py --bead $CHILD"
CLAUDE_CODE_SESSION_ID="$DEMO_SESSION" python3 "$DERIVE" --bead "$CHILD" 2>&1 | sed 's/^/    /'
DERIVED_CMD=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("verification_command",""))' "$HOME/.claude/harness/threads/$DEMO_SESSION/contract.json" 2>/dev/null || echo "")
expect "contract derived with the bead's verify oracle" "python3 claude/bin/spec_id_preflight.py" "$DERIVED_CMD"
echo
note "Negative control: a bead with NO verify fence must fail closed —"
note "derivation refuses to invent a passing oracle (never-suppress)."
NOORACLE=$(bd_new "$PREFIX no-oracle task" --acceptance "Just prose. No verify fence here."); track "$NOORACLE"
run "derive_contract.py --bead $NOORACLE   # expect: refusal, exit 2"
CLAUDE_CODE_SESSION_ID="$DEMO_SESSION" python3 "$DERIVE" --bead "$NOORACLE" >/dev/null 2>/tmp/objdemo_noerr.$$
NO_RC=$?
bad "  → exit $NO_RC: $(head -1 /tmp/objdemo_noerr.$$ 2>/dev/null)"
rm -f /tmp/objdemo_noerr.$$
expect "no-oracle bead fails closed (exit 2)" "2" "$NO_RC"
pause

# =============================================================================
# ACT 5 — the link stays honest over time (referential integrity)
# =============================================================================
act "ACT 5 · Referential integrity — spec-ids can't silently rot"
note "spec_id_enforcement validates at CREATE time. But specs get edited later."
note "spec_id_preflight re-validates every bead's spec-id against current headings."
run "python3 $PREFLIGHT"
python3 "$PREFLIGHT" 2>&1 | sed 's/^/    /'
PF_RC=${PIPESTATUS[0]:-$?}
expect "preflight ran (bd reachable; 0=clean / 1=orphans, not 2=error)" "true" "$([ "$PF_RC" != 2 ] && echo true || echo false)"
echo
note "How an orphan is caught: if someone renames the requirement heading,"
note "the baked-in anchor stops resolving. Demonstrated deterministically:"
ORPHAN=$(REPO="$REPO" SPEC_REL="$SPEC_REL" BAD="$BAD_ANCHOR" python3 - <<'PY'
import os, sys
sys.path.insert(0, os.path.join(os.environ["REPO"], "claude", "bin"))
from pathlib import Path
from spec_id_preflight import check_spec_id
sid = f"{os.environ['SPEC_REL']}#{os.environ['BAD']}"
ok, reason = check_spec_id(sid, Path(os.environ["REPO"]))
print("RESOLVED" if ok else "ORPHANED")
print(reason)
PY
)
ow=$(printf '%s' "$ORPHAN" | sed -n 1p)
orsn=$(printf '%s' "$ORPHAN" | sed -n 2p)
bad "  check_spec_id(...#$BAD_ANCHOR) → $ow"
note "  $orsn"
expect "renamed/removed anchor is detected as ORPHANED" "ORPHANED" "$ow"
pause

# =============================================================================
# ACT 6 — projection into Jira (native bd jira, credential-adaptive)
# =============================================================================
act "ACT 6 · Projecting the bead (with its spec-id) into Jira"
TOK=$(bd config get jira.api_token 2>/dev/null)
HAS_TOKEN=0
{ [ -n "${JIRA_API_TOKEN:-}" ]; } && HAS_TOKEN=1
case "$TOK" in ""|*"(not set)"*) : ;; *) HAS_TOKEN=1 ;; esac

if [ "$HAS_TOKEN" = 1 ]; then
  note "Jira credentials detected — running a REAL dry-run (no ticket is written)."
  _JIRA_URL_SAVED=$(bd config get jira.url 2>/dev/null);     case "$_JIRA_URL_SAVED" in *"(not set)"*) _JIRA_URL_SAVED="";; esac
  _JIRA_PROJ_SAVED=$(bd config get jira.project 2>/dev/null); case "$_JIRA_PROJ_SAVED" in *"(not set)"*) _JIRA_PROJ_SAVED="";; esac
  run "bd jira push $CHILD --dry-run"
  bd jira push "$CHILD" --dry-run 2>&1 | sed 's/^/    /'
else
  note "No Jira credentials configured — showing the native command surface."
  note "(Not faking a Jira response: a dry-run still calls the Jira API for"
  note " project metadata, so a real preview needs real credentials.)"
  echo
  run "bd config set jira.url \"https://you.atlassian.net\""
  run "bd config set jira.project \"PROJ\""
  run "bd config set jira.api_token \"<token>\"   # or export JIRA_API_TOKEN"
  run "bd jira push $CHILD --dry-run              # preview the projection"
  run "bd jira sync --push --create-only          # push new beads to Jira"
  run "bd jira sync --pull                         # import Jira issues as beads"
  echo
  good "  The bead already carries spec_id=\"$SPEC_REL#Contract structure\""
  good "  as a first-class field — so the OpenSpec link travels with it into Jira."
fi
note "Bidirectional: bd jira sync reconciles both ways (newest-wins, or --prefer-*)."
pause

# =============================================================================
# Recap
# =============================================================================
act "Recap — what you just watched (all live, nothing mocked)"
cat <<EOF
  1. OpenSpec held the requirement.                    (real spec file)
  2. The spec-id resolved by value — bad/placeholder blocked.   (ACT 2)
  3. The gate fired on real bd create commands.        (ACT 3, live hook)
  4. The bead's verify fence became a harness contract; no-oracle failed closed. (ACT 4)
  5. Preflight catches spec-ids that rot when headings change. (ACT 5)
  6. bd jira projects the bead — spec-id and all — into Jira.   (ACT 6)

  One thread (spec-id), four tools, a gate at every hop.
EOF

echo
if [ "$FAILS" -eq 0 ]; then
  good "ALL LINKS VERIFIED ✓"
  exit 0
else
  bad "$FAILS link(s) FAILED — the chain is broken above."
  exit 1
fi
