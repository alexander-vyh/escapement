# TDD Enforcement — Global Rule

## When TDD Applies

Before writing any implementation code in a repo that has a `tests/` directory
or test files at the project root (e.g., `test-*.js`):

1. Write the failing test FIRST
2. Run it — verify it fails for the right reason
3. Write minimal implementation to pass
4. Run it — verify it passes
5. Refactor if needed, keeping tests green

Never silently skip TDD in a test-capable repo. Either follow it or get explicit
permission to skip.

## Exemptions

- Test files themselves
- Config and docs (`.toml`, `.yaml`, `.json`, `.md`, etc.)
- Files in `scripts/`, `bin/`, `tools/`, `scratch/`, `spike/`
- Outside git repos
- User says "prototype", "spike", "throwaway", "one-off", "experiment"
- Bug fixes and chores in repos without test infrastructure
