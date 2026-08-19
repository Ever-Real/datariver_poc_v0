# DEV Knowledge K5 — Durable Ingestion Bridge Closeout

- Scope: Node POC bounded durable A-Box preview/confirm/projection/replay only; no K6.
- Product SHA: `93868fa1c1ff3d7c32fd760b79d58434ac9ae989`
- OCI revision: `93868fa1c1ff3d7c32fd760b79d58434ac9ae989` (exact match); `/healthz` `ok`.
- Schema: two additive tables, `poc_knowledge_ingestion_jobs` and `poc_knowledge_source_rows`.
  No existing table rewrite, queue, worker, service, or framework.
- Runtime: pinned published T-Box/release, exact DataHub Table binding, preview 2 nodes/0
  relations, confirm PROJECTED 2 nodes, replay PROJECTED with duplicate count 0.
- Neo4j: parameterized deterministic MERGE; read-back audit 2 nodes, 0 duplicates.
- Provenance: `DETERMINISTIC_ENRICHER`, exact source URN, manifest ref, source hash, release and
  pinned T-Box version retained in receipt.
- Durability: after Web recreate, four durable records were readable from PostgreSQL, including
  the PROJECTED receipt.
- Authorization: unauthenticated ingestion-list request denied `401 SESSION_REQUIRED`; source
  scope remains current DataHub Table/auth checked at request time.
- Focused tests: Data Enricher 7/7; state/provider 42/42; syntax/build passed. Static verifier
  and final diff check passed.
- Cleanup: disposable K5 rows/job records retained only as DEV evidence; no business asset was
  used. PREP and Git push were not performed.
- New architecture counts: tables 2; migrations 0; dependencies 0; services 0; containers 0;
  queues 0; workers 0; frameworks 0; capabilities 0.
- Remaining risk: independent validator resource was unavailable; no K6 route/mutation started.

Status: `K5 COMPLETE_RUNTIME_VERIFIED`; `K6 NOT_STARTED_DEPENDENCY_GATE`.
