# Naming

## Escapement

`Escapement` is named for the clock mechanism that turns stored energy into measured motion. It restrains runaway movement, gives the oscillator enough impulse to continue, and advances the train one tick at a time.

That model fits this repo better than the earlier descriptive name, `claude-workflow-setup`, because the repo is not only a Claude Code setup. Claude Code is one adapter. Codex and other agent hosts should be able to use the same base workflow model with different enforcement surfaces.

The repo's core job is to convert model effort into controlled, outcome-verified progress:

- OpenSpec preserves intent and behavioral requirements.
- Beads carries task state and dependency structure.
- Named agents divide work and keep independent review lanes.
- Test-oracle briefs define what correctness means before implementation.
- Hooks and deterministic gates prevent premature stopping and invalid workflow shortcuts.
- Verification and wakeups make completion or resumption explicit.

This is the clockwork sense of an escapement: not a lock, not a judge, and not a passive reference mark. It is the mechanism that meters motion, injects continuation energy, and keeps the train from running free.

## Collision Notes

The name has public collisions, but the footprint is small enough to tolerate for this repo's current use:

- `fusupo/escapement`: a small Claude Code structured-workflow plugin. This is the closest collision.
- `fulcrologic/escapement`: a prototype statechart-driven autonomous coding agent.
- `jolsten/escapement`: a Python time-code encoder/decoder package on PyPI.

The collision argues against publishing a bare `escapement` package name where a registry namespace is flat, especially on PyPI. It does not outweigh the conceptual fit for the GitHub repo name. If this grows into separately distributed adapters, use qualified package names such as `escapement-claude` and `escapement-codex`.
