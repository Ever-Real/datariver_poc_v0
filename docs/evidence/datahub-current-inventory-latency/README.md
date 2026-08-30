# DataHub Current Inventory Latency Evidence

Date: 2026-08-30 KST
Product: `1adfe1ced2c9311bcbb880bfac400a1edf8d9178`
Starting TEST Handoff: `d101c43209ba97f9b9d8c88be9f1053d21c577d3`
Actual PREP: not executed
Actual OPS: not executed

## Bounded root cause and correction

PREP smoke stage 3 requests the exact current DataHub root inventory with `refresh=true`. The smoke
HTTP envelope is 300 seconds, while the server refresh continues under the server lifecycle signal.
Before this Product, a late retry waited for the active refresh and then unconditionally started a
second complete provider scroll. The TEST predecessor demonstrated this boundary: its first deploy
timed out the first 300-second client wait, then completed after a bounded retry; the same-command
warm rerun completed in 202 seconds.

This Product makes one bounded change: a late or concurrent force-current caller joins the active
inventory refresh and returns that exact generation's items. It does not start a second provider
scroll. If the shared refresh fails, every waiter receives the same typed terminal error and no
failed candidate is persisted or promoted.

The smoke timeout, overall retry budget, provider page timeout, inventory query and scope,
authorization, currentness filtering, reconciliation, K9 publication fence and LKG behavior are
unchanged. No provider metadata, user state, migration or release infrastructure changed.

## Verification

- pre-correction reproduction: two overlapping force-current requests caused two provider scrolls;
- concurrent success and shared typed-failure regressions: `2/2 PASS`;
- DataHub inventory-scale suite: `8/8 PASS`;
- provider and K9 contract integration: `47/47 PASS`;
- syntax, targeted ESLint and diff check: PASS;
- source diff: `frontend/poc-server.mjs` and its focused inventory-scale test only.

A broader catalog-performance run has an unchanged malformed-router fixture failure on the starting
Handoff. It is unrelated to this two-file correction and was not hidden or rewritten.

## Exact Product artifact

The clean Product was built once for `linux/amd64` and exported without rebuilding:

- image: `datariver-poc:1adfe1ced2c9311bcbb880bfac400a1edf8d9178`;
- OCI revision: `1adfe1ced2c9311bcbb880bfac400a1edf8d9178`;
- archive SHA-256: `fbdc40654edfc846ad4cfdc35d5ac47ac0bc608ae92e9cb6a3b04faa759c42d6`;
- child manifest: `sha256:2fc658e88bd9bac7a5962422ba89c27434ad41e29b8fa47145aad0a8011b8f3d`;
- config: `sha256:62adc2bcae3b3837e3c9aed7fba467ba503a8d59a9e4fd1dfbbceb8c4e5b6323`;
- platform: `linux/amd64`.

The archive is ignored and transported separately. TEST must verify checksum, manifest, config,
platform and revision before `docker load`, then use the canonical no-build deploy path.

## Runtime gate

Product `51734c788aaa0ce1cef8c49f3b78ae923fe600dc` remains the last TEST-accepted runtime until this
descendant completes accepted-state deploy, 6/6 smoke and same-command rerun. Existing volumes,
secrets, identities and user metadata must be preserved. Actual PREP and Actual OPS remain outside
this work.
