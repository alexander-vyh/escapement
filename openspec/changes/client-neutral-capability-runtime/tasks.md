## 1. Neutral contract and adapter registry

- [ ] 1.1 Define the normalized lifecycle event and structured decision schema, including identity, provenance, correlation, state transition, action, and enforcement level; add incomplete-input negative controls (spec: Normalize lifecycle identity and provenance; Return structured capability decisions)
- [ ] 1.2 Define capability and adapter registration records for Pi, Codex, and Claude, including installed-version evidence and hard/advisory/unavailable realization; reject host-derived source authority and unproven hard claims (spec: Capabilities have neutral identity and evidence; Adapter realization is explicit)

## 2. Cross-client neutral runtime slice

- [ ] 2.1 Implement one outcome/oracle continuation capability in the neutral runtime and thin Pi, Codex, and Claude event adapters; verify equivalent semantic decisions without adapter-owned policy (spec: Adapters do not own neutral policy; Immediate decisions are applied inline)

## 3. Lifecycle bridge and independent proof

- [ ] 3.1 Implement durable pending-action persistence and adapter-mediated resume/advisory handling; verify ordinary immediate tool decisions do not start the supervisor (spec: Persist runtime-issued pending actions; Resume only through registered adapters)
- [ ] 3.2 Build independent Pi, Codex, and Claude fixtures plus positive and negative controls for the continuation/oracle slice; readiness MUST depend on native/user-visible evidence rather than adapter self-report (spec: Readiness requires independent installed-client evidence; Negative controls reject false equivalence)
