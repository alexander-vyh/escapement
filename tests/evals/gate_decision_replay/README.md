# Gate-decision replay corpus

This directory holds 180 redacted gate events sampled from the repository's
append-only production signal log. Labels are stored separately and joined by
case ID. The reviewer receipt records the source revision, policy revision,
review method, and integrity hashes; it is provenance, not homegrown PKI.

Run the complete replay from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -B tests/evals/gate_decision_replay/replay.py \
  --result /private/tmp/gate-decision-replay.json
```

The command validates the corpus, creates disposable Git repositories, executes
the selected shipped Claude/Codex hook for every case, and writes:

- all 180 recorded cases, 65 observed and 115 skipped with a reason;
- the `allow`/`deny` matrix per gate and host over the observed cases, against
  labels that still carry the retired `ask` class as recorded history;
- a binary confusion matrix with precision and recall per gate and host;
- false-positive and false-negative classes; and
- available repair cost while preserving explicit missing-evidence reasons.

The command exits nonzero for an invalid corpus, changed labels, a hook failure,
or any exact expected/observed mismatch. Run the focused mutation controls with:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_gate_decision_replay.py
```

The corpus still holds all 180 recorded cases in five cells of 36 — nothing was
deleted and `reviewer-receipt.json` is unchanged — but only 65 of them are still
replayable. escapement-e9v.12 retired the `ask` decision class and deleted the
`tdd_gate` and `outcome_assertion_gate` hooks, so:

- **executed (65):** Test Oracle Brief, Claude (29) and Codex (36).
- **skipped, retired cell (108):** Claude TDD, plus Claude and Codex Outcome
  Assertion. The hooks no longer exist, so their recorded decisions cannot be
  reproduced.
- **skipped, retired decision class (7):** the Claude Test Oracle Brief
  `missing_brief_edit` cases, whose attested label is `ask`. The gate still
  ships and still denies at landing; its edit tier no longer asks.

Skipped cases are never relabeled or removed: an attested label that describes a
decision class the repo no longer has is unreplayable evidence, not wrong
evidence. The runner prints `executed` and `skipped` counts so a future silent
drop to zero executed cases is visible instead of looking green.
