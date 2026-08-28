# PREP K9 DataHub source diagnostic hotfix

Recorded on `2026-08-28` for Product
`a5e88b5ec25faff6990ac88489a218d8f6198113`.

- starting `origin/dev`: `aa8cf75fc96b7c2f1cdb2d679e8c815ea72b5977`
- frozen `origin/main`: `aa8cf75fc96b7c2f1cdb2d679e8c815ea72b5977`
- prior Product: `b0402d142cc3920cbe936e7b19d1426009b0cdf1`
- Migration source changes: none
- quarantined feature changes: none

The Control Plane did not access or execute Actual PREP or Actual OPS.

## Actual PREP evidence supplied to the Control Plane

The operator reported doctor `ALL READY`, DataHub `/config` HTTP 200, and smoke step 3/6 bounded
DataHub read `PASS`. Smoke step 4/6 failed at `K9_INITIAL_REFRESH` as
`PREP_SMOKE_K9_DATAHUB_SOURCE_FAILED`. Default Lineage and Metadata Master were both durably
`FAILED` with `last_error_code=K9_DATAHUB_SOURCE_FAILED`; both reported
`semantic_index_status=PENDING`.

This closes the earlier failure-propagation defect in Actual PREP. The Product no longer leaves the
graphs indefinitely `PENDING`, and smoke no longer waits for its generic timeout.

## Root cause and bounded correction

`createPocK9RefreshTask` used the same `K9_DATAHUB_SOURCE_FAILED` catch for five distinct operations
and discarded the original provider family and substage:

1. `INVENTORY`
2. `INVENTORY_PROJECTION`
3. `LINEAGE_COLLECTION`
4. `METADATA_COLLECTION`
5. `RUNTIME_IDENTITY`

The exact historical provider substage cannot be recovered from the already-discarded Actual PREP
evidence, so this release does not invent one. The startup ordering issue is source- and
fixture-reproducible: the server launches an asynchronous Catalog warm-up immediately before it
starts K9; K9 may reuse the same in-flight initial Catalog refresh. Previously, one transient
failure finalized the scheduled boundary, and the same process did not try that boundary again even
if later doctor or bounded reads passed. A `/config` HTTP 200 also does not prove the runtime identity
body contract or the lineage/glossary GraphQL reads.

The public failure remains `K9_DATAHUB_SOURCE_FAILED`. Durable graph failure rows, scheduler
`last_attempt`, the managed-assets read model, and smoke now carry only allowlisted
`failure_stage` and `failure_detail_code` tokens. The detail allowlist is `CONNECTIVITY`, `TIMEOUT`,
`HTTP_4XX`, `HTTP_5XX`, `GRAPHQL`, `CONTRACT`, `EMPTY_SOURCE`, and `INTERNAL_TRANSFORM`. Raw exception
text, provider bodies, credentials, tokens, and unrestricted URNs are never persisted or rendered.

Retry is deterministic and bounded to two total attempts with one 1,000 ms wait. Only
`CONNECTIVITY`, `TIMEOUT`, and `HTTP_5XX` retry. HTTP 4xx, GraphQL, contract, empty-source, and
internal-transform failures are terminal. A terminal failure keeps both canonical graphs `FAILED`
with the exact bounded diagnostic. A successful retry publishes both graphs. Semantic promotion is
started only after every source read succeeds, so a failed source read cannot promote a generation
that the managed-graph last-known-good release does not reference. Existing LKG/current promoted
generation remains unchanged.

No database migration or new deployment framework was added. The canonical command remains:

```bash
./scripts/prep39083 deploy
```

## Source verification

- K9 scheduler/source fixtures: `16/16 PASS`.
- Combined K9 managed graph, scheduler, state-store, and server selection: `92/92 PASS`.
- PREP smoke selection: `29/29 PASS`.
- POC build, TypeScript typecheck, application build, ESLint, and static verification: `PASS`.
- Static verification includes the accepted historical migration checksum/integrity gate; no
  historical migration was reopened or re-audited.
- Product diff is limited to nine K9/smoke source and focused-test files.
- Runtime contract inputs (`env-contract`, example environment, Compose, Dockerfile, deployer, and
  one-command wrapper) are unchanged; `runtime_input_diff=NONE`.

## Exact OCI and disposable resume gate

The exact Product image is `linux/amd64`, has OCI revision
`a5e88b5ec25faff6990ac88489a218d8f6198113`, and image ID
`sha256:8a23982c9897217b9dc2e86a64b112fa07f787fdfdc8090f515c148105a3cd22`.
The runtime image imports the corrected `createPocK9RefreshTask` implementation.

Early current-style `SMOKE_FAILED` descendant-resume attempts encountered intermittent Docker
Compose 5.3.1 client hangs during `build` or `up --wait`. They were not counted as PASS, and every
exact disposable resource was removed individually. After independent minimal Compose build and
health-wait probes passed and both descendant images were cache-warm, the unchanged official
fixture was rerun from a detached exact Product worktree:

- source transition: prior Handoff `aa8cf75fc96b7c2f1cdb2d679e8c815ea72b5977` to exact Product
  `a5e88b5ec25faff6990ac88489a218d8f6198113`;
- result: `1 passed in 155.82s`;
- first attempt state: current-style `SMOKE_FAILED` with no accepted marker;
- resumed state: `EXISTING_OWNED_INCOMPLETE` to `ACCEPTED` through the same deploy flow;
- generated ownership secrets were preserved; no resecret occurred;
- exactly one administrator remained, the three canonical users remained, and K9/MCP identities
  were not duplicated;
- port 39080 remained unchanged.

The fixture teardown was intercepted only to prohibit its test-only `down --volumes` call. Compose
performed a plain `down`, and the three exact disposable volumes were then removed individually by
name. Zero `datariver-prep39083-retry-*` fixture resources remain. No `docker compose down -v` or
`down --volumes` command was executed. No Actual PREP volume, secret, receipt, accepted marker,
administrator, K9/MCP identity, graph generation, ledger, or checkpoint was accessed or changed.

The DEV resume gate is PASS. The same-command Actual PREP rerun remains the operator-owned external
acceptance step. It will either succeed after the single bounded transient retry or expose the exact
durable stage/detail needed for the next bounded operator decision.

Actual PREP: **NOT EXECUTED BY CONTROL PLANE**.

Actual OPS: **NOT EXECUTED**.
