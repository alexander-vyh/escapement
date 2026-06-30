# Claude Eval Profile

Portable Claude Code profile for evaluating Escapement's workflow gates in
benchmarks and scratch repositories.

This is not a copy of a user's live Claude config. It has two installable modes:

- `gates`: hook/rule/skill profile for public bugfix benchmarks such as
  SWE-bench, where extra `.beads` or `openspec` files would pollute the patch.
- `workflow`: full Escapement workflow profile for custom eval repos that
  intentionally include Beads/OpenSpec state.

The gates profile packages:

- oracle-brief enforcement before code edits
- TDD and implementation-echo guards
- oracle-downgrade and outcome-verification guards
- Serena/context-use nudges
- post-edit test reminders
- stop-time no-shirking and continuation checks

The profile excludes authentication, provider selection, personal permissions,
and machine-specific paths. Supply Claude authentication through the benchmark
runner or through the surrounding environment.

## Install Into A Scratch Claude Home

Use an empty scratch target whenever possible.

```bash
cd /path/to/escapement
profiles/claude-eval/install.sh --target /tmp/claude-eval/.claude --mode copy
```

For local development, symlink mode keeps the profile pointed at this checkout:

```bash
profiles/claude-eval/install.sh --target /tmp/claude-eval/.claude --mode symlink
```

Install the workflow profile when the eval task is designed to exercise
Beads/OpenSpec behavior:

```bash
profiles/claude-eval/install.sh \
  --profile workflow \
  --target /tmp/claude-eval/.claude \
  --beads-target /tmp/claude-eval/.beads \
  --mode copy
```

Validate the profile and any installed target:

```bash
python3 profiles/claude-eval/doctor.py
python3 profiles/claude-eval/doctor.py --target /tmp/claude-eval/.claude
python3 profiles/claude-eval/doctor.py \
  --profile workflow \
  --target /tmp/claude-eval/.claude \
  --beads-target /tmp/claude-eval/.beads
```

## Benchmark Use

Use this profile as the configured side of a paired run:

- baseline: Claude Code with `--safe-mode`
- configured: Claude Code using this installed profile

The benchmark oracle must remain independent of Claude's self-report. For
coding bugfixes, capture the resulting git diff and grade it with SWE-bench or
run the task's declared tests after the agent exits.

Use `--profile workflow` for custom workflow tasks whose independent oracle
expects Beads/OpenSpec behavior, for example:

- `bd ready` drives the next task choice
- `/discovery` creates OpenSpec artifacts
- `/work-breakdown` creates Beads tasks with spec links
- `bd close` is blocked when OpenSpec tasks are unreconciled
- active molecule status is visible at SessionStart

## Intentional Omissions

This eval profile does not install:

- `project-bootstrap.sh`
- machine-wide settings merge logic
- launchd files
- personal permissions
- provider/auth files

The workflow profile does install Beads formulas and `mol-status.sh`, but it
does not auto-run `openspec init` or `bd init`. Eval repos should explicitly
contain the Beads/OpenSpec state they are testing, so the benchmark can
attribute behavior to the workflow instead of hidden bootstrap side effects.
