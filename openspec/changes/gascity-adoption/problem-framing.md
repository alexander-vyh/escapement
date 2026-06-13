# Problem Framing — gascity Adoption

Confirmed inputs to discovery. Source: the user, confirmed inline this session (2026-06-05)
after a multi-step evaluation + live trial of gascity on this machine. This framing restates
the user's confirmed answers — it is not a fresh inference.

## Problem

The user runs ~6 concurrent agent sessions (Claude + Codex) and coordinates them **by hand** —
launching each, tracking which session owns which work, routing tasks, and remembering what is
in flight where. There is no orchestration layer managing session spawn/sleep, work routing, or
cross-session coordination. The coordination is manual, stateful, and lives in the user's head.

## Why now

The concurrent-session load already makes hand-coordination a real, recurring tax (it happens
every working session, not hypothetically). And gascity is now de-risked: this session's
evaluation + live trial confirmed it runs non-swarm-by-default (0 agents at rest, demand-driven
spawn, `min_active_sessions=0`), supports `gc rig add --adopt` for repos that already have beads,
serves a native Anthropic endpoint, and clears this machine's tool/version floors (dolt 2.1.2,
bd 1.0.4). The blocker that remained (local-model agentic throughput) was characterized and
ruled out of scope — orchestration runs cloud sessions, not local-model agentic work. So the
"should we" is settled; the open work is "how to adopt it for real."

## Decision authority

`none — solo personal workflow owned by the user.` This is the user's own machine and working
setup. No external stakeholder sign-off is required.

## Behavioral population

`none — only the user's own workflow changes.` No one else has to adopt anything, learn anything,
or change how they work. gascity orchestrates the user's own agent sessions.

## Riskiest Assumption

Betting that **routing most of the user's work through gascity removes more hand-coordination toil
than the operational complexity it adds (a standing supervisor daemon + cities/rigs/packs to learn
and maintain), AND that demand-driven spawning keeps token cost bounded in real use — not just at
rest.** Wrong when: the user spends more time managing gascity (debugging the supervisor, fixing
rig/routing config, babysitting sessions) than the hand-coordination it replaced; OR token spend
climbs because sessions spawn more freely than expected under real load. Liveness: the user would
know within ~2 weeks of running real work through it — coordination-toil and token-spend are both
felt within days of daily use.

## Success criteria

The user's real projects run as gascity rigs; session spawn/sleep is demand-driven (the user stops
manually launching and tracking sessions); coordination of concurrent work moves out of the user's
head and into gascity; and token spend stays in the same range as today (agentic coding still on
cloud models; demand-driven spawn does not balloon session count). The local-vs-cloud provider
split per role is explicitly a *future increment* the user will iterate on — not part of the
initial success bar.
