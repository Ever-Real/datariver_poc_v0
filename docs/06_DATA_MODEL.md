# Data and table specification

The SQLAlchemy metadata and generated `backend/alembic/versions/0001_initial_schema.py` are authoritative for implemented DDL. This document separates implemented tables from target/backlog tables.

## Standards

- Application-generated UUIDs (normally UUIDv7) and UTC `TIMESTAMPTZ`.
- Every protected row has `workspace_id`; mutable aggregates have integer `version`.
- PostgreSQL RLS is enabled and forced on every workspace table. API sets `app.workspace_id` and `app.subject_id` per transaction. Relay, upload and governance BYPASSRLS identities are separate and receive only the tables needed by their background responsibility.
- Every parent/child relationship between tenant tables carries `workspace_id` in a composite foreign key; application filtering is not the only tenant-integrity guard.
- Security selectors such as classification/system/domain/owner are typed columns. JSONB stores non-security documents/extensions.
- Passwords/tokens never have application columns; connections use mounted secret references.
- Outbox, approvals, transitions, decisions, releases and citations are append-only to ordinary application roles.

## Implemented schemas and tables

### Platform, identity and authorization

| Table | Key columns and constraints | Purpose |
|---|---|---|
| `platform.workspaces` | `id`, `slug UQ`, `name`, `status`, `settings`, `version`, timestamps | tenant boundary |
| `iam.subjects` | `id`, `issuer + external_subject UQ`, `display_name`, `active`, timestamps | external IdP mapping; no credential |
| `iam.workspace_memberships` | PK `workspace_id + subject_id`, `department_id`, `job_function`, `clearance`, `attributes`, `active`, `version` | versioned ABAC subject attributes/grants |
| `iam.admin_access_requests` | typed command/envelope, maker/target/checker, canonical hash, expiry/state/consume decision, `version`, timestamps | short-lived membership-access maker-checker aggregate; no arbitrary provider payload |
| `iam.admin_access_approvals` | request/actor, approve/reject, reason, policy decision, payload hash and request version | append-only independent checker evidence |
| `authz.resources` | `workspace_id + resource_type + resource_key UQ`, scope/classification/lifecycle columns, `attributes`, `version` | durable resource attribute registry |
| `authz.policy_decisions` | `id`, `workspace_id`, `subject_id`, `resource_id`, `action`, `effect`, reason/policy JSON, grouped `evaluation_context`, `request_id`, `decided_at` | immutable allow/deny/system-worker or bounded resource-set evidence |

The active baseline policy is code-versioned (`builtin-abac-v2`); database-authored policy/version/binding tables are backlog for the future OPA adapter. Version 2 records typed authentication assurance and rejects non-WebAuthn high-risk execution.

### Catalog projection

| Table | Key columns and constraints | Purpose |
|---|---|---|
| `catalog.assets_projection` | `id`, `workspace_id + urn_hash UQ`, external identity/scope/classification/lifecycle, stored `search_vector`, source version/owner, `last_seen_sync_id`, observed/deleted times | authorized search/base-detail projection; DataHub remains canonical |
| `catalog.sync_runs` | PK workspace/sync, state/next offset/start/heartbeat/completion | single-writer ordered full reconciliation and stale-run recovery |
| `catalog.projection_watermarks` | `workspace_id PK/FK`, non-negative `projection_version BIGINT` | transactional local read-model generation used for cache invalidation |

Projection page idempotency is recorded in `integration.idempotency_keys`. Every committed page
advances the workspace projection version exactly once in the same transaction; replay, rejection
and rollback do not. Final-page reconciliation tombstones missing `DATAHUB` rows and never
seed-owned rows. `sync_runs.state` records reconciliation completeness, while the version records
only a committed local generation. Active rows have a workspace/scope/order partial index, GIN
full-text index and `pg_trgm` name index. Relationship/facet projections and a true incremental
DataHub source cursor remain backlog.

### Governance

| Table | Key columns and constraints | Purpose |
|---|---|---|
| `governance.change_requests` | `id`, `workspace_id + number UQ`, type/title/description/state/requester/classification, `version`, timestamps | change aggregate/state machine |
| `governance.change_request_items` | `id`, `change_request_id + ordinal UQ`, `target_type`, `target_ref`, `aspect_name`, `operation`, before/after hashes, `after_document` | ordered typed DataHub aspects |
| `governance.approvals` | `id`, `change_request_id + stage + actor_id UQ`, decision/reason/actor/policy/time | append-only actor-separated decisions |
| `governance.state_transitions` | `id`, request, from/to, actor, reason, policy decision, occurrence | append-only state history |

### Integration, jobs and objects

| Table | Key columns and constraints | Purpose |
|---|---|---|
| `integration.jobs` | `id`, `job_type + causation_id UQ`, workspace/state/requester/progress/result, `lease_until`, `attempts`, `last_error_code`, `version`, timestamps | durable external-side-effect job |
| `integration.job_attempts` | `id`, `job_id + attempt_no UQ`, worker/state/error/external hash/start/finish | worker attempt evidence |
| `integration.outbox_events` | event PK, workspace/aggregate/type/schema/payload/time, publish/dead-letter/lease/attempt/error | transactional event recovery source and isolated poison-event evidence; relay deletion is revoked |
| `integration.inbox_messages` | PK `consumer + event_id`, workspace/received/completed/result hash | consumer deduplication; relay deletion is revoked |
| `integration.idempotency_keys` | PK `workspace + operation + key_hash`, request hash/result/expiry | HTTP/command replay control |
| `integration.object_manifests` | `id`, `bucket + object_key UQ`, declared/actual size-MIME-SHA, multipart/parts, state/classification/owner, completion/validation attempts, lease/error/summary, expiry/retention, `version`, timestamps | quarantine-to-accepted lifecycle |
| `integration.seed_runs` | `id`, `workspace + namespace + pack_version UQ`, content hash/state/counts/apply/remove time | optional pack ownership/audit |

### Knowledge graph

| Table | Key columns and constraints | Purpose |
|---|---|---|
| `knowledge.graphs` | `id`, `workspace + slug UQ`, name/type/status/classification/active release, `version`, timestamps | graph aggregate and active pointer |
| `knowledge.ontology_versions` | `id`, graph/version/schema/checksum/status, timestamps | typed ontology versions |
| `knowledge.changesets` | `id`, graph/base release/ontology/title/state/author/reviewer/published release, `version`, timestamps | incremental author/review/publish aggregate |
| `knowledge.change_operations` | `id`, `changeset_id + sequence UQ`, operation/kind/stable ID/document/provenance/confidence | ordered typed node/edge edits |
| `knowledge.validation_results` | `id`, changeset/validator/version/severity/code/location/message/time | persisted submission validation evidence |
| `knowledge.releases` | `id`, `graph_id + release_no UQ`, ontology/content hash/counts/publisher/time | immutable release manifest |
| `knowledge.release_nodes` | composite release/entity identity, type/properties/classification/provenance | immutable assertion snapshot |
| `knowledge.release_edges` | composite release/edge identity, endpoints/type/properties/classification/provenance | immutable relationship snapshot |
| `knowledge.projection_deployments` | `id`, release/adapter/target/state/hash/counts/timestamps | optional projection deployment evidence (DDL present) |

The API supports both complete snapshot publication and changeset author/submit/independent-review/publish. Automated source extraction and projection deployment workers remain extension work.

### API sharing

| Table | Key columns and constraints | Purpose |
|---|---|---|
| `sharing.api_products` | workspace/slug UQ, graph/classification/owner/state/current version, optimistic version | stable managed product identity |
| `sharing.api_product_versions` | workspace/product/version UQ, graph/release composite FK, surface/contract/bounds/state/publisher | immutable release-pinned contract version |
| `sharing.consumer_grants` | product version/client UQ, scopes/classification/RPM/month quota/validity/state/revocation, version | credential-reference-only consumer entitlement |
| `sharing.api_invocations` | grant/idempotency key UQ, scope/request/time/units | immutable usage and quota ledger |

### Assistant

| Table | Key columns and constraints | Purpose |
|---|---|---|
| `assistant.chat_sessions` | `id`, workspace/owner/title/scope/retention, `version`, timestamps | owner-scoped session |
| `assistant.chat_messages` | `id`, workspace/session/actor/content/created time | append-only messages |
| `assistant.assistant_runs` | `id`, workspace/session/request message/provider/model/template/policy/state/metrics/timestamps | answer execution audit |
| `assistant.evidence_citations` | `id`, workspace/run/chunk/resource, classification, typed system/domain/owner scope, type/locator/version, SHA-256 content hash, effective interval, extraction method, positive unique rank | append-only immutable authorized evidence snapshot |

## Constraints enforced outside DDL

- Domain code owns legal change/upload/graph transitions and optimistic-version checks.
- Confidential/restricted apply requires two distinct final approvers; requester final approval is denied.
- `APPLIED` requires aggregate expected/observed hash equality after DataHub re-read.
- Graph release publication validates ontology, endpoints, classification and non-empty provenance before insert.
- Object acceptance requires full streamed SHA-256/size equality and format policy before canonical bucket switch.
- Search and snapshot queries prefilter classification and scope before enrichment/serialization.
- Direct administrator membership access requires recent hardware WebAuthn. The optional password
  path applies only an approved typed request and rechecks maker/checker eligibility, target version
  and the two-human-security-administrator invariant under a workspace transaction lock.

## Backlog schema (not implemented)

Versioned authored policies/bindings, catalog relationships/facets, connection registry, governance
attachments/general audit export, graph sources/extraction runs, saved-query templates beyond the
built-in surfaces and embedding partitions remain target tables. Governed retention additionally
requires a policy aggregate with immutable approved versions, Legal Hold commands and append-only
history, typed maker-checker erasure requests/approvals/attempts, immutable archive exports and
verified receipts. These records remain PostgreSQL canonical state; object-store metadata is not a
policy, hold or deletion authority. They require an Alembic revision and updated
API/retention/security tests; their mention in PRD/architecture is not permission to create ad-hoc
columns.

`EVENT_RETENTION_DAYS` is a target online-retention input, not a deletion switch. Automatic event deletion remains disabled until immutable export has been written and read back from a verified Object-Lock store, Legal Hold precedence and Maker-Checker erasure approval are implemented, and a dedicated least-privilege retention worker is introduced.

## Retention and deletion

An approved database policy version distinguishes legal audit, Chat content, completed delivery
events, accepted data, quarantine and telemetry. Durations proposed for a particular installation,
including the 30-day/90-day/13-month/7-year profile, are operating inputs to that version and not
portable schema, migration or source defaults. Activating a policy version does not by itself enable
deletion.

Legal Hold is a versioned aggregate with typed place and governed release commands plus append-only
history, not a mutable object-manifest boolean. It takes precedence over ordinary expiry and blocks
explicit erasure, row pruning and partition detach/drop. A release-pending hold is treated as active.
The first partition implementation over-retains a whole partition when any applicable hold exists.

Object deletion follows canonical manifest/session state through a retryable typed erasure workflow.
The request binds workspace, target kind and UUID, target version, classification, policy version and
canonical payload hash. Destructive execution requires an independent checker, current policy and
authorization, one-time atomic consumption and a final hold/version check. Requests never carry raw
SQL, table names, object keys or provider operations. Immutable audit/release evidence is
pseudonymized where legally allowed rather than edited; a completion receipt preserves only the
minimum legally permitted evidence. Seed removal remains fixed namespace/run scoped and cannot match
non-seed resources.

Immutable archive storage is accessed through a port separate from the registration object store.
The canonical receipt records deterministic manifest hash, row/byte counts, SHA-256, object version,
retention mode and deadline, provider/configuration fingerprint and content/retention read-back time.
A product name or S3-compatible response is insufficient: versioning, Object Lock, compliance-mode
retention, checksum/version behavior and shortening/delete denial need target conformance evidence.
Missing, stale or mismatched evidence prevents a VERIFIED receipt.

Monthly partition schemas are not implemented. Their future primary and unique keys must include the
partition time, with foreign keys and late events designed explicitly, at least two future partitions
prepared and the default partition alerted. Automatic deletion and partition detach/drop remain
`DISABLED_NOT_READY` until approved policy, Legal Hold, maker-checker erasure, verified immutable
archive and restore evidence are all present.
