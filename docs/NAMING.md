# Naming

## Escapement

`Escapement` is named for the clock mechanism that turns stored energy into measured motion. It restrains runaway movement, gives the oscillator enough impulse to continue, and advances the train one tick at a time.

That model fits this repo better than the earlier descriptive name, `claude-workflow-setup`, because the repo is not tied to a single agent host. Claude Code and Codex are supported adapters over the same base workflow model, with host-specific enforcement surfaces where their capabilities differ.

The repo's core job is to convert model effort into controlled, outcome-verified progress:

- OpenSpec preserves intent and behavioral requirements.
- Beads carries task state and dependency structure.
- Named agents divide work and keep independent review lanes.
- Test-oracle briefs define what correctness means before implementation.
- Hooks and deterministic gates prevent premature stopping and invalid workflow shortcuts.
- Verification and wakeups make completion or resumption explicit.

This is the clockwork sense of an escapement: not a lock, not a judge, and not a passive reference mark. It is the mechanism that meters motion, injects continuation energy, and keeps the train from running free.
