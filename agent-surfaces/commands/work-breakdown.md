---
op: work-breakdown
slots:
  invoke:
    claude: "Read and follow the full skill file at `~/.claude/skills/work-breakdown/SKILL.md`. Follow its instructions exactly."
    pi: |-
      Read and follow the full `work-breakdown` skill: load its SKILL.md (listed under your available skills) with `read`. Follow its instructions exactly.

      The user's arguments: `$ARGUMENTS`
targets:
  claude: claude/commands/work-breakdown.md
  pi: plugins/escapement-pi/prompts/work-breakdown.md
frontmatter:
  claude:
    description: "Translate a design doc into a beads task graph with outcome-based acceptance criteria, failure modes, and ambiguity flags"
  pi:
    description: "Translate a design doc into a beads task graph with outcome-based acceptance criteria, failure modes, and ambiguity flags"
    argument-hint: "<design-doc-or-change-path>"
---

{{slot:invoke}}

The first argument is the path to the design doc (required). Example: `/work-breakdown docs/plans/2026-03-08-feature-design.md`
