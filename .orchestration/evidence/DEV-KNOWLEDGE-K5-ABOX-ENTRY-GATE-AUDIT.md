# DEV Knowledge K5 A-Box entry-gate audit

## Scope

- Read-only entry gate for Knowledge K5 A-Box Enricher / Projection.
- Current Product and deployed OCI: `fca4535cab544560bd06486dc363e6df0c6df27f`.
- Authoritative runtime: Node POC at `http://127.0.0.1:39083/`.
- No Product, database, provider, container or Neo4j mutation was performed.

## Reusable current primitives

- `knowledgeDrafts`, immutable `knowledgeReleases`, typed `knowledgeDraftBlocks`,
  `knowledgeDraftBindings` and the existing core CAS can represent the authored T-Box and its
  approved source-field mapping contract.
- `DataEnricherStep` already exposes authorized Catalog source selection, typed SUBJECT_ID and
  PROPERTY mappings, preview/pre-flight/result UX and Published-only ingestion controls.
- K1 supplies exact DataHub Dataset/SchemaField identity, release-pinned deterministic IDs,
  parameterized Neo4j `MERGE`, provenance, read-back audit and duplicate-zero verification.

## Blocking gap

- Current DataHub is a metadata provider and does not provide coherent physical rows.
- The Node POC has no current physical source-row reader or bounded row-preview handler. Its K1
  projection materializes source Table/Column identities only; those identities are not A-Box row
  instances.
- The repository contract requires an operator-owned, least-privilege source manifest/secret
  boundary and a durable fenced ingestion job/worker before physical rows can become governed
  typed instance changes. Current DEV has no `runtime/knowledge-studio` manifest, no source-secret
  root and no running Knowledge Studio ingestion worker.
- Frontend preview/success tests use injected response fixtures. They are UX contract tests, not
  current Node runtime evidence of a source reader or A-Box materialization.
- Reclassifying DataHub metadata as rows, accepting browser SQL/DSN, querying an unrelated local
  database or calling the K1 identity projection an A-Box instance release would fabricate
  evidence and violate the approved boundary.

## Decision

- K5 A-Box Enricher / Projection: `HOLD_KNOWLEDGE_ABOX_PERSISTENCE_DECISION`.
- The hold is limited to actual row preview/materialization. Existing K1 identity/provenance and
  K3/K4 mapping/source-proposal baselines remain complete and unchanged.
- No K5 Product mutator was launched. K6 Product mutation was not started because K5 is not
  complete.
- The smallest future decision is whether to provision the already-specified bounded DEV source
  manifest/secret and durable ingestion authority for the authoritative Node Product. That
  decision must not silently activate the legacy FastAPI runtime or add a second graph authority.

## Bounded decision packet

### Option A — reuse the Node core/CAS as a synchronous row-ingestion store

- Rejected. The core/CAS can retain authored Draft, release and mapping documents, but it has no
  durable claim/lease/fence, immutable source pin, attempt/event trail or atomic Changeset result
  contract for physical rows.
- Adding an API-request source scan or persisting raw/sample rows in the core document would
  contradict ADR-0061 and ADR-0094. It would also create a second, weaker ingestion authority.

### Option B — provision the already tracked ADR-0094 ingestion plane

- Recommended only with explicit approval. The repository already contains revision `0081`, the
  fixed database functions and models, the `knowledge-studio-ingestion-worker` implementation and
  the optional `knowledge-studio-ingestion` Compose profile.
- The authoritative browser/API remains the Node POC. A future bounded Node facade may issue and
  read only the existing fixed-function command/result contract; it must not start the legacy
  FastAPI application or accept DSNs, SQL, identifiers or credentials from the browser.
- DEV provisioning is still a material runtime change: it requires the existing PostgreSQL
  migration/roles, a dedicated service Subject, the immutable deployment-owned source manifest,
  mounted secret references, an approved disposable read-only PostgreSQL source and the optional
  worker/container. The current runtime has none of these inputs.
- Rollback is to disable the optional profile/facade while retaining immutable evidence. It does
  not delete jobs, events, attempts, receipts or Knowledge history.

### Approval boundary

- Approval ID: `APPROVE_K5_CANONICAL_INGESTION_PLANE_DEV`.
- Approval permits only the tracked ADR-0094 DEV plane and the smallest Node fixed-function facade
  needed by the current Product. It does not permit a new table design, new ingestion framework,
  legacy FastAPI authority, PREP/OPS mutation, business-data testing or destructive cleanup.
- Until approval, K5 remains HOLD and K6 remains unstarted. This is an implementation/deployment
  authority decision, not a request for a secret value.

## Independent read-only audit

- Requested/effective model: Gemini 3.1 Pro High, plan/read-only.
- The worker independently returned `HOLD_KNOWLEDGE_ABOX_PERSISTENCE_DECISION` because no approved
  physical row reader or configured DEV ingestion authority exists. It modified no repository
  file. Unrelated generic state-projection helper suggestions were not accepted as K5 evidence;
  the CONTROL_PLANE decision above is based on the current Node Knowledge paths and runtime.

## Status and complexity

- Knowledge overall: `PARTIAL`.
- K0 through K4: `COMPLETE_RUNTIME_VERIFIED`.
- K5: `HOLD_KNOWLEDGE_ABOX_PERSISTENCE_DECISION`.
- K6: `NOT_STARTED` by dependency gate.
- New tables 0; dependencies 0; services 0; containers 0; queues 0; workers 0; frameworks 0;
  capabilities 0.
