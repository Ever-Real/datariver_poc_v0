# Production hardening and scale decision record

Status date: 2026-07-15 (Asia/Seoul)  
Scope: current `datariver_v1` branch and verified hybrid development runtime
Decision: preserve the modular-monolith core; execute measurable P0 gates before introducing a
search engine, external LLM or additional service boundaries.

## 1. Platform mission and current product boundary

DataRiver is the secure R&D data-catalog and knowledge-governance control plane around an externally
operated DataHub. It provides one workspace-scoped surface for catalog discovery, object-backed
registration, metadata change approval/application, quality/freshness visibility, immutable
knowledge-graph releases, release-pinned analysis/API sharing, evidence-grounded Chat and platform
operations.

DataHub remains canonical for applied catalog metadata. DataRiver PostgreSQL is canonical for
identity mappings, ABAC decision evidence, change intent/approvals, jobs/outbox/inbox, upload
manifests, KG ontology/changesets/releases, Chat audit and API grants. Valkey, Airflow and graph/search
projections are replaceable acceleration or delivery planes. No generic DataHub GraphQL, SQL,
Cypher, Bolt, shell or arbitrary HTTP surface is exposed.

## 2. Implemented runtime and code structure

| Layer/runtime | Implemented responsibility |
|---|---|
| `frontend/` | React/TypeScript dashboard, catalog, registration, governance, KG, Chat and sharing flows |
| API process | FastAPI/OIDC boundary, request IDs, ABAC, RLS context, typed use cases and Prometheus endpoint |
| PostgreSQL 17 | nine canonical schemas, RLS, optimistic versions, immutable releases and durable delivery state |
| outbox relay | leases unpublished PostgreSQL events and sends event IDs to queue Valkey |
| upload workers | multipart completion/reconcile and bounded-memory validation/promotion; no DataHub secret |
| governance worker | leased typed DataHub aspect apply plus re-read hash reconciliation |
| DataHub adapter | fixed GraphQL/aspect contracts, timeout/error mapping, bounded concurrency and circuit breaker |
| Valkey cache/queue | separate TTL/evictable cache and AOF/no-eviction delivery instances; never canonical |
| SeaweedFS S3 profile | quarantine/accepted objects behind the object-store port; PostgreSQL owns the manifest |
| Airflow overlay | paused catalog probe/full reconciliation DAGs using short-lived Keycloak client credentials |
| APISIX/Keycloak overlays | optional local edge/OIDC; application ABAC remains mandatory |

The code dependency rule is `interfaces/workers/infrastructure -> application -> domain`; domain code
does not import provider frameworks. Independent processes share a versioned distribution, not
domain-model shortcuts. Service extraction occurs only at existing ports and only with measured
scale/availability/team-ownership evidence.

## 3. Verified baseline and important limitations

The current branch passes 76 backend tests, strict mypy over 110 files, Ruff, frontend
type/lint/test/build, deterministic migration generation and static architecture/Compose/role checks.
The hybrid runtime has live evidence for PostgreSQL RLS, Keycloak service-token OIDC, APISIX,
Vite proxying, DataHub authentication and semiconductor seed verification. Target DataHub, target
object storage, production identity, large data, backup/restore and 60-minute soak gates remain open.

The frontend is a functional integration baseline, not a completed enterprise UX: catalog facets,
autocomplete/lineage, policy administration, audit/job browsing, Chat history/SSE/external-model
adapter, automated KG extraction/projection rebuild and several upload lifecycle endpoints remain
explicit API backlog.

## 4. Provisional capacity hypothesis

These numbers create a reproducible load-test envelope; they are not a business SLA. Product,
security and infrastructure owners must replace or approve them before production sizing.

| Dimension | Initial target | Stress gate | Evidence required |
|---|---:|---:|---|
| active assets per workspace | 1,000,000 | 3,000,000 | skewed names/descriptions, 4 data classes, real scope cardinality |
| total active assets | 5,000,000 | 15,000,000 | at least 10 workspaces with unequal sizes |
| daily asset changes/workspace | 50,000 | 200,000 | create/update/delete mix and late events |
| peak concurrent human users | 500 | 2,000 | OIDC, RLS, search/detail/governance mix |
| catalog search request rate | 100 RPS | 300 RPS | 60-minute cached/uncached mix |
| Chat request rate | 5 QPS | 20 QPS | retrieval, denial and long-response mix measured separately |
| KG per large workspace | 2M nodes / 10M edges | 10M / 50M | release build, export, bounded traversal and rebuild hash |
| governance writes | 20 RPS | 60 RPS | idempotency, approval and outbox atomicity |

Reference latency/error objectives remain cached search p95 <= 300 ms, uncached p95 <= 800 ms,
change-request write p95 <= 400 ms and error rate < 1%. Add p99 <= 1.5 s for uncached search to
prevent a good p95 from hiding long authorization/DB waits. API RSS, DB CPU/connections/locks, Valkey
memory/evictions, DataHub latency/concurrency and audit rows/transaction must accompany latency.

## 5. Freshness, revocation and classification objectives

Provisional objectives are incremental projection lag p95 <= 5 minutes and p99 <= 15 minutes;
full reconciliation completes inside 24 hours and is used for verification/recovery rather than the
normal freshness path. The current offset scan is a full reconciliation, so the incremental contract
cannot be accepted until the deployed DataHub version exposes a stable event/change watermark and
late-arrival behavior is contract-tested.

Permission revocation must become effective p99 <= 60 seconds after the authoritative change and
emergency edge blocking <= 15 seconds. The current API reloads membership attributes per request,
and cache keys include actions/denies/clearance/system/domain plus policy version and source
watermark. Still required: two-identity timing tests for membership, classification, explicit deny,
policy-version rollout and already-open Chat/stream connections.

Proposed production default, pending security/data-owner approval:

| Class | Catalog search/detail | Chat/RAG | Cache/provider rule |
|---|---|---|---|
| PUBLIC | action + workspace policy | permitted | normal short TTL; approved provider allowed |
| INTERNAL | clearance + system/domain | permitted | workspace-scoped; provider residency/retention approved |
| CONFIDENTIAL | clearance + system/domain | named Chat entitlement only | no prompt/evidence content cache; zero-retention private provider |
| RESTRICTED | named direct-read entitlement | denied by default | no external LLM; metadata-only operational signals |

The current deterministic Chat calls no external model and persists cited authorized evidence, but it
does not yet implement the proposed CONFIDENTIAL/RESTRICTED Chat-specific entitlement. Production
external inference stays disabled until this matrix is approved and enforced.

## 6. P0 implementation and remaining gates

| Workstream | Current disposition | Remaining acceptance |
|---|---|---|
| literal search safety | implemented: NFKC, minimum non-empty length, `%`/`_`/backslash escape | API negative tests and UX message in browser E2E |
| PostgreSQL search | implemented: stored `tsvector`, GIN FTS, `pg_trgm` name index, active scope/order partial index | target-distribution EXPLAIN/BUFFERS and write-cost measurement |
| search cache | implemented: short TTL key includes workspace, full permission scope, policy version, request and watermark; access/source counters expose hit/miss/error/write paths | Valkey eviction exporter and revocation timing under load |
| ABAC audit amplification | Chat candidates evaluated as a set; one grouped row retains per-resource effect/reasons | extend to facets/autocomplete/export; partition/retention volume proof |
| DataHub isolation | timeout, concurrency bulkhead, circuit breaker, fresh + bounded stale detail fallback; fixed-label request/duration/in-flight/rejection/circuit metrics | target contract/fault test; worker-process metrics; incremental watermark |
| local read projection | search and base detail survive DataHub read failure inside stale bound | project approved detail aspects and display freshness consistently in UI |
| worker privilege | separate API/relay/upload/governance/bootstrap DB roles and secrets; upload has no DataHub secret | egress policy in target orchestrator; correlation/scope guard for every BYPASSRLS claim |
| audit/event retention | config has event retention; Chat defaults 90 days | monthly partitions, legal retention, deletion jobs and WORM export |

### Partition and WORM design gate

Partition `authz.policy_decisions`, `integration.outbox_events`, `integration.inbox_messages` and high-
volume Assistant audit tables by monthly decision/event time only after measured rows/day and legal
retention are approved. The migration must account for PostgreSQL's requirement that partitioned
unique/primary keys include partition keys. Pre-create at least two future partitions, alert on the
default partition, detach expired partitions, checksum and export them to an Object-Lock/WORM-capable
bucket before deletion.

Provisional retention: outbox/inbox online 30 days after completed/published, Chat content 90 days
unless workspace policy is shorter, policy decisions and governance audit online 13 months plus
immutable archive for 7 years. Legal, privacy and trade-secret owners must approve these values.

### Search-plan evidence matrix

Run `EXPLAIN (ANALYZE, BUFFERS, WAL, SETTINGS)` for empty browse, exact name, rare/common token,
substring/typo, description-only match and no-result queries. Each case runs with PUBLIC-only,
10/50/90% permitted ratios, high-cardinality and broad system/domain scopes, first/deep cursor and
cold/warm cache. Reject the plan if it performs an unbounded sequential scan at target volume or if
index write amplification prevents the daily-change gate.

## 7. P1 read-plane decision

Do not add OpenSearch merely because the product is a catalog. Introduce an outbox-fed, idempotent
search read model when any one condition persists after PostgreSQL tuning:

- the 60-minute soak misses cached p95 300 ms, uncached p95 800 ms or <1% error rate;
- DB CPU, connection wait or lock wait remains above the deployment's reviewed threshold;
- required facet/autocomplete/lineage/hybrid behavior cannot meet correctness/latency with PostgreSQL;
- projection freshness exceeds the approved watermark.

The extracted read model stores authorization attributes, source version/watermark and document hash;
tracks consumer/index lag, DLQ, reindex generation and drift hash; builds a shadow index and atomically
switches aliases. PostgreSQL/DataHub ownership does not change, and stale state remains visible.

## 8. P2 Assistant/KG decision

The current Chat is deliberately deterministic and evidence-only. External inference requires a
separate assistant worker so API processes do not hold model calls, embedding work or long provider
connections. Retrieval units become immutable evidence chunks carrying workspace, classification,
allowed scope, source/version/locator, effective time and content hash—not bare asset/node IDs.

The model receives no SQL, Cypher, arbitrary HTTP or apply/publish tool. Answers without authorized
citations return `검증 불가`; KG output is only a proposed changeset routed through existing validation,
independent review and immutable release publication. Maintain a separate red-team corpus for direct/
indirect prompt injection, poisoned RAG documents, encoding/Unicode, tool abuse, data exfiltration and
malicious output markup. RAG relevance is not a prompt-injection control.

## 9. P3 deployment and observability decision

- API: multiple replicas, independent liveness/readiness, explicit pool budget per replica; introduce
  PgBouncer only after transaction-local RLS context leakage tests.
- PostgreSQL: HA topology, PITR/WAL archive, isolated restore drill, partition/autovacuum plans and
  measured RPO <= 5 minutes/RTO <= 60 minutes.
- Objects: replicated, encrypted S3-compatible target with lifecycle, checksum, Object Lock where
  required and restore evidence; local single-node SeaweedFS is not the production topology.
- Delivery: retain Valkey + PostgreSQL outbox until retention/multi-consumer throughput requires a
  durable event log. Kafka/Pulsar does not replace canonical outbox/inbox semantics.
- Airflow: LocalExecutor remains valid for a small single machine; use a remote/container executor
  for multi-machine or large batch after operational-cost review.
- Signals: deploy Prometheus plus OTel Collector/backend with request/trace/job correlation; include
  queue/outbox lag, DB pool/locks, DataHub bulkhead/circuit/latency, cache hit/eviction, projection lag,
  denial rates and later LLM latency/tokens/cost/citation/refusal metrics.

## 10. Ordered execution backlog

1. Obtain signed capacity, classification/Chat and retention decisions; record reference hardware and
   target DataHub/OIDC/S3 versions.
2. Run migration on an empty copy and a production-sized synthetic copy; capture the search-plan
   matrix and index write/storage cost.
3. Add policy/source revocation timing, target DataHub fault, worker kill/reclaim and 60-minute
   load/soak automation; cache/API DataHub metrics are exposed, while worker/sync/Valkey metrics remain.
4. Implement and contract-test incremental DataHub change-watermark ingestion, retaining nightly full
   reconcile as drift verification/recovery.
5. Add partition provisioning/retention/WORM export only with approved volume/legal inputs.
6. Apply the P1 decision gate. If it fails, extract search indexing first through the outbox port.
7. Build evidence chunks and an isolated assistant worker, then pass ABAC and prompt-injection red-team
   gates before enabling any external model.
8. Complete HA/PITR/object recovery, browser E2E, enterprise OIDC/Airflow auth, signed images/SBOM and
   accountable production acceptance.

## 11. Decisions required from accountable owners

- approve or replace every capacity/stress number and name the reference host;
- approve incremental/full sync lag, permission-revocation SLA and emergency kill-switch behavior;
- approve the four-class search/Chat/provider matrix and cross-border/retention restrictions;
- approve audit/Chat/event online and WORM retention, legal hold and deletion authority;
- supply target DataHub version/capabilities, enterprise IdP claims, S3 implementation and deployment
  topology so open contract/recovery gates can produce real evidence.
