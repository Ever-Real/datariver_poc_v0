# CHANGE_HISTORY_EXECUTION_PLAN

## VERIFIED BASELINE
- repo /Volumes/SSD_Mac/workspace/datariver_poc_v0; dev exact SHA 78e533db6db0352dc0b6d44a557db22a7b05162c; origin/dev af97af3c5c77449398711fbf33638aad1f980499; ahead 6; origin/main absent; DEV_MAC_ARM64.
- pre-existing dirty harness only: CURRENT.md and .orchestration/receipts/CP-WORKTREE-TOPOLOGY-001.md. Product source unchanged.
- G1/G2/G3/G4 NOT_APPROVED.
- T00 task_0100eed10b29 and T01 task_5ef78a4bdfa9 completed by verified control recovery; no file modifications.

## T00 VERIFIED
- native Node POC listens *:39080; pgvector/Redis/Neo4j/Airflow containers healthy.
- Search path: UI catalog -> /poc-api/datahub/catalog -> DataHub GMS GraphQL. Unfiltered page uses direct scroll; filtered search loads full inventory. GMS page 250, cap 10,002 pages; inventory cache 15m.
- detail path /poc-api/datahub/asset with Redis 60s cache; schema field pagination at 100.
- Chat SSE; GENERAL sample 200 about 25.6s, evidence 0; catalog sample 5/2000 about 83.9ms/6624 bytes; first detail 14/14 about 38.6ms/8533 bytes; vector status READY, 2000 indexed; profile coverage 2000 schema, 0 row/size/created fields. Warm single samples only, not load tests.
- Node has established PostgreSQL 127.0.0.1:15432 and Redis 127.0.0.1:16379 connections. PostgreSQL is current state/vector authority; Redis optional acceleration.
- POC DB public schema uses poc_state and poc_catalog_embedding; vector extension. Current core state uses whole-scope JSON PUT, version returned but no expected-version/CAS and no DB target identity marker.
- runtime CR evidence: two records; one CHANGES_REQUESTED initial round, one TESTING edited round 2; one active ADMIN profile; zero registered systems/assignees. Existing states/revision/approval/target binding must not be changed.
- Monitoring external tabs use MONITORING_DASHBOARDS_JSON, max 8; GRAFANA_EMBED_EVIDENCE_REFERENCE is not dashboard list. Native built-in change screen absent.
- policy conflicts: AGENTS.md says dev/main only while user explicitly approved local Task child worktrees; record explicit override. AGENTS prep-update targets Ever-Real/datariver_v1 but this project forbids access; keep POLICY_CONFLICT and do not access.

## DBEAVER_CONNECTION_SHEET
- container datariver-poc-pgvector-1
- host source POC_STATE_BIND_HOST, default 127.0.0.1
- exposed port source POC_POSTGRES_HOST_PORT, default 15432
- internal 5432
- database source POC_POSTGRES_DB, default datariver_poc
- username source POC_POSTGRES_USER, default datariver_poc
- password source local .env POC_POSTGRES_PASSWORD; never print value
- SSL mode: local Compose has no TLS contract; record DISABLE_FOR_LOCAL_COMPOSE / target UNKNOWN
- schemas: public for POC init tables
- extensions: vector
- migrations: POC tables via deploy/poc/postgres-init/001-poc-state.sql; backend has Alembic convention separately.

## T01 VERIFIED/UNKNOWN
- local DataHub GMS, Kafka, Schema Registry containers observed.
- OpenAPI advertises /openapi/v2/timeline/v1/{urn}.
- no authenticated secret-free safe data probe completed.
- categories TECHNICAL_SCHEMA/DOCUMENTATION/TAG/GLOSSARY_TERM/OWNERSHIP UNKNOWN.
- intermediate events, retained history, version counts, stable identities, retention/catch-up risk UNKNOWN.
- MCL topic MetadataChangeLog_Versioned_v1/schema IDs/partition offsets/retention NOT_EXECUTED.
- selected_candidate UNDECIDED_PENDING_TARGET_PROBE.
- exact PREP/admin read-only NOTI required: using target-managed credentials without printing them, test real non-sensitive Dataset URN Timeline categories, pagination/stable event identity/intermediate A->B->C; capture earliest/latest/version count/retention config. Inspect Kafka topic existence/config and Schema Registry subject/schema plus consumer-group-free end offsets without committing offsets. Record commands redacted, timestamps, environment, GMS/DataHub version, no writes.

## PROVISIONAL ARCHITECTURE
- exact capture: Timeline first only if all authoritative conditions pass; else existing MCL; otherwise BLOCKED_EXACT_CHANGE_CAPTURE.
- nightly reconciliation never authoritative history source.
- current projection separate from append-only ledger; PostgreSQL canonical, Redis cache, pgvector latest generation only.
- UTC timestamptz storage, Asia/Seoul business display/week/schedule configuration.
- dedup source identity + entity/aspect/category/version/event timestamp/payload hash; source-specific checkpoint.
- indefinite normalized ledger, no repeated raw schema document.
- assignment policy configurable, snapshot at detection.
- CR link separate relation; no CR auto transition; primary/candidate/history.
- existing CR display mapping is presentation-only per user directive.
- no new DB/container/framework.

## TASK DAG TO RECORD
- T00 completed, owner 10, R2 read-only.
- T01 completed with target-probe blocker, owner 40, R2 read-only.
- T02 owner 10, R3 planning, depends T00/T01 plus target probe, allowed docs/adr/0123-datahub-change-history-ledger.md only, acceptance source decision/model/checkpoint/dedup/schedule/API/UI/storage estimate/no-new-container conclusion, validation architecture review, no gate for local candidate but G1 integration.
- T03 owner 40 backend/data Builder, R3 migration, depends T02, allowed backend migration/domain paths to be enumerated after T02, validation migration upgrade/downgrade/unit tests, G1.
- T04 owner 40, R2 exact capture, depends T02/T03, selected adapter only, validation intermediate events/idempotency/catch-up.
- T05 owner 40, R2 reconciliation/performance, depends T02/T03, may parallel T04 only if paths isolated, validation fast refresh/nightly/tombstone/atomic switch/Redis fallback/vector.
- T06 owner 30, R3 access/assignee/CR APIs, depends T02/T03, 10 review, existing CR transitions unchanged.
- T07 owner 60, R2 UI, depends T05/T06, native Monitoring + CR weekly table, external tab regression.
- T08 owner 50, R3 independent validation, depends T04-T07, no repair.
- T09 owner 90, R3 fresh audit High~XHigh, depends T08, do not repair.
- max two mutating tasks; initial next executable is PREP/admin read-only target probe via NOTI, user/environment action needed, G3 mutation not authorized.
