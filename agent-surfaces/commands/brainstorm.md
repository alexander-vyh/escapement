---
op: brainstorm
slots:
  invoke:
    claude: "Read and follow the full skill file at `~/.claude/skills/brainstorming/SKILL.md`. Follow its instructions exactly."
    pi: |-
      Read and follow the full `brainstorming` skill: load its SKILL.md (listed under your available skills) with `read`. Follow its instructions exactly.

      The user's arguments: `$ARGUMENTS`
targets:
  claude: claude/commands/brainstorm.md
  pi: plugins/escapement-pi/prompts/brainstorm.md
frontmatter:
  claude:
    description: "Enhanced brainstorming — challenges whether work should be done, rotates creative lenses, routes to /discovery or writing-plans"
  pi:
    description: "Enhanced brainstorming — challenges whether work should be done, rotates creative lenses, routes to /discovery or writing-plans"
---

{{slot:invoke}}
