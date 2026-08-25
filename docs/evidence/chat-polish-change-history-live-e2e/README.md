# Chat polish and Change History live E2E evidence

This bundle closes the bounded Chat action-row refinement and verifies Change History through the
real DEV source database, official DataHub APIs/ingestion, DataHub MCL, the DataRiver canonical
ledger, exact Table-to-System authorization and the Change Management read model. It progresses
from Product `ed5d5a6e37d509ede85c3c3bd58f331fd8117306`, Evidence
`3d0ba51b5d0d758739c83e6acd4bbea666c2f8db` and Handoff
`8a7125ad46367f617e1194a9505ada1798a239ad`.

The final Product candidate is `a09cd4cb47db7bb31f608dfd94c61f34844d33af`. Its exact amd64
OCI was healthy on the existing DEV port `39083` and returned HTTP 200. Dashboard `39090` returned
HTTP 200. PREP and OPS were not executed.

## Chat action UI

The existing immutable-history Copy/Edit behavior is unchanged. Only the user-message action scope
was refined: `.chat-message-actions-user` is transparent, has no border/card/strip, sits two pixels
below the bubble and retains the existing button hover and accessible focus behavior. No global
Button style changed. Component tests assert the dedicated scope and the production bundles contain
the resulting Chat asset.

## Historical 73-event RCA

Before this E2E, the append-only canonical ledger still contained all **73** historical events:
**17 Schema** and **56 Metadata**. They came from two earlier DataHub 1.6 DEV capture identities,
not from a production detector or a UI fixture. Their entity names identify governed disposable,
MCL-validation and MCL-E2E runs, plus one existing seed asset.

The formerly active exact mappings were removed through the governed mapping workflow. Stored
reasons include `Remove PHASE 1C-4 runtime validation mapping` and
`Remove disposable DEV Registration runtime mapping.` Therefore the prior UI was populated while
those exact mappings and grants existed; it later truthfully became empty when the active mapping
count returned to zero. The events themselves were never deleted. No admin fallback or schema-scope
authority was introduced.

## Dedicated DEV E2E boundary

- Source: PostgreSQL 15 container `quant_db`.
- Dedicated schema: `datariver_change_e2e`.
- Dedicated Table: `datariver_change_e2e_table_a`.
- Official DataHub 1.6 ingestion recipe:
  `infra/datahub/recipes/change_history_e2e_postgres.yml`.
- Dataset URN:
  `urn:li:dataset:(urn:li:dataPlatform:postgres,datariver-change-e2e-dev.quant_db.datariver_change_e2e.datariver_change_e2e_table_a,DEV)`.
- MCL topic: `MetadataChangeLog_Versioned_v1`.
- New source identity:
  `9f26d351b6009dce2510e4d0f190e0295c0c06ff0a7db6840c30a0da3dc4caaa`.
- Exact capture boundary: partition 0, first offset 71701, final next offset 71826.
- Mapping: existing `/api/v1/admin/table-system-mappings` ETag/CAS workflow to the existing
  canonical test System; no database insert and no fabricated mapping.
- Authorization: the disposable subject received the existing bounded System/Table authority; no
  policy widening.

## Required live mutation matrix

| Case | Source mutation | Observed DataHub aspect | Canonical ledger | Authorized UI/API proof |
|---|---|---|---|---|
| Table CREATE | source DB DDL + official ingestion | `datasetProperties`, `schemaMetadata` | offsets 71752-71753, 5 CREATE rows | PASS |
| Column CREATE | `ALTER TABLE ADD COLUMN` + ingestion | `schemaMetadata` | offset 71777, CREATE | PASS |
| Column MODIFY | integer nullable to bigint not-null + ingestion | `schemaMetadata` | offset 71781, UPDATE | PASS |
| Column DELETE | `ALTER TABLE DROP COLUMN` + ingestion | `schemaMetadata` | offset 71785, DELETE | PASS |
| Table description | official DataHub metadata proposal/read-back | `datasetProperties` | offset 71787, DOCUMENTATION UPDATE | PASS |
| Domain | official DataHub GraphQL `setDomain` | `domains` | offset 71789, DOMAIN ADD | PASS |
| Glossary Term | official DataHub GraphQL add/remove | `glossaryTerms` | offsets 71790-71791, ADD/REMOVE | PASS |
| Tag | official DataHub GraphQL add/remove | `globalTags` | offsets 71792-71793, ADD/REMOVE | PASS |
| Column description | official DataHub GraphQL field-description mutation | `editableSchemaMetadata` | offset 71809, DOCUMENTATION CREATE | PASS |
| Table DELETE | source DB DROP + stateful ingestion | `status` | offset 71814, LIFECYCLE DELETE | PASS |

The new `domains` normalization is explicit and generic: DataHub `domains` maps to the existing
platform-neutral `DOMAIN` ledger category. The PostgreSQL CHECK, Node API contract and UI type share
that taxonomy. The idempotent startup schema remains part of `./scripts/prep39083 deploy`; there is
no separate migration command.

## Deleted-Table history and authorization

The exact mapping document now stores a bounded canonical Table authority snapshot at ASSIGN time.
The current DataHub Table must still exist to create the mapping. A historical Change History read
uses the snapshot only after that Table leaves current inventory, and still requires:

1. the exact mapping to remain active;
2. the mapped System to remain active;
3. the current subject to pass the ordinary Table read policy against the stored canonical identity.

This fixes deletion-history disappearance without making a stale inventory row current and without
an authorization fallback. In the acceptance window after physical deletion and official stateful
ingestion:

- DataHub current inventory no longer contained the Table;
- Search Resource Tree contained zero `datariver_change_e2e` ghosts;
- Change Management returned **16** authorized rows: **7 Schema** and **9 Metadata**;
- every row resolved the exact System as `RESOLVED`;
- Schema and Metadata filters each returned a bounded five-row first page with a next cursor;
- detail included source aspect, operation, before/after data, Table locator and System provenance;
- Monitoring and Change Management continued to use the same canonical read API.

## Cleanup and final state

Cleanup was itself performed through source DDL, official stateful ingestion and canonical mapping
CAS, never through ledger deletion. The source schema is absent, active exact mapping count is zero,
and the new source has 20 append-only ledger rows: 16 acceptance rows plus four cleanup lifecycle /
documentation observations. Global ledger count is now 93 (the original 73 plus these 20).

The disposable local credential is disabled, its single session is revoked, re-login returns 401,
and active test sessions are zero. Temporary password, cookie and runtime files were removed. No
temporary browser, process, mapping, source object or controlled glossary/tag/domain fixture remains.

## Verification gates

- Focused Node Change History/mapping/server tests: **50/50 PASS**.
- Final Node Product server suite: **130/130 PASS**.
- Focused UI Chat/Change History suites: **49/49 PASS**.
- Final UI suite: **90 files / 661 tests PASS**.
- ESLint, TypeScript, standard build, POC build, Ruff lint, strict mypy over 588 files and static
  verification: PASS.
- PREP unit/handoff contract: **35/35 PASS**; smoke contract: **3/3 PASS**.
- Isolated PREP Docker state-machine integration: PASS.
- Isolated forced-smoke-failure then same-command retry without duplicate bootstrap: PASS.
- Exact OCI: amd64, revision `a09cd4cb47db7bb31f608dfd94c61f34844d33af`, healthy, HTTP 200.
- `git diff --check`, Compose/release contract checks and secret/proxy-leak scans: PASS.

The repository-wide Ruff formatter check continues to report four unchanged legacy Python test files;
none is part of this Product delta. Ruff lint itself is green. Router intent/retrieval/reranking did
not change, so the accepted 60/60 and Boundary 8/8 evidence was preserved rather than repeated.

## Browser acceptance limitation

The required in-app Browser initialization and troubleshooting flow reported no available browser
instance. Per the Browser safety contract, no alternate browser-control backend was substituted.
The actual authorized rows were verified through the exact production API/read model, and UI
render/filter/detail behavior through the production component suite, but final pointer/visual
inspection remains `FINAL_BROWSER_ACCEPTANCE_SURFACE_UNAVAILABLE`.

No fake ledger insert was used. Production authorization was not widened.

