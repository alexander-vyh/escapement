---
description: "Run discovery to create a design doc with adversarial planning — problem, non-goals, riskiest assumption, walking skeleton"
argument-hint: "[--schema rapid|feature|epic] [edit <change-name>] <topic>"
---

Read and follow the full `discovery` skill: load its SKILL.md (listed under your available skills) with `read`. Follow its instructions exactly.

The user's arguments: `$ARGUMENTS`

Parse the arguments:
- `--schema rapid|feature|epic` selects ceremony level (default: `feature`)
- `edit {change-name}` enters Edit mode on an existing OpenSpec change
- Everything else is the topic name for Create mode

Examples:
- `/discovery dark-mode` → Create mode, feature schema, topic "dark-mode"
- `/discovery --schema rapid fix-date-filter` → Create mode, rapid schema
- `/discovery --schema epic auth-redesign` → Create mode, epic schema
- `/discovery edit dark-mode` → Edit mode on existing change
