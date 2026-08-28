# PREP K9 glossary-assignment reconciliation evidence

## Disposition

```text
Goal:                         PREP_K9_GLOSSARY_ASSIGNMENT_RECONCILIATION_READY
Product:                      80618b6039bf994585a2a3ff623b44c1e16efeb5
Parent integrated Product:    71529ba69c2191884144e5f43ab5bc97720be4e9
Starting main/dev:            892239850fbdc447ad1b45df664ad7382b285385
Actual PREP/OPS access:       NOT EXECUTED
Migration source changes:     NONE
Quarantined feature changes:  NONE
```

This descendant changes only the K9 glossary metadata collector, its fixed DataHub query seam,
bounded tests, and the existing isolated K9/MCL recovery fixture. The MCL normalization correction
already present in Product `71529ba69c2191884144e5f43ab5bc97720be4e9` is unchanged. There is no
migration, environment, Compose, port, package-lock, Change Management, Admin, or feature-WIP
change.

## Frozen operator-provided Actual PREP evidence

The Control Plane did not access PREP. The operator reported that the complete glossary search
returned 1,570 entities across seven pages: 1,551 Terms and 19 Nodes, with no duplicate Term or
Node observations and a complete cursor. The first inspected Table assignment then failed with:

```text
product_error_code   K9_DATAHUB_SOURCE_FAILED
failure_stage        METADATA_COLLECTION
failure_detail_code  ASSIGNMENT_TERM_OUTSIDE_SNAPSHOT
declared Table assignments  574
observed Table assignments    1
Term outside snapshot         1
```

The collector incremented the observed count before its membership check, so the profile means
the first inspected Table-to-Term reference was absent from the completed search result. It does
not mean the provider contained only one assignment. Search-index absence had been treated as
canonical nonexistence; that was the exact incorrect assumption.

## Generic correction

After a complete glossary scroll, the collector now gathers sorted unique missing assignment Term
URNs and performs at most 1,000 exact `entity(urn)` lookups. The fixed DataHub v1.6.0 query selects
`urn`, `type`, `exists`, advisory `status.removed`, and exactly the same Term attributes,
assignment totals, parent edges, and outgoing-relationship first page used by the scroll path.

Acceptance requires the returned exact identity, `GLOSSARY_TERM` type, and `exists=true`.
`status.removed=true` is rejected when the provider exposes it; v1.6.0 permits a null status and
ordinary Glossary deletion hard-deletes the Term. A valid direct entity runs through the same Term
normalizer and complete relationship pagination as a scroll entity, is hydrated into the source
snapshot, deterministically merges sparse/rich assignment attributes, and preserves every
assignment edge. Exact duplicate assignments remain idempotent.

Exact lookup null, `exists=false`, removed state, or incompatible entity type fails closed as
`DANGLING_GLOSSARY_ASSIGNMENT`. Response-contract faults and GraphQL/transport/timeout/HTTP faults
retain the existing bounded provider classification. The old
`ASSIGNMENT_TERM_OUTSIDE_SNAPSHOT` value remains readable solely for descendant resume of the
retained Actual-PREP-style receipt; no new collection path emits it as a final diagnosis.

The additive sanitized assignment profile contains only counts:

```text
missing_term_reference_count
direct_term_resolution_attempt_count
direct_term_resolution_recovered_count
direct_term_resolution_dangling_count
table_missing_term_count
column_missing_term_count
source_consistency_conflict_count
```

It contains no URN, name, description, GraphQL body, provider exception, credential, or token.
Identity and shape failures retain only SHA-256 hashes and bounded page/ordinal values.

DataHub v1.6.0 does not expose one provider snapshot generation shared by inventory, search, and
exact entity reads. The Product therefore does not invent an atomic snapshot or infer a source
race from search absence. A mutation that produces a dangling exact lookup or later assignment
total mismatch remains fail-closed, and the whole source refresh can be retried without semantic
promotion or LKG destruction. In the verified fixtures no independently provable cross-read race
occurred, so `source_consistency_conflict_count=0`.

Primary contract references:

- [DataHub v1.6.0 GraphQL entity schema](https://github.com/datahub-project/datahub/blob/v1.6.0/datahub-graphql-core/src/main/resources/entity.graphql)
- [DataHub v1.6.0 entity existence resolver](https://github.com/datahub-project/datahub/blob/v1.6.0/datahub-graphql-core/src/main/java/com/linkedin/datahub/graphql/resolvers/entity/EntityExistsResolver.java)
- [DataHub v1.6.0 Glossary Term mapper](https://github.com/datahub-project/datahub/blob/v1.6.0/datahub-graphql-core/src/main/java/com/linkedin/datahub/graphql/types/glossary/mappers/GlossaryTermMapper.java)
- [DataHub v1.6.0 Glossary deletion resolver](https://github.com/datahub-project/datahub/blob/v1.6.0/datahub-graphql-core/src/main/java/com/linkedin/datahub/graphql/resolvers/glossary/DeleteGlossaryEntityResolver.java)

## Bounded fixture results

| Fixture | Result | Recovered | Dangling |
|---|---|---:|---:|
| Term present in complete scroll | PASS; no direct lookup | 0 | 0 |
| Search omission, direct active Term | PASS; hydrate and preserve assignment | 1 | 0 |
| Sparse/rich assignment observations in either order | PASS; byte-equivalent deterministic output | 1 | 0 |
| Direct null or removed Term | fail closed: `DANGLING_GLOSSARY_ASSIGNMENT` | 0 | 1 each |
| Direct incompatible entity type | fail closed: `DANGLING_GLOSSARY_ASSIGNMENT` | 0 | 1 |
| Direct provider failures | original transport/timeout/HTTP 4xx/HTTP 5xx/GraphQL/contract family preserved | 0 | 0 |
| More than 1,000 unique missing Terms | fail closed before direct provider fanout | 0 | 0 |

The metadata/source suite is 26/26 PASS. The integrated K9 managed-graph, scheduler, state,
server, MCL capture/discovery/checkpoint, and PREP smoke selection is 181/181 PASS. ESLint,
TypeScript typecheck, application build, POC build, static/source integrity, accepted migration
checksums, and `git diff --check` pass. The only build advisory is the pre-existing Vite chunk-size
warning.

## Exact Actual-PREP-style descendant resume

The isolated provider exposes one current Table assigned to a valid Glossary Term while the
complete glossary scroll returns zero search entities. No PREP business content is in the fixture.

1. Exact parent Product `71529ba69c2191884144e5f43ab5bc97720be4e9` passes health, login, and
   bounded DataHub read, then fails K9 with
   `METADATA_COLLECTION / ASSIGNMENT_TERM_OUTSIDE_SNAPSHOT`; the attempt is `SMOKE_FAILED`.
2. Exact descendant Product `80618b6039bf994585a2a3ff623b44c1e16efeb5` uses the same project,
   named volumes, runtime secrets, and deploy flow.
3. The direct resolver performs one attempt, recovers one Term, hydrates it, reconciles declared
   and observed Table assignment totals as 1/1, and records zero dangling references.
4. Smoke passes in exact order: health, administrator login, DataHub bounded read, both managed
   K9 graphs plus semantic index, MCL checkpoint contract, and GENERAL provider/route.
5. Final attempt phase is `ACCEPTED` with the parent Product recorded as the resume source.

The retained MCL checkpoint boundary remains `before=7`, repeated initialization `=7`, and
read-back `after=7`. Runtime secrets are byte-identical. There is one administrator, one K9
identity, one MCP identity, and no reset, resecret, volume deletion, duplicate identity, LKG loss,
or semantic promotion before all source stages succeed. Port 39080 is unchanged. Disposable
residue is exactly:

```text
containers 0
volumes    0
networks   0
```

## Exact OCI

```text
Image ID     sha256:5f4ef8dff5c270c03b2d12a64698d8dc11c6ac9ae6d334165202c1b59507bbaa
Platform     linux/amd64
Revision     80618b6039bf994585a2a3ff623b44c1e16efeb5
Runtime user node
```

The networkless read-only image hashes of `poc-k9-metadata-collection.mjs` and `poc-server.mjs`
match the exact Product Git contents. Final release source-check records
`runtime_input_diff=NONE` after the Evidence and Handoff checkpoints.

## Operator boundary

`origin/main` stays frozen pending explicit user approval. After the verified Handoff is promoted,
the PREP operator uses the unchanged path:

```bash
git fetch origin
git switch main
git pull --ff-only origin main
./scripts/prep39083 deploy
```

Actual PREP and Actual OPS were not executed by the Control Plane.
