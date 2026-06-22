<!-- Spec: git-completion-ceiling -->

## Purpose

A per-repo "git completion ceiling" declares how far an agent may take work — local
commit only, push + open PR, or push + merge — and the escapement PreToolUse gates
enforce it as a hard cap. The skeleton covers the `local` push-cap and the resolver.

## Requirements

### Requirement: Per-repo ceiling resolution

The system SHALL resolve a single ceiling value for the repo containing the agent's
working directory, from a versioned per-repo config file, defaulting to the permissive
`pr` tier when no configuration is present.

#### Scenario: ceiling read from repo config

- **WHEN** the resolver runs in a directory whose enclosing git repo contains
  `.claude/repo-policy.json` with `{"git_completion_ceiling": "local"}`
- **THEN** it returns `local`, resolved by walking up from the working directory to the
  git root

#### Scenario: unconfigured repo defaults to pr

- **WHEN** the resolver runs in a git repo with no `.claude/repo-policy.json`, or the
  file is present but lacks the `git_completion_ceiling` field
- **THEN** it returns `pr` (the permissive default), and no push is blocked on account
  of the missing config

#### Scenario: malformed config fails safe to default

- **WHEN** `.claude/repo-policy.json` is present but unparseable or holds a value
  outside `{local, pr, merge}`
- **THEN** the resolver returns `pr` and records a gate signal noting the malformed
  config, rather than blocking work on a config error

### Requirement: Hard push-cap for the local tier

The system SHALL block an agent's `git push` via a PreToolUse denial when the resolved
ceiling is `local`, and SHALL allow `git push` for the `pr`, `merge`, and unconfigured
cases.

#### Scenario: push denied in a local repo

- **WHEN** an agent issues `git push` (any form) in a repo whose ceiling is `local`
- **THEN** the PreToolUse gate denies the call with a message that names the ceiling,
  states the repo's limit, and includes the `--ceiling-waiver "<reason>"` escape, and
  emits a `_gate_signal.record(gate="git-completion-ceiling", ...)` entry

#### Scenario: push allowed at or below the ceiling

- **WHEN** an agent issues `git push` in a repo whose ceiling is `pr` or `merge`, or in
  a repo with no ceiling configured
- **THEN** the gate allows the call (negative control: absence of config must never
  block a push)

#### Scenario: human push is never blocked

- **WHEN** the user runs `git push` themselves (e.g. via the `!` shell escape), not as
  an agent tool-call
- **THEN** the gate does not block it — enforcement governs agent tool-calls only

### Requirement: Waiver escape with substantive reason

The system SHALL allow a blocked push to proceed when accompanied by a
`--ceiling-waiver "<reason>"` whose reason clears a substance bar, and SHALL reject
placeholder reasons.

#### Scenario: valid waiver permits the push

- **WHEN** the agent re-issues the blocked action with `--ceiling-waiver "<a concrete,
  non-placeholder reason>"`
- **THEN** the gate allows the action and records the waiver (gate, repo, ceiling,
  reason) as a labeled signal for half-life review

#### Scenario: placeholder waiver is rejected

- **WHEN** the waiver reason is empty, under the substance threshold, or a placeholder
  (`tbd`, `n/a`, or text that merely echoes the ceiling)
- **THEN** the gate still denies the action (value-not-presence validation)

### Requirement: Floor coherence with the ceiling

The system SHALL NOT punish an agent for stopping at the repo's ceiling — stopping after
a commit in a `local` repo is a sanctioned outcome, not shirking.

#### Scenario: stop-at-commit permitted in a local repo

- **WHEN** an agent in a `local` repo commits its work and ends the turn without pushing
  and without using shirking language
- **THEN** the Stop is permitted — the ceiling is the completion target, so reaching it
  is "done," not an early stop
