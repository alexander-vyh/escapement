# Claude Code Adapter Notes

Claude Code uses `CLAUDE.md`, `claude/settings.template.json`, Claude skills,
rules, hooks, commands, and agents. Existing `claude/*` implementation paths are
kept in this increment; the neutral manifest names their host support status so
path names stop acting as the source of truth.

Claude Code has richer hook coverage today than Codex. New shared workflow
behavior should be added through the manifest first, then rendered or translated
to the host-specific surface that can actually enforce it.
