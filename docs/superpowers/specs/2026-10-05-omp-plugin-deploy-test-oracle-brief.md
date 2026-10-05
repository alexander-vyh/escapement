# OMP plugin deployment oracle

1. **Business invariant:** normal Escapement deployment refreshes the independently
   registered OMP plugin. Its loaded adapter permits virtual tool devices and
   continues to deny ordinary file writes in a managed primary checkout.
2. **Independent source of truth:** OMP's registered package manifest and installed
   `node_modules/escapement` tree, compared with the declared landing checkout;
   actual installed extension handlers exercised with captured OMP tool shapes.
3. **Constraints:** use supported `omp plugin upgrade escapement`; preserve the
   rolling dependency, enablement, selected features, settings and other plugins;
   keep existing Claude/Codex update behavior; use Bun for the installed TypeScript
   import; do not rewrite private OMP state or weaken checkout guards.
4. **Invalid solutions:** checking source instead of installed authority, accepting
   version text or command exit zero as freshness, skipping configured broken
   packages, copying the extension elsewhere to probe it, or pinning a release SHA.
5. **Fragile shortcut:** an exit-zero upgrade that leaves stale installed bytes.
   The no-op fixture must fail deployment and installed verification.
6. **Negative controls:** stale/missing installed files; failed upgrade; changed
   configuration; installed/source byte-identical mutants that map every file as
   virtual or map virtual URIs as files; ordinary managed-root write must deny.
7. **Positive controls:** all screenshot URI devices must allow; a linked-worktree
   file write must allow; two successive releases must advance installed bytes;
   unrelated plugin data and rolling dependency/configuration survive both.
8. **Missing data:** genuinely absent OMP reports an explicit skip. Present but
   unregistered, incomplete or unresolved OMP fails closed. No verifier success
   without complete installed package byte and runtime proof.
9. **Final verification:** run `scripts/deploy-plugins.sh` after merge, then run
   `python3 scripts/verify_omp_plugin.py --source .` against the actual OMP
   installation. Inspect installed URI allowance, real checkout denial and linked
   worktree allowance; a fresh process loads new bytes, while existing sessions
   need reload.

The behavioral suite is `tests/test_omp_plugin_update.py`. Its public updater
fixtures start with an independently seeded stale installation, stub only the
external package-manager transaction, and inspect final installed bytes and
registered handler behavior. A metadata/wrapper contract covers all three hosts
and failure propagation. Pre-implementation red: 18 failed on missing updater,
verifier/wrapper and the old declaration; the strengthened 20-case suite was also
independently run red by the mutation challenger. Diagnostics prevent missing-command
errors from satisfying the negative cases.
