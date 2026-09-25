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

- all 180 case observations;
- a complete 3×3 `allow`/`ask`/`deny` matrix per gate and host;
- a binary confusion matrix with precision and recall per gate and host;
- false-positive and false-negative classes; and
- available repair cost while preserving explicit missing-evidence reasons.

The command exits nonzero for an invalid corpus, changed labels, a hook failure,
or any exact expected/observed mismatch. Run the focused mutation controls with:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q tests/test_gate_decision_replay.py
```

The corpus has no Codex `tdd_gate` cell: its recorded rows are Write/Edit
payloads, while Codex runs the gate on `apply_patch` (behavior covered by
`claude/hooks/tests/test_codex_patch_gates.py`). The labeled population is 36
cases in each of five cells: Claude TDD, Claude and Codex Test Oracle Brief, and
Claude and Codex Outcome Assertion.
