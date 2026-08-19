# DEV Knowledge K5 CONTROL_PLANE reclaim

## Scope and lineage

- Approval `APPROVE_K5_CANONICAL_INGESTION_PLANE_DEV` was received for the already accepted
  ADR-0094 plane only. K0 through K4 remained frozen and K6 was not started.
- Authoritative worktree: `/Users/everreal/orca/workspaces/datariver_poc_v0/dev-core-t04-validation`.
- Repository/evidence baseline: `07cbe1e0d87e46ef069a44278ea3276111230a13`.
- Product and deployed OCI: `fca4535cab544560bd06486dc363e6df0c6df27f`.
- `/Volumes/SSD_Mac/workspace/datariver_poc_v0` is an older MCL documentation lineage and is not
  the Knowledge K5 source of truth.

## Temporary Gemini inventory

- Reclaimed state: `PAUSED_UNVERIFIED_DIRTY_DIFF`.
- The only tracked modifications added an in-memory preview and immediately completed job with
  random graph/release/Changeset identities, plus a browser-client proxy that bypassed the existing
  bounded POC handling. No test had been run.
- Classification: server mock `DROP`; client proxy `DROP`; accepted Product change `NONE`.
  The narrow Gemini hunks were removed without resetting the worktree or touching other changes.
- The completed Orca K5 audit worker was already disconnected and its Dispatch had already been
  released. No new Gemini/Claude/validator worker was launched.
- Deployed Web remained at the prior Product. POC PostgreSQL had no
  `knowledge.studio_ingestion_jobs` relation. Neo4j retained the existing K1 projection only
  (2 `KnowledgeSourceEntity` nodes / 1 `HAS_COLUMN` edge). No temporary worker Product commit,
  DB migration, Neo4j write or container recreation was found.

## Blocking contract gap

- ADR-0094 is implemented in the canonical Python application schema and worker. Its successful
  ingestion result is an immutable, provenance-bearing DRAFT Changeset; it does not directly write
  Neo4j or publish an instance Release.
- The authoritative runtime is instead the Node POC Compose. Its PostgreSQL contains the POC state
  schema, not revision `0081`; its local Subject and Asset identities are not the canonical UUID/IAM
  rows required by the fixed database functions.
- The Node POC has no fixed-function database adapter to that plane. The accepted root Compose
  worker exists, but the authoritative DEV runtime has no canonical backend/database deployment,
  source manifest, source-secret root, worker identity or retention binding configured.
- Adding a POC-specific job table/function set, identity mirror or synchronous raw-row scan would
  be a new ingestion authority outside ADR-0094. Starting FastAPI as a second API authority is also
  outside the approval. A physical source secret cannot repair the missing identity/schema bridge.

## Decision and evidence

- K5: `HOLD_KNOWLEDGE_ABOX_SCHEMA_EXPANSION`.
- Required decision: either make the canonical ADR-0094 database/identity plane authoritative for
  the Node Product through an explicitly designed fixed-function adapter, or approve a separate
  POC schema/identity bridge. The latter is not inferred from the existing approval.
- The minimum missing schema concepts are a canonical Workspace/Subject/Asset/Studio Release
  identity mapping and durable function-owned ingestion job/result references. Existing POC
  core/CAS cannot safely represent claim, lease, fence, attempt, immutable source pin and atomic
  Changeset provenance.
- Executed checks: both worktree lineages, Git diff/check/status/history, OCI label, `/healthz`,
  current container start state, POC database relation/job inventory and bounded Neo4j counts.
- Product SHA and OCI remain equal. No Product commit or deployment was made, so focused/full
  Product regression, browser K5 write E2E and independent validator were not claimed.
- New tables 0; dependencies 0; services 0; containers 0; queues 0; workers 0; frameworks 0;
  capabilities 0.
