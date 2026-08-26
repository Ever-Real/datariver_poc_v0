# PREP Cross-release Owned Resume Evidence

Recorded at `2026-08-26T10:14:09Z` for Product
`749f568f4ea0dcddd3e837e76d83fe784985bb5b`.

## Root cause and correction

The V1 deployment receipt authenticated almost the complete generated runtime file. Its payload
excluded only four release identity keys, so tracked `FIXED` values such as
`POC_LLM_TIMEOUT_MS` were incorrectly part of target ownership. In addition,
`prepare_deployment()` reconciled and persisted the descendant release's `FIXED` values before
`deploy()` validated the old incomplete receipt. A legitimate descendant release therefore changed
the very payload later compared with the V1 fingerprint and was misclassified as operator drift.

V2 separates the two contracts:

- target ownership is an HMAC over only `POC_POSTGRES_PASSWORD`, `NEO4J_PASSWORD`, and
  `POC_MCP_SERVICE_TOKEN` under the versioned
  `DATARIVER_PREP39083_TARGET_OWNERSHIP_V2` contract;
- project, `linux/amd64`, port 39083, K9 mode, canonical volume identities, and Product/Handoff Git
  ancestry remain independent fail-closed checks;
- tracked `FIXED` values remain release configuration and do not enter the ownership hash.

The deploy order is now: read preserved runtime, inspect the receipt and volumes, prove ownership,
prove Product/Handoff ancestry, reconcile the descendant release, atomically persist the new
runtime, migrate the receipt to V2, and resume. Read-only operational commands no longer rewrite the
runtime file.

## Legacy and already-updated runtime compatibility

Only well-formed V1 and V2 receipts are accepted. For V1, the deployer reads the historical tracked
environment contract from the receipt's exact Handoff with `git show`, accepts only the bounded V3
or V4 schema, reconstructs the retired V1 fingerprint, and checks it with the preserved target
secrets. This also covers the observed PREP condition where a failed descendant deploy had already
written new `FIXED` values: historical `FIXED` values are reconstructed without rolling back or
printing the runtime file. After proof, the receipt is atomically rewritten as V2 and records the
source contract and prior Product.

Malformed receipts, changed generated secrets, noncanonical volumes, project/platform/port drift,
K9 ownership-mode drift, and invalid Product or Handoff ancestry all remain fail-closed as
`PREP_EXISTING_STATE_REQUIRES_OPERATOR_RECOVERY`.

## Runtime verification

An isolated full Docker regression used the exact Product image and exercised:

1. a historical tracked release whose fixed LLM timeout was 15 seconds;
2. PostgreSQL, Neo4j, Redis, canonical bootstrap identities, and a forced `SMOKE_FAILED` receipt;
3. a descendant release whose runtime file already contained the tracked 120-second value;
4. V1 ownership reconstruction and V2 migration;
5. same-command resume to `ACCEPTED`.

Result: `1/1 PASS` in `112.39s`. Generated secrets and named volumes were reused; administrator,
user, and MCP identity counts did not increase; K9 and MCP identities remained distinct; no volume,
database, receipt, or runtime-secret deletion occurred. The separate exact-Product same-release
smoke-failure retry and the fresh/residual/running/stopped/ambiguous state matrix also passed.

The OCI is `linux/amd64`, carries revision
`749f568f4ea0dcddd3e837e76d83fe784985bb5b`, and has image ID
`sha256:b95c48ba161ced4def7d2c39ffbdb0fd2c1c4c01287c60e6dbab0dd90d9df9d1`.

## Source gates

- PREP ownership/handoff focused suite: `60/60 PASS`.
- Node Product server: `144/144 PASS`.
- UI: `90 files / 663 tests PASS`.
- ESLint, TypeScript, standard build, and POC build: `PASS`.
- Ruff lint/format and strict mypy over 588 source files: `PASS`.
- Static verification, shell/Python syntax, source diff, and changed-file secret scan: `PASS`.
- Full repository Python run: `3929 passed / 118 skipped / 55 failed`; all 55 failures are in
  unchanged legacy migration revision assertions, strict-schema test doubles, DEV-host secret-file
  fixtures, or unrelated environment templates. No PREP ownership test failed, and the complete
  changed deployment suite passed independently.
- Router/retrieval semantics changed: `NO`; Router 60 plus Boundary 8 was retained, not rerun.

## Deployment

The only PREP operator command remains:

```bash
./scripts/prep39083 deploy
```

The current owned PREP `SMOKE_FAILED` state is compatible with same-command descendant release
resume, including its already-updated tracked `FIXED` runtime values. No `.env.prep` edit or manual
cleanup is required.

Actual PREP deployment: **NOT EXECUTED by the DEV Agent**.

Actual OPS deployment: **NOT EXECUTED by the DEV Agent**.
