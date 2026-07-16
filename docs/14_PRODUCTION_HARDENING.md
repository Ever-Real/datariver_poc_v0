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
| classification/inference governance | versioned four-class policies, provider-profile eligibility and policy-bound RESTRICTED Search grants with Admin API/UI |
| assistant inference seam | disabled-first typed worker contract and output validation only; no provider integration or runtime process |

The code dependency rule is `interfaces/workers/infrastructure -> application -> domain`; domain code
does not import provider frameworks. Independent processes share a versioned distribution, not
domain-model shortcuts. Service extraction occurs only at existing ports and only with measured
scale/availability/team-ownership evidence.

## 3. Verified baseline and important limitations

The current branch passes 371 backend tests, strict mypy over 183 source/test files, Ruff, and 17 frontend
test files/69 tests plus type/lint/build. The frontend artifact is JS 476.15 kB (gzip 136.83 kB) and
CSS 36.31 kB (gzip 7.54 kB). Deterministic migration generation and static
architecture/Compose/role checks also pass.
The hybrid runtime has live evidence for PostgreSQL RLS, Keycloak service-token OIDC, APISIX,
Vite proxying, DataHub authentication and semiconductor seed verification. Target DataHub, target
object storage, production identity, large data, backup/restore and 60-minute soak gates remain open.

The approved DataHub provider baseline is the stable `v1.6.0` contract in ADR-0008. Production
promotion requires the external deployment to pin the reviewed OCI digests, enable runtime version
enforcement and pass live scan/detail/lineage/apply/read-back contract tests. A matching version
string alone is not production acceptance evidence.

The frontend now has a governed enterprise shell with dense square-edge tokens, typed navigation,
explicit Workspace commit/remount, a no-preload two-character global-search floor and server-scoped
Admin visibility. It is not a completed enterprise UX. Classification policy,
inference-profile review/revocation and RESTRICTED-grant administration are implemented.
Catalog normalized hierarchy/lineage, audit/job browsing, Chat history/SSE/external-model adapter,
automated KG extraction/projection rebuild and several upload lifecycle endpoints remain explicit API
backlog.

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
and cache keys include actions/denies/clearance/system/domain plus policy version and a monotonic
local projection version. The seeded direct-API probe passed 100 iterations per scenario with p99
100.660 ms for inactive membership, 167.743 ms for explicit search deny and 193.388 ms for system/
domain scope removal, using one unchanged token and verified restoration. Still required: target-load,
two-identity classification/policy-version rollout and already-open Chat/stream timing tests; the local
numbers do not establish the emergency edge-blocking SLA.

Proposed production default, pending security/data-owner approval:

| Class | Catalog search/detail | Chat/RAG | Cache/provider rule |
|---|---|---|---|
| PUBLIC | action + workspace policy | permitted | normal short TTL; approved provider allowed |
| INTERNAL | clearance + system/domain | permitted | workspace-scoped; provider residency/retention approved |
| CONFIDENTIAL | clearance + system/domain | named Chat entitlement only | no prompt/evidence content cache; zero-retention private provider |
| RESTRICTED | named direct-read entitlement | denied by default | no external LLM; metadata-only operational signals |

The active governed classification-policy snapshot, immutable provider-profile version and exact
policy-bound RESTRICTED Search grants are now evaluated in Search/detail and Chat retrieval. A
missing, malformed, expired or revoked dependency falls back to the portable static floor.
RESTRICTED Search requires both the explicit scope grant and ordinary ABAC; RESTRICTED Chat is always
denied. The current Chat still calls no external model and persists only validated cited evidence.
Production external inference remains disabled despite the implemented administration/routing
eligibility controls.

## 6. P0 implementation and remaining gates

| Workstream | Current disposition | Remaining acceptance |
|---|---|---|
| literal search safety | implemented: NFKC, minimum non-empty length, `%`/`_`/backslash escape | API negative tests and UX message in browser E2E |
| PostgreSQL search | implemented: stored `tsvector`, GIN FTS, `pg_trgm` name index, active scope/order partial index and lower-name short-prefix index | target-distribution EXPLAIN/BUFFERS and write-cost measurement |
| search cache | implemented: search/facet/suggestion short TTL keys include workspace, full permission scope, policy version, request and transactional local projection version; access/source counters expose hit/miss/error/write paths; local same-token membership/deny/scope revocation p99 is below 200 ms | Valkey eviction exporter and two-identity revocation timing under target load |
| ABAC audit amplification | Search/facet/suggestion and Chat candidates are SQL-prefiltered as sets; each request keeps a top-level authorization decision and Chat retains one grouped evidence decision row | export coverage and partition/retention volume proof |
| change-target authorization | partial: new items persist a server-only immutable local dataset identity/scope binding; create and state mutation share the request DB session, projection rows use share locking, lists use one grouped current-target decision, point reads hide denied targets, approval/forward transitions reject target fingerprint drift, legacy unbound rows are quarantined, and the worker rejects unsafe/unbound queued shapes and reconciles an already-observed approved hash | revalidate current requester/classification policy at apply under an approved least-privilege worker read capability, serialize provider+URN+aspect, obtain provider CAS where available, replace ordinary raw aspect JSON with typed edit DTOs and bind accepted upload content to the exact proposal |
| DataHub isolation | timeout, concurrency bulkhead, circuit breaker, fresh + bounded stale detail fallback; fixed-label request/duration/in-flight/rejection/circuit metrics | target contract/fault test; worker-process metrics; incremental watermark |
| local read projection | search and base detail survive DataHub read failure inside stale bound | project approved detail aspects and display freshness consistently in UI |
| worker privilege | separate API/relay/upload/governance/bootstrap DB roles and secrets; upload has no DataHub secret | egress policy in target orchestrator; correlation/scope guard for every BYPASSRLS claim |
| audit/event retention | governed policy versions, Legal Hold and non-executing erasure Maker-Checker persistence/API/history are implemented with forced RLS and no cascading/delete privilege; relay pruning remains removed | verified WORM receipt/conformance, one-time execution claim, archive-only/erasure workers, restore proof, then table-family monthly partitions |

### Partition and WORM design gate

Partition `authz.policy_decisions`, `integration.outbox_events`, `integration.inbox_messages` and high-
volume Assistant audit tables by monthly decision/event time only after measured rows/day and legal
retention are approved. The migration must account for PostgreSQL's requirement that partitioned
unique/primary keys include partition keys. Pre-create at least two future partitions, alert on the
default partition and rehearse late-event and restore behavior. No detach/drop path exists yet.

Retention durations are not portable source defaults. Deployment values must be authored,
independently approved, versioned and activated in the database policy aggregate. Neither policy
activation nor expiry alone authorizes deletion.

Before a future detach/drop, the exact immutable range must be exported through an archive port that
is separate from upload storage. The worker records a deterministic manifest, row/byte counts and
SHA-256, obtains an immutable object version, fully reads the content back, reads Object-Lock
retention back and commits a matching PostgreSQL receipt. Provider names or S3 compatibility are not
capability evidence. The target deployment must prove versioning, Object Lock, compliance-mode
retention, checksum/version behavior and rejection of retention shortening and protected-version
deletion; missing, stale or mismatched proof fails closed for every provider.

Legal Hold takes precedence, and release-pending is treated as held. Explicit erasure is separate
from automatic retention and requires a typed target, current target/policy version, canonical
payload hash, distinct maker/checker, strong authentication and atomic one-time consumption. A
partition containing any applicable hold is initially retained in full.

Automatic deletion, expiry-driven object lifecycle deletion and monthly-partition detach/drop remain
`DISABLED_NOT_READY`. PostgreSQL now persists append-only capability attestations and receipts, but
no export or retention worker is wired and the current development object store has not proved WORM
conformance. Destructive paths stay disabled until a separate least-privilege worker and target
conformance/restore evidence exist. Relay roles retain no delete privilege. See ADR-0010.

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

The PostgreSQL cache generation is now a workspace-scoped monotonic projection version. It advances
once per committed reconciliation page or seed mutation and is deliberately not presented as an
external DataHub source cursor or proof that a full reconciliation is complete. Incremental source
watermark and lag measurement remain prerequisites for a valid read-plane freshness comparison.

## 8. P2 Assistant/KG decision

The current Chat is deliberately deterministic and evidence-only. Its retrieval units are now
immutable evidence chunks carrying workspace, classification, typed system/domain/owner scope,
source/version/locator, effective time, extraction method and canonical content hash—not bare
asset/node IDs. A provider-neutral composer returns cited chunk IDs; empty, duplicate, unauthorized
or hash-invalid citations fail closed to `검증 불가` and persist no citation.

The separate assistant worker source boundary now defines a disabled-first typed execution contract,
so API processes still make no model call and hold no provider connection. The default adapter has no
SDK, endpoint, secret or egress and always refuses. No durable inference job, dispatch path or model
provider is configured in this baseline.

The inference package/result schema has no SQL, Cypher, arbitrary HTTP, tool or mutation field.
Answers without an exact authorized citation subset return `검증 불가`; KG output remains only a future
proposed changeset routed through existing validation, independent review and immutable publication.
Before any provider enablement, implement pre-call and post-call live policy/profile/attestation
revalidation, durable queue/idempotency, SSE timing/cancellation, latency/token/cost/refusal metrics
and a scaled red-team corpus for direct/indirect prompt injection, poisoned RAG documents,
encoding/Unicode, tool abuse, data exfiltration and malicious output markup. RAG relevance is not a
prompt-injection control.

## 9. P3 deployment and observability decision

The current Compose/host-development topology is explicitly Single-node Pilot. ADR-0013 prohibits an
HA claim until at least three independent nodes, off-host distributed storage and measured failover/
restore evidence are accepted. Likewise, ADR-0012 keeps SeaweedFS as Pilot upload storage and does
not make archived MinIO OSS the default for a new immutable-archive deployment.

Implemented foundation: process liveness is separate from schema-aware readiness; readiness uses a
bounded real pool lease and requires the packaged sole Alembic head. Compose, APISIX and host startup
gate downstream processes/traffic on readiness. API and worker pool size, overflow and lease timeout
are Settings-backed with the previous effective defaults preserved. This proves local startup and
budget visibility, not multi-replica HA or a target `max_connections` value.

- API: multiple replicas, independent liveness/readiness, explicit pool budget per replica; introduce
  PgBouncer only after transaction-local RLS context leakage tests. The fail-closed probe and unit
  contract exist, but no PgBouncer deployment or live pass does.
- PostgreSQL: HA topology, PITR/WAL archive, isolated restore drill, partition/autovacuum plans and
  measured RPO <= 5 minutes/RTO <= 60 minutes.
- Objects: replicated, encrypted S3-compatible target with lifecycle, checksum, Object Lock where
  required and restore evidence; local single-node SeaweedFS is not the production topology.
- Delivery: retain Valkey + PostgreSQL outbox until retention/multi-consumer throughput requires a
  durable event log. Kafka/Pulsar does not replace canonical outbox/inbox semantics.
- Airflow: LocalExecutor remains valid for a small single machine; use a remote/container executor
  for multi-machine or large batch after operational-cost review.
- Signals: use OTel Collector as the vendor-neutral boundary and deploy the approved Prometheus,
  Alertmanager, Grafana, Tempo and Loki roles or enterprise exporter adapters with request/trace/job
  correlation; include queue/outbox lag, DB pool/locks, DataHub bulkhead/circuit/latency, cache hit/eviction, projection lag,
  denial rates and later LLM latency/tokens/cost/citation/refusal metrics.

The current Prometheus endpoint now exports bounded configured/current API DB-pool gauges. Database
lock/wait metrics, multi-replica aggregation, exporters, dashboards, alerts and the OTel pipeline
remain target-deployment gates.

## 10. Ordered execution backlog

1. Obtain signed capacity, classification/Chat and retention decisions; record reference hardware and
   target DataHub/OIDC/S3 versions.
2. Run migration on an empty copy and a production-sized synthetic copy; capture the search-plan
   matrix and index write/storage cost.
3. Extend the local membership/deny/scope revocation probe to two identities, classification,
   policy-version and open Chat/stream sessions under load; add target DataHub fault, worker
   kill/reclaim and 60-minute load/soak automation. Cache/API DataHub metrics are exposed, while
   worker/sync/Valkey metrics remain.
4. Implement and contract-test incremental DataHub change-watermark ingestion, retaining nightly full
   reconcile as drift verification/recovery.
5. Add the provider-neutral archive export/conformance worker around the implemented append-only
   capability and receipt evidence plus policy, Legal Hold and Maker-Checker aggregates, then add a
   separate one-time execution claim. Provision monthly
   partitions table-family by table-family only after approved volume/legal inputs, and keep all
   automatic deletion/detach/drop disabled until verified receipts and restore evidence exist.
6. Apply the P1 decision gate. If it fails, extract search indexing first through the outbox port.
7. Wire the isolated assistant contract only after durable dispatch and pre/post-call authorization
   revalidation exist, then expand the checked-in initial attack corpus into the full
   ABAC/prompt-injection/tool-abuse evaluation gate before enabling any external model.
8. Complete HA/PITR/object recovery, browser E2E, enterprise OIDC/Airflow auth, signed images/SBOM and
   accountable production acceptance.

## 11. Decisions required from accountable owners

- approve or replace every capacity/stress number and name the reference host;
- approve incremental/full sync lag, permission-revocation SLA and emergency kill-switch behavior;
- approve the four-class search/Chat/provider matrix and cross-border/retention restrictions;
- approve audit/Chat/event online and WORM retention, legal hold and deletion authority;
- supply target DataHub version/capabilities, enterprise IdP claims, S3 implementation and deployment
  topology so open contract/recovery gates can produce real evidence.
