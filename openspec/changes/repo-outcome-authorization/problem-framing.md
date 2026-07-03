# Problem Framing — repo-outcome-authorization

## Problem

Coding agents stop at "PR opened" and ask "want me to merge it now, or would you
rather review the PR first?" on green PRs, instead of shipping the change live — even
though the ship-live rule says "PR opened" is not done. Observed recurring; most
recently `cro-executive-dashboard` PR #242 (auto-deploys to Cloud Run on merge), where
the agent asked despite a full green suite (36 files / 291 tests) and a passing build.

## Why Now

It keeps happening across sessions and directly wastes the user's time. This session
just *removed* the per-repo **ceiling** (PR #95) as contradicting ship-live; the
authorization side — a per-repo declaration that agents are *cleared* to drive to live
— was left unbuilt. The base Claude Code system prompt defers to "durable
authorization" for hard-to-reverse/outward-facing actions, but no such durable artifact
exists, so agents default to asking.

## Decision Authority

The user (alexander). Solo; personal workflow tooling.

## Behavioral Population

Coding agents (Claude Code / Codex sessions) operating in the user's repos. They must
read the per-repo declaration, treat it as the durable authorization the base prompt
requires, and merge green PRs without soliciting review.

## Riskiest Assumption

Betting that a committed per-repo file will actually change agent merge behavior and
override base-prompt confirm-first caution. Wrong when: an agent in a repo declaring
`merged-and-deployed` + `auto_merge_on_green` *still* asks "merge or review first?" on
a green PR. Would know within ~days, on the next green PR in a configured repo (or a
scripted harness replay).

## Success Criteria

In a repo whose declaration is `merged-and-deployed` + `auto_merge_on_green: true`, an
agent that reaches green verification merges the PR without asking; and the Stop gate
blocks a session that tries to end with an unmerged green PR in such a repo (parity
with the existing `git_work_remains` check).
