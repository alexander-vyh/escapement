# Test Oracle Brief: escapement-kjwx shell writes reach TDD and oracle-brief gates

## Business invariant
A behaviour-bearing source file changed through the shell (heredoc, cat >, sed -i, a script) must be held to the same TDD and Test Oracle Brief requirement as one changed through Edit/Write/apply_patch; the user must see the agent told once, at the change.

## Independent source of truth
The working tree itself (git status: modified, staged, untracked files) observed after the Bash call, classified by the existing gates' own public classifiers; the hook JSON each host acts on is the observable signal.

## Solution constraints
Must check state not command text; must reuse tdd-gate and test_oracle_brief_policy classification; must stay per-file once-per-session; must not touch stop_hook.py or tdd-gate's ask/deny decision; landing gates remain unchanged.

## Invalid solution classes
Parsing the shell command for redirects is invalid; a wrong solution that fires on every Bash call is invalid; a solution that ignores untracked new files is invalid; bypass via a script that writes the file must not escape.

## Fragile implementation to reject
A regex only on `cat >` fails for python open().write and sed -i; a hardcoded special case for one payload shape fails on Codex and Pi; treating tests/ as behaviour-bearing for TDD is a shortcut that misfires.

## Negative control
A shell write of src/app.py with no test changes and without a brief must produce the TDD and brief feedback; a second unrelated Bash call must not repeat it (fail if it does).

## Positive control
A shell write to docs/README.md produces no output; a shell write with a test file already modified and a valid brief present passes with no feedback.

## Missing/unresolved handling
Missing git repo, missing cwd, or unreadable payload: allow silently (fail open, nothing to judge). Absent session id: report every time rather than suppress.

## Final outcome verification
Run the hook through the Claude command, the generated Codex hooks.json command, and the rendered Pi extension; inspect the JSON each host acts on and verify the message reaches the model.
