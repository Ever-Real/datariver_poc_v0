# PREP K9 metadata collection hotfix

Recorded on `2026-08-28` for Product
`9c960e28d10c5cd7fb748e745860d73c6ffeb2ae`.

- starting `origin/dev`: `c517ff9e8db2fe92c525398affa893733241c80f`
- frozen `origin/main`: `c517ff9e8db2fe92c525398affa893733241c80f`
- prior Product: `a5e88b5ec25faff6990ac88489a218d8f6198113`
- Migration source changes: none
- quarantined feature changes: none

The Control Plane did not access or execute Actual PREP or Actual OPS.

## Actual PREP evidence supplied to the Control Plane

The operator reported doctor `ALL READY`, DataHub `/config` HTTP 200, and smoke step 3/6 bounded
DataHub read `PASS`. Both canonical managed graphs were durably `FAILED` with:

```text
last_error_code=K9_DATAHUB_SOURCE_FAILED
failure_stage=METADATA_COLLECTION
failure_detail_code=INTERNAL_TRANSFORM
semantic_index_status=PENDING
```

The latest PostgreSQL K9 failure contained the same stage and detail. Provider connectivity and
authentication are therefore not the current blocker. Actual PREP verifies the earlier terminal
failure propagation and durable stage/detail work; semantic-index `PENDING` is downstream of the
failed source stage.

## Reproduced invariant and exact correction

DataHub v1.6.0 exposes both `Tag.name` and nullable `Tag.properties`. Its `TagMapper` maps the tag-key
into `Tag.name`, while the optional display name and description come from `Tag.properties`.
Consequently, the same exact seeded tag URN can legitimately appear through different projections
as both:

```text
Tag.name=datariver_classification_internal, Tag.properties=null
Tag.name=datariver_classification_internal, Tag.properties.name=CLASSIFICATION:INTERNAL
```

The former collector compared the fully rendered tag objects. It therefore classified this richer
observation of the same canonical URN as an identity conflict and then collapsed every plain local
invariant into `INTERNAL_TRANSFORM`. The v1.6.0 contract was checked against the upstream GraphQL
schema and mapper:

- https://github.com/datahub-project/datahub/blob/v1.6.0/datahub-graphql-core/src/main/resources/entity.graphql
- https://github.com/datahub-project/datahub/blob/v1.6.0/datahub-graphql-core/src/main/java/com/linkedin/datahub/graphql/types/tag/mappers/TagMapper.java

The correction preserves the exact canonical URN and records only the bounded internal name source
`PROPERTIES` or `LEGACY` through JSON, structured-clone, PostgreSQL, and Redis projection paths. A
deterministic canonical merge prefers `properties.name` over the tag-key name regardless of
observation order. The internal provenance is removed from graph, API, Tree, Chat, evidence, and
embedding outputs. Different non-empty names from the same source or conflicting non-empty
descriptions still fail closed as `TAG_IDENTITY_CONFLICT`.

All local metadata invariants now retain the public `K9_DATAHUB_SOURCE_FAILED` and
`METADATA_COLLECTION` stage while using one bounded detail token:

- `TAG_IDENTITY_CONFLICT`
- `GLOSSARY_RESPONSE_MALFORMED`
- `GLOSSARY_TOTAL_DRIFT`
- `GLOSSARY_CURSOR_STALLED`
- `GLOSSARY_RELATION_PAGE_INCOMPLETE`
- `GLOSSARY_RELATION_COUNT_MISMATCH`
- `METADATA_IDENTITY_CONFLICT`
- `GLOSSARY_ASSIGNMENT_COUNT_MISMATCH`
- `METADATA_NORMALIZATION_FAILED`

Malformed tag/glossary shapes, cursor stalls, early relationship termination, total/count drift,
duplicate identities, and assignment mismatch remain fail closed. No raw GraphQL response, URN,
description, provider body, credential, token, or exception text is persisted as a diagnostic.
Semantic-index promotion still begins only after every source stage succeeds, and an unsuccessful
collection does not change the promoted graph generation or last-known-good state.

## Changed Product scope

- `frontend/poc-k9-metadata-collection.mjs` and its focused tests
- K9 scheduler/contract, state-store, server, provider, and smoke adapters/tests needed to preserve
  and expose the bounded enum
- `deploy/poc/Dockerfile.example`, solely to copy the new runtime module explicitly

No migration, environment contract, Compose topology, deployer, release framework, feature WIP,
secret, checkpoint, graph generation, ledger, or operator command was changed.

## Source verification

- Expanded K9 metadata/source/managed/state/server/provider/smoke selection: `176/176 PASS`.
- Candidate-focused K9 selection: `86/86 PASS`.
- Provider contract regression: `24/24 PASS`.
- TypeScript typecheck: `PASS`.
- POC build and application build: `PASS`.
- ESLint: `PASS`.
- Static verification: `PASS`.
- Accepted migration checksum manifest: `2/2 PASS`; no broad migration review was repeated.
- `git diff --check`: `PASS`.

## Exact OCI and disposable descendant resume

The exact Product image is `linux/amd64`, has OCI revision
`9c960e28d10c5cd7fb748e745860d73c6ffeb2ae`, and image ID
`sha256:ed6fe1194e56388ed6fcf2299a2832e1d1fbeca12d250ae110ee18eca7322510`.
The runtime image imports the new K9 metadata module.

The unchanged official current-style `SMOKE_FAILED` descendant-resume fixture ran from prior
Handoff `c517ff9e8db2fe92c525398affa893733241c80f` to the exact Product:

- result: `1 passed in 134.79s`;
- first attempt state: current-style `SMOKE_FAILED`, with no accepted marker;
- resume: the same deploy flow advanced the exact descendant to `ACCEPTED`;
- generated ownership secrets were preserved and no resecret occurred;
- administrator and canonical service identities were not duplicated;
- port 39080 remained unchanged.

Two preliminary attempts were stopped before creating resources when Docker Compose 5.3.1 blocked
inside the configured credential helper. A later preparation attempt correctly failed closed on an
ARM64 parent-image rebuild when the isolated Docker config lacked buildx. Neither was counted as a
Product PASS. The final fixture used the same Docker daemon with an isolated credential-free config,
the installed Compose/buildx plugins, and exact amd64 parent/Product images.

The fixture teardown was intercepted only to prohibit its test-only `down --volumes` call. Compose
performed a plain `down`; the three exact disposable volumes were then removed individually by
name. Zero resources for the fixture project remain. No `docker compose down -v` or
`down --volumes` command was executed. No Actual PREP volume, secret, receipt, accepted marker,
administrator, K9/MCP identity, graph generation, ledger, or checkpoint was accessed or changed.

Runtime contract inputs other than the explicit Dockerfile runtime-module copy are unchanged. The
release source check records the final `runtime_input_diff` after the Evidence checkpoint.

The operator command remains:

```bash
./scripts/prep39083 deploy
```

Actual PREP: **NOT EXECUTED BY CONTROL PLANE**.

Actual OPS: **NOT EXECUTED**.
