---
op: research-findings-persistence
slots:
  wire_loss:
    claude: |-
      Anything load-bearing that exists **only** in a `SendMessage` is lost the moment the
      sending agent shuts down. The lead's transcript is the only other copy, and compaction
      erases it — silent, total, unrecoverable loss of dispatched work.
    codex: |-
      Anything load-bearing that exists **only** in a `send_message` payload or a spawned agent's
      final response is lost the moment the agent is closed. The lead's transcript is the only
      other copy, and compaction erases it — silent, total, unrecoverable loss of dispatched work.
    pi: |-
      Anything load-bearing that exists **only** in a child's returned output, a `contact_supervisor`
      message, or a `runs.steer` relay is lost the moment the child exits. The lead's transcript is
      the only other copy, and compaction erases it — silent, total, unrecoverable loss of
      dispatched work.
  pointer_rule:
    claude: |-
      **Every dispatched agent writes its complete artifact to a file BEFORE sending its pointer
      message.** The `SendMessage` is a pointer — "done, findings at `<path>`" — **never the
      payload.** The agent that *has* the work persists it, rather than relying on the lead to
      catch a fleeting message. This survives both agent shutdown and lead-transcript compaction.
    codex: |-
      **Every spawned agent writes its complete artifact to a file BEFORE sending its pointer
      message.** Its `send_message` / final response is a pointer — "done, findings at `<path>`" —
      **never the payload.** The agent that *has* the work persists it, rather than relying on the
      lead to catch a fleeting message. This survives both agent shutdown and lead-transcript compaction.
    pi: |-
      **Every dispatched child writes its complete artifact to a file BEFORE returning its pointer.**
      Give each `runs.run` / `runs.all` item an explicit `output` path; its returned output and any
      `contact_supervisor` message are a pointer — "done, findings at `<path>`" — **never the
      payload.** The child that *has* the work persists it, rather than relying on the lead to
      catch a fleeting message. This survives both child exit and lead-transcript compaction.
  lead_enforcement:
    claude: |-
      The **lead's existing continuation-harness contract** is the enforcement — no new
      machinery, no agent-side shutdown hook (coercive at the worst layer; can't know
      which file was owed; no escape path for a legit write failure). Make the lead's
      `--verify` blocking and substance-checking (value-not-presence — a touched empty
      file must fail):
    codex: |-
      The **lead's own verification step** is the enforcement — no new machinery, no
      agent-side shutdown hook (coercive at the worst layer; can't know which file was
      owed; no escape path for a legit write failure). Before synthesizing, the lead runs
      this check itself and treats a non-zero exit as blocking; where the continuation
      harness is active on this host, declare the same command as the contract's
      verification command. Keep it substance-checking (value-not-presence — a touched
      empty file must fail):
    pi: |-
      The **lead's own verification step** is the enforcement — no new machinery, no
      agent-side shutdown hook (coercive at the worst layer; can't know which file was
      owed; no escape path for a legit write failure). Before synthesizing, the lead runs
      this check itself and treats a non-zero exit as blocking; where the continuation
      harness is active on this host, declare the same command as the contract's
      verification command. Keep it substance-checking (value-not-presence — a touched
      empty file must fail):
targets:
  claude: claude/rules/research-findings-persistence.md
  codex: plugins/escapement/claude/rules/research-findings-persistence.md
  pi: plugins/escapement-pi/claude/rules/research-findings-persistence.md
frontmatter:
  claude:
  codex:
  pi:
---

# Durable Artifacts — Persist Before You Point (Global Rule)

Applies to **any** multi-agent dispatch — research, review roundtables, debug fan-outs.
General agent-team hygiene, not research-specific. Home: `agent-teams-default.md` + the
`dispatching-parallel-agents` skill.

## The principle: nothing load-bearing on the wire

{{slot:wire_loss}}

## The rule

{{slot:pointer_rule}}

- **Where:** a **gitignored** `.research/<topic>-<date>/<NN>-<agent>.md`. The dispatch's
  **first action ensures `.research/` is in `.gitignore`** (add if absent). NOT `docs/` —
  that commits PII-bearing output into a product repo. NOT `/tmp` — it vanishes, which is
  the exact durability failure this fixes.
- **Format contract:** each file carries a mandated `## Findings` header. Provenance and
  uncertainty tags live **inline in the file**, never only in the message.
- **Retention:** on completion the lead **prints the path and offers cleanup** — no
  auto-delete.

<!-- escapement:detail:start -->

## Enforcement — at the consumer's gate, not the producer's

{{slot:lead_enforcement}}

```sh
set -euo pipefail
shopt -s nullglob                      # empty dir → loop body skips, no literal-glob
D=.research/<topic>-<date>; N=<agents-dispatched>
count=$(ls "$D"/*.md 2>/dev/null | wc -l | tr -d ' ')
test "$count" -eq "$N" || { echo "FAIL count: $count/$N files in $D"; exit 1; }
for f in "$D"/*.md; do
  grep -q '^## Findings' "$f" || { echo "FAIL no-Findings-header: $f"; exit 1; }
  test "$(sed -n '/^## Findings/,$p' "$f" | grep -cve '^[[:space:]]*$')" -ge 5 \
    || { echo "FAIL stub-under-header: $f"; exit 1; }
done
echo "OK: $N substantive findings files in $D"
```

The count check is the headline guard, so it **must** carry its own `|| exit 1`
(do not rely on `set -e` for a bare `test`). Without it, a run with 3 of 10 files
present would fall through to the loop and pass — the gate that doesn't fire.

If a file is missing or a stub, **re-dispatch or ping that agent** — do not
synthesize from the transcript.

**Day-2 escalation (only if the observe phase shows agents skipping the file):**
a producer-side hook with an escape path in the denial (`write file OR send
inline + --persist-waiver "<why>"`), `_gate_signal.record(gate=
'research-persistence', …)`, and the same substance check. Behavior precedes
belief — ship the rule + the lead-side contract first.


<!-- escapement:detail:end -->
