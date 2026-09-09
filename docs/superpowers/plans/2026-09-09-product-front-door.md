# Escapement Product Front Door Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. This session is executing the bounded tasks directly, with independent mutation challenge and outcome verification.

**Goal:** Make the existing Escapement product legible and credible to an advanced individual operator without adding a new product or changing the workflow engine.

**Architecture:** Keep `agent-surfaces/identity.json` authoritative for package positioning. Use `README.md` as the decision-oriented front door, `docs/PRODUCT_TOUR.md` for a representative end-to-end walkthrough, and `docs/EVIDENCE.md` for incident-backed proof. Extend existing static contract tests to keep these public surfaces linked, ordered, and capability-honest.

**Tech stack:** Markdown, JSON canonical identity, generated plugin manifests, Python/pytest contract checks.

---

### Task 1: Define the public-surface oracle

- [x] Add the Test Oracle Brief for visitor comprehension, evidence, and truthful limits.
- [x] Add `tests/test_product_surface.py` with positive and negative controls.
- [x] Run the focused test and observe RED because the tour, evidence, and positioning do not yet exist.
- [x] Dispatch a mutation challenger and strengthen any surviving shortcut.

### Task 2: Ship the minimum coherent product surface

- [x] Update the canonical short description with the approved category and promise.
- [x] Reorder and tighten `README.md` around audience, loop, evidence, problem entrypoints, install, and limitations.
- [x] Add one clearly labeled representative product tour.
- [x] Add incident-backed evidence with direct links and explicit remaining limits.
- [x] Render generated host and plugin surfaces.

### Task 3: Verify and deliver

- [x] Run focused contracts, renderer drift checks, and the full test suite.
- [ ] Dispatch code review and independent outcome verification; resolve important findings.
- [ ] Commit, push, open a pull request, carry it through green merge, and refresh both installed plugins.
- [ ] Verify the default-branch public README and installed metadata, then close `escapement-56bb`.
