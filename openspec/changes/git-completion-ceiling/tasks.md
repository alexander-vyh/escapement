## 1. Walking skeleton — local push-cap (escapement)

- [ ] 1.1 Define `.claude/repo-policy.json` shape (`{"git_completion_ceiling": "local|pr|merge"}`) and implement `resolve_ceiling(cwd)` in escapement: walk up to git root, read the file, return the tier; default `pr` when file/field absent; fail safe to `pr` on malformed config with a gate signal (spec: per-repo-ceiling-resolution)
- [ ] 1.2 Add the PreToolUse hard cap on the `git push` path — deny when ceiling is `local`, with a message naming the ceiling + `--ceiling-waiver "<reason>"` escape, and emit `_gate_signal.record(gate="git-completion-ceiling", ...)`; allow for `pr`/`merge`/unconfigured; reuse `validate_no_shirking.py`'s PreToolUse surface if clean, else a sibling hook; wire into `claude/settings.template.json` (spec: hard-push-cap-for-the-local-tier)
- [ ] 1.3 Implement the `--ceiling-waiver` escape with value-not-presence validation — accept a substantive reason (record it as a labeled signal), reject empty / under-threshold / placeholder reasons (spec: waiver-escape-with-substantive-reason)

## 2. Behavioral test — the oracle (escapement)

- [ ] 2.1 Test: in a `local` fixture repo, an agent `git push` is denied by the gate (spec: hard-push-cap-for-the-local-tier)
- [ ] 2.2 Negative control: an unconfigured fixture repo allows `git push`; positive control: a `merge` fixture repo allows `git push` (spec: per-repo-ceiling-resolution, hard-push-cap-for-the-local-tier)
- [ ] 2.3 Test: a human (`!`-style, non-tool-call) push is not blocked (spec: hard-push-cap-for-the-local-tier)
- [ ] 2.4 Floor-coherence test: in a `local` fixture, a turn ending after a commit with no push and no shirking language is allowed to Stop (spec: floor-coherence-with-the-ceiling)
- [ ] 2.5 Waiver test: a valid `--ceiling-waiver "<reason>"` permits the push; a placeholder reason (`tbd` / `n/a` / echo-of-ceiling) still denies (spec: waiver-escape-with-substantive-reason)

## 3. Proof of delivery — live observation (escapement)

- [ ] 3.1 In a real repo set to `git_completion_ceiling: local`, run a live agent session: confirm `git push` is denied with the actionable message + waiver path, and that the session can stop after committing without a shirking-block (spec: hard-push-cap-for-the-local-tier, floor-coherence-with-the-ceiling)
