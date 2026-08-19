# DEV Knowledge K5 — Durable Ingestion Bridge Closeout

- Scope: bounded Node POC A-Box preview/confirm/projection/replay only; K6 was not started.
- Product SHA / deployed OCI: `34af2b869d04fd96f4b9cd69f6eeed8729bafe28` (exact);
  Web `http://127.0.0.1:39083/healthz` returned `ok` before and after Web-only restart.
- Architecture: existing Node identity, release/binding/CAS, authorization and K1 parameterized
  Neo4j MERGE were reused. No Python/FastAPI authority, generic job/queue/worker or secret value
  storage was added.
- Schema/migration: additive `deploy/poc/postgres-init/002-poc-knowledge-ingestion.sql` creates only
  `poc_knowledge_ingestion_jobs` and `poc_knowledge_source_rows` in one transaction with
  `IF NOT EXISTS`. It passed existing-DB reapply; clean Compose initialization uses the same file.
- Source boundary: one deployment-owned, non-secret manifest reference pinned the exact DataHub
  Table URN and two canonical-hash-validated disposable rows. Browser DSN/SQL/token input was not
  accepted.
- Browser/runtime: published release `e91b78c5-f9c0-412e-86ff-95eb997592bd`, T-Box version `4`,
  exact target Class and source were shown. Preview reported Node 2 / Relation 0 / Rejected 0 /
  Unmapped 0 / `DETERMINISTIC_ENRICHER`; scoped Neo4j count was 0 before confirmation.
- Projection/replay: two confirmed executions each returned durable `PROJECTED`, DRAFT changeset,
  Node 2 / Edge 0 / duplicate 0. Neo4j read-back was 2 total = 2 distinct, T-Box `4`, exact two
  source hashes and `DETERMINISTIC_ENRICHER` provenance.
- Durability: hard reload and a Web-only container recreate preserved the authenticated session,
  latest SUCCESS/DRAFT changeset and two PROJECTED receipts in PostgreSQL.
- Authorization negatives: a real no-grant manager browser saw `NOT_RUN` and no job/count/
  provenance; direct list returned `403 KNOWLEDGE_TABLE_FORBIDDEN`. An unpublished draft returned
  `409 KNOWLEDGE_DRAFT_NOT_PUBLISHED` even to Admin.
- Tests: focused K5 server/UI/live-proxy tests passed; Node full `109/109`; frontend full `87`
  files / `617` tests; lint, typecheck, production build, Compose render and diff check passed.
- Cleanup: exact disposable Neo4j nodes `4`, ingestion jobs `5` and source rows `2` were removed;
  the prior K5 draft is `DISCARDED`; three K5 credentials were disabled and sessions revoked;
  temporary password files, isolated browser profiles and runtime manifest were removed. The K1
  baseline Asset/release was not archived or modified.
- New architecture count: tables `2`; migrations `1`; dependencies `0`; services `0`; containers
  `0`; queues `0`; workers `0`; frameworks `0`; capabilities `0`.
- Remaining risk: the POC schema-migration contract remains partial and has no automatic down
  migration. Independent validator was unavailable (`K5_VALIDATOR_PENDING_RESOURCE`); coordinator
  source, full-suite, exact SHA/OCI, browser, restart, Neo4j and cleanup evidence was captured.
- Git push and PREP mutation were not performed.

Status: `K5 COMPLETE_RUNTIME_VERIFIED`; `K6 NOT_STARTED`.
