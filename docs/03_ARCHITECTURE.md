# Architecture definition

## Architectural style

The first production shape is a modular monolith with independent API, worker, outbox relay, and scheduler processes. Modules communicate through application ports and durable domain events, never by writing another module's tables. This is a deliberate precursor to MSA: extraction is possible without accepting distributed-system cost before boundaries and load are proven.

Code dependencies point inward:

```text
interfaces/http ─┐
workers/cli ─────┼─> application/use_cases ─> domain
infrastructure ──┘             │
                              └─> application/ports <─ infrastructure adapters
```

The domain imports no FastAPI, SQLAlchemy, Redis, DataHub, object-storage, graph, or LLM SDK. An architecture test enforces this rule.

## Runtime view

```mermaid
flowchart LR
    U["Browser / API consumer"] --> G["API gateway profile"]
    G --> A["DataRiver API"]
    A --> P["PostgreSQL canonical state"]
    A --> VC["External Redis cache"]
    A --> O["Upload-oriented S3-compatible storage"]
    A --> D["External DataHub read facade"]
    A --> C["Deterministic evidence Chat (current)"]
    A --> Z["ABAC policy decision"]
    P --> R["Outbox relay"]
    R --> VQ["External Redis job delivery"]
    VQ --> W["Integration / KG workers"]
    W --> D
    W --> O
    W --> GP["Rebuildable graph projection"]
    RW["Optional archive-only retention scheduler / worker"] --> P
    RW --> IA["Separate immutable archive port"]
    AF["Airflow scheduled and bulk workflows"] --> A
    A -. "future durable dispatch; not wired" .-> IW["Typed assistant inference worker contract (disabled first)"]
    IW -. "future approved adapter" .-> L["Approved inference provider"]
    A -. "reviewed OTLP instrumentation" .-> OT["Optional OpenTelemetry Collector -> Prometheus/Grafana/Tempo/Loki"]
    W -. "reviewed OTLP instrumentation" .-> OT
```

Only the gateway/UI ports are public. PostgreSQL, Redis, object storage, OPA, DataHub credentials,
graph protocols and telemetry backends stay on private or explicitly controlled connector networks.
The base Compose owns no Redis, MinIO or SeaweedFS process or data volume.

The checked-in Compose and hybrid host-development views are Single-node Pilot topologies. Multiple
processes on the same host improve process recovery but do not establish HA. ADR-0013 requires at
least three independent nodes plus off-host distributed storage and accepted failure drills before
an environment may claim HA.

## Bounded contexts

| Context | Responsibility | Canonical data |
|---|---|---|
| Platform & Identity | workspaces, external IdP-subject mapping and normalized Role assignment evidence | workspace, subject reference, membership, Role assignment/event |
| Authorization | ABAC resources, Role-version Policy Book rules, policies, bindings and decision evidence | Role data rule, policy and decision log |
| Catalog Facade | authorized index plus DataHub search/detail/lineage projection and snapshot-bound managed export | projection/cursor/export receipt; applied metadata remains in DataHub |
| Governance | registration and change-request aggregate/state machine | requests, approvals, transitions, audit |
| Integration | connections, job intents, outbox/inbox, retry/DLQ/reconcile | durable job and delivery state |
| Knowledge Studio | ontology, proposals, changesets, validation and releases | immutable graph releases/provenance |
| Assistant | sessions, messages, runs and authorized evidence | chat audit/evidence metadata |
| Sharing | release-pinned API products, subject/client-bound grants, exact replay bodies and quota evidence | product/version/grant plus immutable invocation/result/month aggregate |
| Retention & Erasure | approved retention versions, Legal Hold, erasure Maker-Checker review and optional archive-only execution; destructive execution remains absent | policy/hold/erasure aggregates, fenced execution claims, immutable receipts and append-only evidence in PostgreSQL |
| Operations | capability health and operator actions | connection/job snapshots, not raw telemetry |

The API gateway is a deployment boundary, not an authorization context. It validates identity and coarse quotas; each use case resolves resource attributes and performs ABAC again.

## Canonical ownership rules

- DataHub owns metadata after successful application. DataRiver stores a minimal authorized projection and a monotonic local projection version; a true DataHub source watermark remains an ingestion contract.
- DataRiver PostgreSQL owns intent, approvals, job state, graph release manifests, policy and audit.
- Graph projection data is disposable. Publishing first creates an immutable PostgreSQL/object snapshot, loads a shadow projection, verifies it, then switches the active pointer.
- Redis owns nothing canonical. Cache loss changes latency, not correctness. Delivery-stream loss is recovered from the PostgreSQL outbox.
- Airflow task status is operational evidence, never the business job status.
- PostgreSQL, not an object provider, owns retention versions, Legal Hold state, erasure authority
  and archive verification receipts. Archive objects are evidence bytes referenced by those
  receipts; provider metadata does not activate deletion.
- External identifiers such as DataHub URNs map to internal UUIDs and are never primary keys.
- Policy Book Role rules add deny-capable No/Partial/Full, residency and purpose checks. They never
  replace membership ABAC or RLS; missing rules and unavailable partial-treatment adapters deny.

### Atomic Sharing execution boundary

The current Snapshot, Neighbors and deterministic local Chat API-product surfaces execute inside one
bounded PostgreSQL transaction. The application locks product → current version → exact
`SUBJECT_CLIENT_V2` grant, rechecks the active service Subject, issuer/client, ABAC fingerprint,
governed release lineage and active retention rule, then either returns the exact stored result or
builds one local bounded response. One security-definer completion capability inserts the immutable
ledger, classified result and UTC-month aggregate together. Any failure rolls back all three.

Redis, Neo4j, DataHub, Airflow, object storage and an external LLM are not participants in this unit
of work. A provider-backed Sharing surface requires a durable reserve/execute/settle worker and
cannot extend the database lock across a network call. Result routes are private/no-store; expired
or policy-drifted bodies are not disclosed. PostgreSQL remains canonical for quota and evidence,
while physical retention purge remains governed and disabled.

## Retention, Legal Hold and immutable archive boundary

The existing S3 port is upload-oriented: it supports multipart registration, quarantine cleanup and
accepted-object promotion. It is not a WORM boundary. The optional `ImmutableArchiveStore` is a separate
application port with a separate private endpoint, bucket and writer credential and no delete or
retention-bypass operation. The API, relay and upload workers do not receive that credential.

```text
approved policy version + eligible immutable audit range
→ active/release-pending Legal Hold check
→ deterministic export manifest and SHA-256
→ exact capability attestation committed under the live lease
→ conditional immutable archive create with attestation UUID and object version
→ full content and retention/Object-Lock read-back
→ verified PostgreSQL receipt
→ terminal archive-only evidence state
→ remain retained; destructive eligibility is a future, separately approved control plane
```

Provider names do not establish capability. The target provider must prove versioning, Object Lock,
compliance retention, checksum/version behavior, read-back and rejection of shortening/deletion.
Missing, expired or mismatched proof stops the workflow. Policy durations are approved runtime data,
not source defaults; a duration or expired timestamp never acts as a deletion switch.

Legal Hold always wins over expiry. A UI toggle issues typed place/release commands and immutable
history rather than editing a boolean. Explicit sensitive-data erasure is separate from automatic
expiry and binds maker, independent checker, canonical target version/owner/classification, active
policy ID/hash and a canonical payload hash. The archive-only scheduler may consume an exact
APPROVED Chat-session request once into a fenced command, revalidate current human
eligibility/hold/target/policy state and attach a verified receipt. It cannot delete, purge or detach
anything. An expired write lease first performs bounded read-only reconciliation against the exact
attestation UUID and provider write time; it never runs a probe or PutObject. A future destructive
executor requires a new ADR, separate approval and final
authorization/hold/version/archive checks. Raw bucket keys, table names or provider operations are
never client-supplied erasure commands.

Automatic deletion and monthly-partition detach/drop are currently `DISABLED_NOT_READY`. They remain
so until approved policy/hold/erasure workflows, verified archive receipts, target
restore/conformance evidence and a separately approved destructive design are accepted. A partition with
any applicable active hold is conservatively retained in full.

## Change application sequence

```mermaid
sequenceDiagram
    participant UI
    participant API
    participant DB as PostgreSQL
    participant Relay
    participant Worker
    participant DH as DataHub
    UI->>API: approve request (Idempotency-Key)
    API->>DB: transition APPLY_QUEUED + outbox, one transaction
    API-->>UI: 202 + job URI
    Relay->>DB: lease unpublished outbox
    Relay->>Worker: publish event id only
    Worker->>DB: inbox dedupe + APPLYING
    Worker->>DH: typed MCP/aspect update
    Worker->>DH: re-read affected aspect
    Worker->>DB: compare hash, record attempt
    alt reconciled
        Worker->>DB: APPLIED + audit + projection event
    else mismatch or dependency failure
        Worker->>DB: APPLY_FAILED/retryable + evidence
    end
```

The worker may receive a message more than once. Inbox uniqueness and operation-specific idempotency make the business effect repeat-safe.

Catalog export is a separate disabled-first worker boundary. The API records an exact normalized
request plus permission, classification-policy, policy-code, CSV-safety and projection generations;
the worker does not call DataHub and cannot export RESTRICTED rows. It streams the local projection
into an attempt-unique private object, reconciles its receipt, and publishes completion only while
the original security/source snapshot and lease remain current. API and export worker do not share
DB or S3 credentials when the feature is enabled.

## Knowledge-graph lifecycle

```text
source snapshot
→ parsing/extraction run
→ entity resolution
→ proposal operations
→ draft changeset
→ ontology/provenance/ABAC validation
→ independent review
→ immutable release
→ shadow projection
→ count/hash/golden-query verification
→ active pointer switch
```

Graph types are `CATALOG_MIRROR`, `CURATED_KNOWLEDGE`, and `ANALYTIC_PRODUCT`. Ontology versions and content releases are independent. Every assertion includes source locator, extraction/model/prompt version where applicable, confidence, effective time, and security attributes.

## Search and Chat authorization

Filtering a DataHub page after retrieval leaks counts, pagination, and asset existence. A local `catalog.assets_projection` therefore stores searchable/base-detail metadata and security attributes. The API calculates the permitted asset set before DataHub enrichment. Literal search is normalized/escaped and backed by FTS/trigram/active-scope indexes. Search cache keys bind workspace, permission scope, policy version and projection watermark. Chat uses the same permitted set before retrieval; candidate decisions are grouped into request-level audit evidence, and citations include version and source locator.

ADR-0020 adds one deliberately narrow remediation view: after a durable human-security-administrator
decision, the local catalog reader may enumerate non-deleted quarantined projections in that same
workspace so those real DataHub assets can be classified. The decision bit is part of the cache and
cursor security scope. It never reaches export, Chat, attachment, provider, mutation or
cross-workspace paths, except for the existing typed DataHub metadata enrichment of its catalog
detail, and does not make DataHub a canonical authorization authority.

The optional DataHub lineage frame is not a generic external-URL feature. It is disabled by default;
after a local authorized asset lookup, the API alone constructs the configured exact-origin lineage
URL. CSP permits only that origin, the browser sends an opaque asset ID rather than a URN and the
frame is sandboxed with no referrer. DataHub's own SSO, authorization and framing headers remain a
separate external acceptance gate.

After retrieval/composition, Chat opens a separate final persistence transaction, applies workspace
and owner RLS context, serializes against retention-policy administration and binds the session to
the exact ACTIVE retention ID/hash and database-time deadline. This transaction is the only place
that writes Chat content. Missing policy, policy supersession, expiry or legacy-unbound evidence
fails closed; it does not invent a duration or authorize deletion.

The active classification-access snapshot is a versioned, workspace-scoped four-class policy. Its
rules and authorization generation bind cache/evaluation state; RESTRICTED Search additionally
requires an exact subject/resource, system or domain grant bound to the active policy ID and hash.
Missing, malformed, expired or revoked policy/provider/grant state falls back to the static
fail-closed floor. RESTRICTED Chat is always denied.

## Assistant inference boundary

Current Chat remains an in-process deterministic evidence composer and makes no model call. The
separate assistant-inference source boundary is only a typed, disabled-first worker contract. Its
versioned package binds requested/selected provider identity and region, policy, attestations,
immutable URN-addressed evidence and a monthly workspace/user token-accounting decision. Internal
routes are monitor-only; an external route requires a durable hard-limit reservation. An exhausted
external budget can preselect an already approved internal route that passes the same classification,
jurisdiction and attestation eligibility predicates. The external denial and internal monitor-only
observation remain separate; the worker still executes one route and never falls back from an
exception.

Provider citations are passed through a separate server-side grounding-verifier port. Completion
requires exact package/route IDs, answer hash, cited chunk order and an evidence-bundle hash over
canonical source URN, source version and content hash. Metric, non-zero threshold and evaluator
identity come from an immutable grounding-policy snapshot. A structurally valid post-call draft
retains its usage metrics even when later refused; otherwise the result is
`보안 규정 및 근거 데이터 부족으로 답변할 수 없습니다`. Neither input nor output has SQL,
Cypher, arbitrary HTTP, tool or mutation fields. There is no token ledger, configured provider or
grounding adapter, endpoint/secret, API-to-worker dispatch, durable inference job, streaming
transport or deployed worker process in this baseline. Dotted inference edges in the runtime view
are future seams, not current network calls.

## External Redis topology

| Capability | Persistence | Eviction | Content |
|---|---|---|---|
| `REDIS_CACHE_URL` | none required | bounded evicting policy such as `allkeys-lfu` | bounded TTL search/detail/policy-derived results |
| `REDIS_DELIVERY_URL` | deployment-reviewed persistence and recovery | `noeviction` | job IDs and delivery metadata only |

The two URLs must identify distinct endpoints or databases and use distinct least-privilege
credentials. Cache keys include workspace, permission-scope hash, policy version, request parameters
and the local projection version. Tokens, credentials, presigned URLs, full uploads, canonical job
state and confidential prompts are prohibited. The checked-in client uses the Redis protocol; legacy
`VALKEY_*` environment names are accepted only as a migration alias.

The browser treats its selected Workspace as a tenant/RLS context, not an authorization fact. The
safe UUID selection is retained in the same-origin URL so an OIDC round-trip, reload or new tab can
restore the requested page; it is still sent on each typed request and the server always re-resolves
membership, RLS and ABAC. The OIDC user/token object plus verified `/auth/me` profile and roles stay
in React memory. Browser persistence is limited to the short-lived PKCE redirect transaction state,
which contains only a versioned intent and validated same-origin return path; no client-side role or
administrator flag exists.

That memory boundary is generation- and epoch-fenced. Only the newest `/auth/me` response whose
subject matches the OIDC `sub` may publish an identity snapshot. An opaque `securityEpoch` changes
on subject, provider-session or security-bearing profile transitions and is captured with Workspace
by each request/download; drift discards late bodies and prevents `401` retry across contexts. A
separate accepted-hydration revision suspends and rechecks Admin after ordinary same-session
renewal without recreating the API client or unrelated feature state. An unchanged returned Admin
context resumes the mounted subtree and preserves its draft state; an epoch or Admin-context
fingerprint change, mismatch or denial purges it. Neither counter is persisted, sent as authority or
trusted by the backend.

The browser-delivery edge has one canonical five-header policy: CSP, nosniff, no-referrer,
frame denial and a restricted Permissions Policy. Nginx `1.30.3` recursively merges those
server-level `always` rules into every location, including locations with their own cache header.
The `/api/` proxy removes only upstream copies of those five fields before emitting the canonical
edge values; application cache, authentication, retry, ETag, Vary, download and trace headers
remain upstream-owned. HSTS is not emitted by the inner HTTP container and remains owned by the
real TLS terminator.

The optional Keycloak identity-administration adapter is a narrow anti-corruption boundary, not a
generic IdP proxy. It owns only fixed user lookup/create, temporary-password and enable operations
using a dedicated `manage-users` service account. A user remains disabled while the canonical
PostgreSQL subject/membership, idempotency record and outbox event commit through the fixed
`iam.provision_workspace_identity` function. Provider enablement occurs last and is safe to retry.
Self-service password change uses a fixed provider-side application-initiated action and returns to
the original DataRiver route. The browser UI exposes neither the provider product name nor an admin
URL, and the replacement password never crosses the DataRiver API.

## Degradation model

| Dependency failure | Expected behavior |
|---|---|
| DataHub | concurrency bulkhead/circuit breaker; authorized local base detail or explicitly bounded stale enrichment, otherwise 503; queued changes retained and never marked applied |
| Redis cache | direct authorized DB/DataHub path; higher latency |
| Redis delivery | outbox accumulates and relay retries; writes remain durable |
| graph projection | catalog remains available; graph Chat/analytics clearly degraded |
| future inference provider/worker | deterministic evidence Chat remains; the disabled-first contract refuses with `검증 불가`; no provider call or graph mutation |
| Airflow | scheduled/bulk jobs delayed; synchronous core unaffected |
| object storage | upload/download unavailable; metadata/workflow state retained |
| immutable archive capability | export, explicit erasure that requires archive, automatic deletion and partition drop stop; ordinary authorized reads remain available |
| telemetry backend/collector | canonical workflows continue; bounded telemetry may buffer or drop according to deployment policy without exporting protected payloads |
| policy service | sensitive reads and all writes fail closed; public health remains available |

## Service extraction criteria

A context becomes a separate service only when it has an independent owner, demonstrably different scale/availability need, stable versioned events, no cross-context database writes, and an operational budget for deployment/on-call/data migration. Likely first candidates are Integration Worker, Assistant inference, and graph projection—not identity or governance aggregates.
