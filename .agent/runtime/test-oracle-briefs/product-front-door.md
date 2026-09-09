# Test Oracle Brief: Escapement Product Front Door

## Business invariant

An advanced individual operator arriving at the repository can quickly answer four questions before installing anything: what Escapement is, what outcome it promises, how the existing delivery loop behaves, and what the current adapters do not enforce. The product story must connect that loop to inspectable real evidence rather than presenting architecture or aspirational claims as proof.

## Independent source of truth

The approved product framing is the category “The control system for agentic delivery” and promise “Delegate outcomes. Get verified delivery.” The repository's actual merged pull requests and their checks are the source for proof stories. Test-owned evidence records bind each public summary to the facts checked against those live records; the product pages do not certify themselves. `agent-surfaces/manifest.json` is the source for current support statuses and reasons. The user-visible oracle is the linked content and ordering rendered on the default-branch GitHub README plus the product interface generated from canonical identity into the installed plugin manifest.

## Solution constraints

- Preserve the existing mission, capability chain, adapters, and technical engine.
- Keep `agent-surfaces/identity.json` authoritative for generated plugin positioning, capabilities, keywords, and starter prompts; do not edit generated manifests by hand.
- Label the synthetic tour as representative, not a captured transcript, benchmark, or guarantee.
- Use direct merged-PR links for real evidence and include counterevidence or remaining limitations where the incident requires it.
- Put the tour, evidence, audience, and truthful limitations before deep architecture or installation detail.
- Add no dashboard, wizard, hosted service, telemetry, alternate engine, or new runtime dependency.

## Invalid solution classes

- A hero-only copy edit that leaves no concrete tour, proof, audience, or decision path.
- A polished walkthrough presented as a real run without inspectable evidence.
- Claims that the merge hook observes green status, confirmation classes are enforced, deployment metadata executes deployment, or Codex can schedule/re-enter ended sessions.
- Duplicated product positioning hand-edited into generated plugin manifests.
- Architecture-first documentation that makes the reader reconstruct the product from internal components.

## Fragile implementation to reject

Replace the first paragraph with the approved slogan while leaving the existing README order and content intact. It looks productized but still gives a visitor neither a two-minute loop nor evidence. The product-surface contract must fail this shortcut.

## Negative control

On a copied repository, remove the evidence link, move the install section ahead of truthful limits, replace a recorded outcome with fabricated autonomous-delivery copy, or insert the reviewer-demonstrated false merge, deployment, Codex continuation, or adapter-identity claims into either new product page. The static contract or mission-capability validator must fail and identify the affected public surface. The evidence contract binds each cited pull request to its exact test-owned observed result and counterevidence, so a set of valid links cannot decorate fabricated or reassigned claims.

## Positive control

The completed surface retains the exact approved category and promise, links both the tour and evidence before installation, exposes current limitations before installation, and keeps the canonical plugin description generated from `agent-surfaces/identity.json`.

## Missing and unresolved handling

Missing linked files, absent evidence, or unknown support behavior fails closed: the check fails or the prose labels the behavior unsupported/unverified. An unavailable external proof must not be replaced by an uncited number or stronger claim.

## Final outcome verification

Run:

```bash
python3 -m pytest tests/test_product_surface.py tests/test_mission_capability_contract.py tests/test_agent_surfaces.py -q
python3 tools/render_agent_surfaces.py --check
python3 -m pytest claude/hooks/tests harness/tests tests -q -rs
```

After merge, fetch the default-branch README and canonical plugin manifest through GitHub, verify the category, promise, tour/evidence links, and limitation ordering. Resolve every cited pull request through the GitHub API; require `MERGED` state, merge metadata, and live records consistent with the attached observed result and counterevidence. Then run both repository-declared plugin refresh scripts and verify the installed manifests contain the new short description.
