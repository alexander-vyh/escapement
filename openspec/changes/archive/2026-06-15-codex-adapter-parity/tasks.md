## 1. Surface Manifest

- [x] 1.1 Add host-neutral onboarding fragments and manifest
- [x] 1.2 Add renderer/checker for generated agent surfaces
- [x] 1.3 Render `AGENTS.md`, `CLAUDE.md`, and `.codex/hooks.json`

## 2. Codex Surfaces

- [x] 2.1 Preserve repo-owned `.agents/skills/*` Codex skill surfaces
- [x] 2.2 Remove unavailable task/user-question tool references from Codex skills
- [x] 2.3 Add fixture-backed Codex `test_oracle_brief_gate` hook wiring

## 3. Verification

- [x] 3.1 Add generated-surface and static-safety tests
- [x] 3.2 Add negative control for ready Codex hook without fixture coverage
- [x] 3.3 Run targeted and full verification
