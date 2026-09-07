# Problem Framing — codex-stop-gate

Confirmed by user 2026-07-07 (interactive session; scope confirmed via explicit
choice "Walking skeleton first", framing confirmed "Confirmed as stated").

## Problem

Codex sessions wind down after declaring "done" with no mechanical check: no
outcome verification, residue narrated instead of resolved. Real incident
2026-07-07: Codex merged simplifi/cro-reporting PR #329, declared "Shipped",
stopped on a deleted-upstream branch with unshipped residue and no post-merge
verification. Escapement's continuation-harness Stop gate exists but is
Claude-only; the Codex adapter's only countermeasure is compliance prose
(`codex_final_response_gap.py` SessionStart notice).

## Why Now

The incident above, plus the blocking premise is stale:
`agent-surfaces/manifest.json` marks `stop_hook`/`validate_no_shirking`
codex-unsupported with reason "Codex has no Stop lifecycle event", but Codex
hooks went GA (~v0.124.0, 2026-04-23 [per changelog summary, not independently
verified]) with a Stop event whose blocking semantics force an automatic
continuation prompt. The fix has been possible for ~2.5 months.

## Decision Authority

Alexander (solo workflow-tooling repo).

## Behavioral Population

Codex agent sessions across all of the user's repos, via the user-level
`~/.codex` hooks layer. The only human behavior change is a one-time
hook-trust approval (`/hooks` trust flow).

## Riskiest Assumption

Betting a user-layer `~/.codex` Stop hook actually blocks Codex wind-down and
forces a continuation prompt in a real session; wrong when the trust model or
payload/output semantics do not work as documented
(developers.openai.com/codex/hooks, fetched 2026-07-07); would know within
days via a live probe session in a scratch repo.

## Success Criteria

A Codex session that tries to stop without a green `verify` or an explicit
user release gets its final answer intercepted and is forced to continue with
a constructive resumption prompt — observed in a real Codex session, not only
a fixture.
