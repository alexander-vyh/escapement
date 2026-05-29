# Demo cheat-sheet — OpenSpec ⇄ beads ⇄ harness ⇄ Jira

A one-page companion to `demo.sh`. Everything below is **live** in this repo —
no slideware, no mocks. The demo creates real beads and tears them down.

## Run it

```bash
demo/openspec-beads-jira/demo.sh            # presenter mode: pauses between acts
demo/openspec-beads-jira/demo.sh --no-pause # straight through
demo/openspec-beads-jira/demo.sh --check    # non-interactive + ASSERT every link
```

`--check` is also the script's own regression oracle: it asserts each link and
exits non-zero if any is broken. Safe to run anytime — created beads are
prefixed `OBJDEMO` and deleted on exit (even on Ctrl-C).

## The one-sentence story

> **A single `spec-id` (`path#anchor`) is the join key threaded through four
> tools, and a gate guards every hop.** OpenSpec owns *why* (design intent),
> beads owns *what's left* (task state), the continuation-harness owns *are we
> done* (a runnable oracle), and Jira is a projection of the bead.

```
  design intent        task state          "is it done?"        org tracker
   OpenSpec      ──▶     beads        ──▶    harness        ⇄      Jira
   ### Require-          bd create           contract.json         bd jira
   ment: ...            --spec-id           (verify oracle)        sync/push
        └────────────────┴──── spec-id: path#anchor ───────────────┘
```

## What each act proves (and the talking point)

| Act | Mechanism (real code) | Talking point |
|----|------------------------|---------------|
| 1 | `### Requirement:` in `openspec/changes/.../specs/outcome-contract.md` | Design intent has one home. beads points at it, never re-states it. |
| 2 | `spec_id_enforcement.validate_spec_id()` | The gate validates the **value resolves**, not just that a flag is present. `--spec-id none` is rejected (anti-mock-bureaucracy). |
| 3 | the live `spec_id_enforcement.py` hook over real `bd create` commands | Watch it **block** the 3 commands that break traceability and **allow** the 2 that keep it — including the reasoned-waiver escape hatch. |
| 4 | `derive_contract.py --bead <id>` | The bead declares its oracle **once**, in a ` ```verify ` fence; the harness contract is derived from it. A bead with no oracle **fails closed** (never invents a passing check). |
| 5 | `spec_id_preflight.py` | Create-time validation isn't enough — specs get edited. Preflight re-checks every bead's anchor and flags orphans when a heading is renamed. |
| 6 | `bd jira sync` / `bd jira push` (native) | The `spec_id` is a **first-class bead field**, so the OpenSpec link travels with the bead into Jira. Sync is bidirectional. |

## Going live with the Jira leg

`bd jira` is native — no custom bridge. A dry-run still calls the Jira API for
project metadata, so it needs real credentials (the demo does **not** fake a
response when none are set):

```bash
bd config set jira.url       "https://you.atlassian.net"
bd config set jira.project   "PROJ"
bd config set jira.api_token "<api-token>"        # or: export JIRA_API_TOKEN
bd config set jira.username  "you@company.com"    # Jira Cloud

bd jira push <bead-id> --dry-run   # preview the projection (real API, no write)
bd jira sync --push --create-only  # push new beads to Jira
bd jira sync --pull                # import Jira issues as beads
bd jira sync                       # bidirectional (newest-wins; --prefer-local/-jira)
bd jira status                     # sync status
```

When credentials are present, `demo.sh` ACT 6 automatically runs the real
`bd jira push --dry-run` instead of printing the command surface.

## Provenance notes (so you can trust the demo on stage)

- **Verified live:** the OpenSpec spec, the `--spec-id` field, both gates
  (`spec_id_enforcement`, `spec_id_preflight`), and contract derivation were all
  exercised against the real tools while building this. The `--check` run is the
  evidence.
- **Two real bugs were found and fixed while building this demo** (the demo was
  the forcing function):
  1. `spec_id_enforcement` crashed on `bd show --json`'s list shape →
     mol-feature detection failed **open** (gate silently not firing).
  2. The invalid-spec-id deny branch raised `NameError` (f-string vs `.format`)
     → the value-check failed **open**. Both now have regression tests.
- **Not yet verified — needs a live push:** *which* Jira field carries the
  `spec_id` (custom field vs description). Confirm with a real
  `bd jira push --dry-run` against your instance before claiming a specific
  field mapping on stage.
