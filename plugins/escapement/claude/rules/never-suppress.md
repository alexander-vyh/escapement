# Never Suppress — Global Rule

When something fails, fix why it fails. Never make the failure invisible.

This applies to every form of suppression:
- Skip lists, exclusion lists, deny lists
- `# noqa`, `# type: ignore`, `# nosec`, `# pylint: disable`
- Downgrading errors to warnings
- `except: pass` or `except SomeError: pass` without handling
- `@pytest.mark.skip` / `xfail` without a linked fix
- `--no-verify`, `SKIP=` in pre-commit
- Retry-and-swallow (catch, log, continue without fixing)

Every suppression is a bug disguised as configuration. Fix the bug.

## Never Downgrade the Oracle

Do not make a test easier to pass by weakening what it proves.

Forbidden oracle downgrades:
- Changing a business-outcome assertion into an implementation-detail assertion
- Replacing semantic identity with generated IDs
- Removing a negative control
- Changing fail-closed behavior to silently ignore unresolved data
- Testing an upstream/intermediate artifact instead of the final user-facing output
- Asserting that code executed rather than that the outcome happened
- Deleting or loosening a regression test without replacing it with an equal or
  stronger oracle

If a test fails, fix the implementation or revisit the spec. Do not weaken the
test unless the Test Oracle Brief is updated and reviewed.
