# Data and table specification

The SQLAlchemy metadata and generated `backend/alembic/versions/0001_initial_schema.py` are authoritative for implemented DDL. This document separates implemented tables from target/backlog tables.

## Standards

- Application-generated UUIDs (normally UUIDv7) and UTC `TIMESTAMPTZ`.
- Every protected row has `workspace_id`; mutable aggregates have integer `version`.
- PostgreSQL RLS is enabled and forced on every workspace table. API sets `app.workspace_id` and `app.subject_id` per transaction. Relay, upload and governance BYPASSRLS identities are separate and receive only the tables needed by their background responsibility.
- Every parent/child relationship between tenant tables carries `workspace_id` in a composite foreign key; application filtering is not the only tenant-integrity guard.
- Security selectors such as classification/system/domain/owner are typed columns. JSONB stores non-security documents/extensions.
- Passwords and tokens never have application columns. Development System Settings store only
  validated non-secret YAML and `file:/run/secrets/<name>` reference names; exact revision,
  TEST and activation evidence is workspace-scoped and disabled outside development.
- Outbox, approvals, transitions, decisions, releases and citations are append-only to ordinary application roles.

## Implemented schemas and tables

### Platform, identity and authorization

| Table | Key columns and constraints | Purpose |
|---|---|---|
| `platform.workspaces` | `id`, `slug UQ`, `name`, `status`, `settings`, `version`, timestamps | tenant boundary |
| `platform.data_systems` | workspace-scoped code/name UQ, description, active flag, version/timestamps | canonical business-system master; not a DataHub provider connection |
| `platform.system_schema_scopes` | workspace/platform/database/schema UQ, composite system FK, active flag | explicit DataHub projection scope to business-system assignment |
| `platform.system_assignees` | system/subject/responsibility UQ, `DEVELOPER` or `DATA_STEWARD`, priority `1..999`, active flag | accountable human system assignments; never browser-derived |
| `platform.external_service_profiles` | workspace/service-key UQ, current YAML/version, nullable activated version, updater and bounded service vocabulary | development-only current draft and pointer to the revision selected for next startup; production runtime settings remain deployment/provider controlled |
| `platform.external_service_profile_versions` | workspace/profile/configuration-version UQ, SHA-256 document hash, immutable YAML/endpoint, creator, TEST status/scope/latency/actor/time and activation actor/time | exact SAVE → TEST → ACTIVATE evidence; RLS-scoped reads are granted to each consuming process's existing least-privilege DB role |
| `iam.subjects` | `id`, `issuer + external_subject UQ`, `display_name`, IdP email, ordinary last-login timestamp/IP, `active`, timestamps | external IdP mapping and profile audit; no credential or password |
| `iam.workspace_memberships` | PK `workspace_id + subject_id`, `department_id`, `job_function`, `clearance`, `attributes`, `active`, nullable `access_expires_at`, `version` | versioned ABAC attributes/grants; human expiry is authorization-bearing, service-account expiry is operator-managed `NULL`, and the optional default marker only chooses among active unexpired memberships |
| `iam.membership_renewal_requests` | workspace/target pending partial UQ, observed/requested expiries, requester/checker, reason/decision/policy/time and optimistic version | self-requested six-calendar-month extension with independent global-Admin decision and no self approval |
| `iam.access_roles` | workspace/key UQ, name/description, clearance, typed group/action/System/Domain scope documents, active flag, updater/version | reusable administrator-managed RBAC template; assignment materializes the existing membership ABAC document and the role marker is not independent authority |
| `iam.admin_access_requests` | typed command/envelope, maker/target/checker, canonical hash, expiry/state/consume decision, `version`, timestamps | short-lived membership-access maker-checker aggregate; no arbitrary provider payload |
| `iam.admin_access_approvals` | request/actor, approve/reject, reason, policy decision, payload hash and request version | append-only independent checker evidence |

`iam.resolve_default_workspace(issuer, external_subject)` is a narrowly scoped database function,
not an IAM list API.  It may return only one active Workspace UUID for the already verified OIDC
subject during `/auth/me` hydration, prefers the optional membership default marker and otherwise
uses deterministic active-Workspace ordering.  It is executable by the application role but returns
no attributes, memberships, roles or cross-workspace data; normal IAM reads remain RLS-bound.
| `authz.resources` | `workspace_id + resource_type + resource_key UQ`, scope/classification/lifecycle columns, `attributes`, `version` | durable resource attribute registry |
| `authz.policy_decisions` | `id`, `workspace_id`, `subject_id`, `resource_id`, `action`, `effect`, reason/policy JSON, grouped `evaluation_context`, `request_id`, `decided_at` | immutable allow/deny/system-worker or bounded resource-set evidence |
| `authz.classification_access_policy_versions` | workspace/policy number UQ, required jurisdiction, grant maximum, payload hash, maker/checker/supersede state and optimistic version | independently approved four-class Search/Chat policy |
| `authz.classification_access_policy_rules` | workspace/policy/classification UQ, policy hash, typed Search/Chat modes and optional immutable provider-profile version FK | exactly one immutable rule for each of the four classifications |
| `authz.restricted_search_grants` | active policy ID/hash, subject, typed resource/system/domain scope, validity, payload hash, maker/checker/revocation and optimistic version | explicit policy-bound RESTRICTED Search entitlement |
| `authz.restricted_search_grant_events` | grant/version UQ, action/actor/reason/policy decision/time/payload hash | append-only grant history |
| `authz.classification_access_generations` | workspace PK, monotonic generation and update time | transactional authorization/cache invalidation generation |

The general ABAC decision engine remains code-versioned (`builtin-abac-v2`); generic database-authored
OPA policy/binding tables remain backlog. The narrower classification-access policy above is
implemented operating data and is evaluated together with ordinary ABAC, never as its replacement.
Missing or inconsistent active state falls back to the portable static floor.

### Catalog projection

| Table | Key columns and constraints | Purpose |
|---|---|---|
| `catalog.assets_projection` | `id`, `workspace_id + urn_hash UQ`, external identity/scope/classification/lifecycle, nullable typed-container `database_name`/`schema_name`, bounded provider display summary (`owner_ref`, `domain_ref`, tag/term arrays, projected `column_names` and source-created time), stored `search_vector`, source version/owner, `last_seen_sync_id`, observed/deleted times | authorized search/tree/base-detail projection; projected column paths only power bounded discovery and DataHub remains canonical for detailed column metadata |
| `catalog.sync_runs` | PK workspace/sync, state/next offset/start/heartbeat/completion | single-writer ordered full reconciliation and stale-run recovery |
| `catalog.projection_watermarks` | `workspace_id PK/FK`, non-negative `projection_version BIGINT` | transactional local read-model generation used for cache invalidation |
| `catalog.export_requests` | workspace/requester/job composite FKs, canonical request and security/source hashes, non-RESTRICTED classification ceiling, private artifact receipt, format-safety version and access deadline; owner-select plus forced workspace RLS | owner-scoped managed CSV/XLSX intent and verified artifact metadata; object content remains private storage state |

Projection page idempotency is recorded in `integration.idempotency_keys`. Every committed page
advances the workspace projection version exactly once in the same transaction; replay, rejection
and rollback do not. Final-page reconciliation tombstones missing `DATAHUB` rows and never
seed-owned rows. `sync_runs.state` records reconciliation completeness, while the version records
only a committed local generation. Active rows have a workspace/scope/order partial index, GIN
full-text index, `pg_trgm` name index, a lower-name prefix index for two-character autocomplete and
a workspace/platform/database/schema/name partial index for lazy tree branches. Database/schema
values are nullable projections of typed DataHub `Database`/`Schema` browse containers; an absent
typed container stays absent and is never reconstructed from a URN. Facets and tree branches are
derived from the same authorization-prefiltered projection and cached by security and projection
generation; a separate facet projection and a true incremental DataHub source cursor remain backlog.
Alembic `0019` adds only the bounded, non-authoritative display summary needed by dense catalog
results; tags and glossary terms are JSONB arrays constrained to their array shape. It is never an
authorization selector, provider payload or browser mutation surface. Detail continues to read the
typed DataHub enrichment through the server anti-corruption layer.

### Governance

| Table | Key columns and constraints | Purpose |
|---|---|---|
| `governance.change_requests` | `id`, `workspace_id + number UQ`, type/title/description/state/requester/classification, nullable requested due date/priority/urgency vocabulary, `version`, timestamps | change aggregate/state machine |
| `governance.change_request_items` | `id`, `change_request_id + ordinal UQ`, typed provider or intake target/aspect/operation, before/after hashes/document, nullable historical target binding and canonical `routing_system_id` | immutable executable item or typed multi-target intake evidence; every new item routes workflow authority through an active canonical System |
| `governance.registration_content_bindings` | candidate/hash UQ, change item UQ, request/item/creator composite workspace FKs, created time | append-only candidate-to-governed-item provenance; no ordinary update/delete grant |
| `governance.manual_metadata_submissions` | workspace/asset/requester FKs, per-workspace serial UQ, immutable typed table/field payload, private bucket/key UQ, CSV SHA-256/size/row count, state/attempt/lease/version/timestamps | independent MANUAL registration audit/CSV receipt; payload and receipt identity are immutable, while a leased Airflow-owned worker may advance controlled state after CSV and provider read-back verification |
| `governance.approvals` | `id`, `change_request_id + stage + actor_id UQ`, REVIEW/TEST/FINAL decision/reason/actor/policy/time and JSON authority snapshot | append-only decision plus immutable System Developer/Data Steward/global Admin authority evidence used by stage-completeness checks |
| `governance.state_transitions` | `id`, request, from/to, actor, reason, policy decision, occurrence | append-only state history |

### Integration, jobs and objects

| Table | Key columns and constraints | Purpose |
|---|---|---|
| `integration.jobs` | `id`, `job_type + causation_id UQ`, workspace/state/requester/progress/result, `lease_until`, `attempts`, `last_error_code`, `version`, timestamps | durable external-side-effect job |
| `integration.job_attempts` | `id`, `job_id + attempt_no UQ`, worker/state/error/external hash/start/finish | worker attempt evidence |
| `integration.outbox_events` | event PK, workspace/aggregate/type/schema/payload/time, publish/dead-letter/lease/attempt/error | transactional event recovery source and isolated poison-event evidence; relay deletion is revoked |
| `integration.inbox_messages` | PK `consumer + event_id`, workspace/received/completed/result hash | consumer deduplication; relay deletion is revoked |
| `integration.idempotency_keys` | PK `workspace + operation + key_hash`, request hash/result/expiry | HTTP/command replay control |
| `integration.object_manifests` | `id`, `workspace + id UQ`, `bucket + object_key UQ`, declared/actual size-MIME-SHA, explicit allowlisted content profile, multipart/parts, state/classification/owner, completion/validation attempts, lease/error/summary, expiry/retention, `version`, timestamps | quarantine-to-accepted lifecycle; filename/MIME never implies proposal capability |
| `integration.upload_preparation_jobs` | upload/requester composite FKs, exact source-evidence identity UQ, source configuration UQ, typed state, lease token/time, attempts/progress/error, optimistic version | durable typed preparation claim; execution role access is deliberately not granted by `0016` |
| `integration.upload_preparation_receipts` | exact job source-evidence/upload composite FKs and UQs, source/accepted SHA equality, locator hash, optional ETag/VersionId, parser/scanner/schema/config versions, counts/root/receipt hashes | append-only full-input preparation receipt |
| `integration.upload_registration_candidates` | receipt/ordinal UQ, receipt/asset UQ, local asset ID, evidence version, submitted platform/database/schema/table plus identity hash, typed description operation/value and candidate hash | append-only server-prepared candidate; submitted evidence remains distinct from the current catalog target; no URN, Aspect, classification, provider document or object coordinate |
| `integration.seed_runs` | `id`, `workspace + namespace + pack_version UQ`, content hash/state/counts/apply/remove time | optional pack ownership/audit |
| `integration.inference_provider_profile_versions` | workspace/profile key/version UQ, server route key, provider/model/deployment identities, kind, jurisdiction/region, classification ceiling, two bounded attestation snapshots, payload hash, maker/checker/revocation and optimistic version | immutable server-registered routing eligibility; no endpoint or credential |
| `integration.inference_provider_generations` | workspace PK, monotonic generation and update time | transactional provider-routing invalidation generation |

### Retention governance

| Table | Key columns and constraints | Purpose |
|---|---|---|
| `retention.policy_versions` | workspace/policy number UQ, typed duration fields, canonical payload hash, maker/checker decisions, state and optimistic version; one ACTIVE row per workspace | independently approved operating retention policy; activation never authorizes deletion by itself |
| `retention.legal_holds` | typed data class/scope, canonical payload hash, creator, governed release fields, blocking state and optimistic version | Legal Hold canonical state; every state except RELEASED blocks destructive eligibility |
| `retention.legal_hold_events` | hold/version UQ, typed action, actor/reason/policy decision/time and action hash | append-only placement and release history |
| `retention.erasure_requests` | typed canonical target snapshot, classification, policy ID/hash, maker/checker, bounded expiry, payload hash, terminal review state and optimistic version | independently reviewed erasure intent; APPROVED never grants an execution capability |
| `retention.erasure_request_events` | request/version UQ, typed action, actor/reason/policy decision/time and request payload hash | append-only creation and decision history |
| `retention.archive_capability_attestations` | configuration/encryption/runtime-principal fingerprints, probe contract/challenge, bucket, bounded observation window, seven verified controls, state/failure and canonical payload hash | append-only target conformance evidence; a provider label alone cannot create VERIFIED state |
| `retention.immutable_archive_receipts` | exact source range and manifest, active policy ID/hash, typed full-object checksum, full content/retention read-back, object version, capability/encryption/principal binding and canonical payload hash | append-only proof for a verified archive object version; never a deletion capability |

All seven tables use forced workspace RLS and composite membership/aggregate foreign keys. Retention
foreign keys do not cascade, the application role cannot delete these rows, and Legal Hold/erasure
events cannot be updated. The application role has read-only access to archive evidence; no API or
ordinary unit of work can create it. Archive export attempts, erasure execution claims/attempts and
destructive completion tables remain unimplemented.

### Knowledge graph

| Table | Key columns and constraints | Purpose |
|---|---|---|
| `knowledge.graphs` | `id`, `workspace + slug UQ`, name/type/status/classification/active release, `version`, timestamps | graph aggregate and active pointer |
| `knowledge.ontology_versions` | `id`, graph/version/schema/checksum/status, timestamps | typed ontology versions |
| `knowledge.changesets` | `id`, graph/base release/ontology/title/state/author/reviewer/published release, `version`, timestamps | incremental author/review/publish aggregate |
| `knowledge.change_operations` | `id`, `changeset_id + sequence UQ`, operation/kind/stable ID/document/provenance/confidence | ordered typed node/edge edits; model-proposed provenance includes verified excerpt/excerpt hash/page hash |
| `knowledge.validation_results` | `id`, changeset/validator/version/severity/code/location/message/time | persisted submission validation evidence |
| `knowledge.releases` | `id`, `graph_id + release_no UQ`, ontology/content hash/counts/publisher/time | immutable release manifest |
| `knowledge.release_nodes` | composite release/entity identity, type/properties/classification/provenance | immutable assertion snapshot |
| `knowledge.release_edges` | composite release/edge identity, endpoints/type/properties/classification/provenance | immutable relationship snapshot |
| `knowledge.projection_deployments` | `id`, graph/release/job, adapter/target/state/content and verification hashes/counts/verified time/error | Neo4j shadow read-back evidence; `SHADOW_VERIFIED` requires reconstructed canonical content-hash equality |
| `knowledge.source_snapshots` | graph/upload UQ, private object coordinate/version, PDF media/size/hash/classification/state/creator | immutable integrity-verified source binding; never an external URL |
| `knowledge.source_pages` | source/page PK, page content hash and parsed text | reviewer-visible page-aware grounding source |
| `knowledge.source_page_embeddings` | source/page/provider/model, dimension/vector and page hash | release-scoped semantic seed evidence for the exact parsed page |
| `knowledge.extraction_runs` | source/changeset, parser hash, embedding/extraction bindings, input/output hashes/state/error | reproducible typed extraction execution and activated configuration revision evidence |
| `knowledge.graphrag_audits` | graph/release/request UQ, actor, question hash, retrieved/cited IDs, model/prompt/tool and configuration source/version/hash, token counts | immutable citation-bounded inference audit without storing the raw question |

The API supports complete snapshot publication, changeset author/submit/independent-review/publish,
PDF source extraction into a DRAFT changeset, canonical Neo4j shadow verification and citation-bound
GraphRAG. PostgreSQL releases remain canonical; Neo4j can be deleted and rebuilt. The current Mac
developer extraction call is synchronous and bounded. A leased durable inference worker remains a
production promotion gate rather than an implemented production claim.

Model-authored evidence text is never canonical input. The server whitespace-normalizes each parsed
page into stable bounded evidence units, supplies only their opaque IDs to the model and resolves a
selected ID back to the server-owned excerpt/page/hash. Unknown IDs are rejected and edges whose
endpoints are absent from the same typed response are discarded before domain validation.

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
| `assistant.chat_sessions` | `id`, workspace/owner/title/scope, retention policy ID/hash/basis/deadline/binding version, `version`, timestamps; composite policy FK and immutable binding trigger | owner-scoped, active-policy-bound session; legacy/superseded/expired sessions are append-closed |
| `assistant.chat_messages` | `id`, workspace/session/actor/content/created time | append-only messages |
| `assistant.assistant_runs` | `id`, workspace/session/request message/provider/model/template/policy/state/metrics/timestamps | answer execution audit |
| `assistant.evidence_citations` | `id`, workspace/run/chunk/resource, classification, typed system/domain/owner scope, type/locator/version, SHA-256 content hash, effective interval, extraction method, positive unique rank | append-only immutable authorized evidence snapshot |

Alembic `0011` adds the classification policy/rule/generation, RESTRICTED grant/event and inference
profile/generation tables with forced workspace RLS, composite workspace foreign keys, immutable
rule/event/profile payloads and no application delete path. The assistant inference package/result
contract is source-only: it adds no durable inference job, provider endpoint/secret or execution table.
Alembic `0012` adds only the active lower-name prefix index used by the governed two-character
suggestion contract; no new source-of-truth or cross-workspace table is introduced.
Alembic `0013` adds nullable database/schema hierarchy projection columns and the active hierarchy
partial index. It changes no canonical ownership: DataHub remains the applied metadata source.
Alembic `0014` adds `catalog.export_requests`, owner-select and workspace RLS, immutable request and
security/source snapshot bindings, non-RESTRICTED classification ceiling, artifact-shape/hash
constraints and only the API grants needed to insert/read owner records and create jobs. It does not
provision an export DB role or S3 identity; runtime enablement remains a separate operator action.
Alembic `0015` adds nullable all-or-none governance target-binding evidence and its bounded lookup
index. It performs no historical backfill: existing unbound items cannot be presented as if current
projection values were their creation-time evidence. New domain creation requires a complete,
server-generated binding. The authorization fingerprint covers identity and scope attributes;
source version and observation time remain separate evidence. No foreign key points to the
rebuildable catalog projection.
Alembic `0016` adds the disabled-first typed BULK preparation foundation from ADR-0016: existing
manifests default to non-executable `FORMAT_ONLY_V1`, preparation jobs have lease/state constraints,
and completed receipts, candidates and candidate-to-change bindings are append-only to ordinary
roles. All relationships carry workspace, all new tables use forced RLS, and every new foreign key
uses `RESTRICT`. The manifest content profile is immutable after insert. Because the catalog projection
is rebuildable, candidate target IDs are historical evidence rather than physical foreign keys and
must be re-resolved under the same workspace before proposal creation. The existing BYPASSRLS upload
role receives no access to the new tables; a workspace/correlation-bound execution boundary remains
an activation prerequisite. The API now persists and reads authorized `upload_preparation_jobs`
through ordinary forced-RLS sessions after locking and verifying the exact accepted manifest,
immutable content profile, promoted-byte SHA-256 evidence and server configuration hash. It cannot
claim a lease, write a receipt/candidate or create candidate provenance. No parser worker or typed
proposal capability is enabled.

Alembic `0017` closes the submitted-identity evidence gap without rewriting history. Existing
candidate rows become `LEGACY_V1` with no fabricated hierarchy; new rows must be
`DATASET_DESCRIPTION_CANDIDATE_V2` and carry all four submitted hierarchy values plus their identity
hash. Parser/configuration and ordered-root contracts advance to V2, and a trigger rejects new legacy
rows plus every candidate update/delete. No new role grant is introduced. The read-only candidate
API accepts only READY receipt evidence, recomputes V2 identity/candidate invariants and resolves a
page through one current authorization-pruned ACTIVE DATASET lookup. It never reads object storage or
DataHub and exposes no raw provider/object coordinates. Candidate publication, preview commands and
proposal creation remain disabled until fenced publish and execution authorization are proven.

Alembic `0018` removes the fixed Chat retention duration. Existing sessions are honestly marked
`LEGACY_UNBOUND_V1`; new sessions require an exact `ACTIVE_POLICY_V1` binding to the workspace's
active policy ID/hash, database transaction time and calculated `chat_content_days` deadline.
PostgreSQL triggers reject fabricated deadlines, inactive policy bindings, non-owner message
appends and mutation of retention evidence. The application role retains only session
`version`/`updated_at` update privilege and no Chat delete privilege. Clean installations validate
the canonical `0001` contract, upgrades install it atomically, and partial schemas fail closed.

## Constraints enforced outside DDL

- Domain code owns legal change/upload/graph transitions and optimistic-version checks.
- Confidential/restricted apply requires two distinct final approvers; requester final approval is denied.
- `APPLIED` requires aggregate expected/observed hash equality after DataHub re-read.
- `COMPLETED` is permitted only for a non-executable typed change intake after independent final
  approval; it has no DataHub provider claim or reconciliation hash.
- Graph release publication validates ontology, endpoints, classification and non-empty provenance before insert.
- Object acceptance requires full streamed source SHA-256/size equality and format policy, an
  attempt-scoped destination, a full promoted-byte SHA-256/size read-back and a committed
  version-fenced manifest receipt before quarantine cleanup. Provider Object VersionId and
  conditional-copy evidence remain target-environment gates.
- Search and snapshot queries prefilter classification and scope before enrichment/serialization.
- Direct administrator membership access requires recent hardware WebAuthn. The optional password
  path applies only an approved typed request and rechecks maker/checker eligibility, target version
  and the two-human-security-administrator invariant under a workspace transaction lock.

## Backlog schema (not implemented)

Versioned general ABAC policies/bindings, catalog relationships/normalized hierarchy, connection registry,
general audit export, durable production inference jobs, saved-query templates
beyond the built-in surfaces and embedding partitions remain target tables. Governed retention
policy versions, Legal Hold history, typed Maker-Checker erasure requests/decisions and immutable
archive capability/receipt evidence are implemented. Erasure execution claims/attempts and archive
export attempts remain target tables.
These future records remain PostgreSQL canonical state; object-store metadata is not a policy, hold
or deletion authority. They require a later Alembic revision and updated API/retention/security
tests; their mention in PRD/architecture is not permission to create ad-hoc columns.

Alembic `0035` adds CR revision rounds and immutable TEST attachment/hash evidence. `0036` adds the
typed XLSX profile and fenced Bulk publication grants. `0037` adds the Knowledge PDF source/page/
embedding/extraction, projection verification and GraphRAG audit tables. `0038` expands persisted
connection-test scopes to actual model execution/authenticated Neo4j query evidence and records the
non-secret System Configuration/deployment binding on GraphRAG audits. SQLAlchemy metadata, the
regenerated `0001` baseline and these incremental migrations must remain deterministic equivalents.

`EVENT_RETENTION_DAYS` is a target online-retention input, not a deletion switch. Automatic event deletion remains disabled until immutable export has been written and read back from a verified Object-Lock store, Legal Hold precedence and Maker-Checker erasure approval are implemented, and a dedicated least-privilege retention worker is introduced.

## Retention and deletion

An approved database policy version distinguishes legal audit, Chat content, completed delivery
events, accepted data, quarantine and telemetry. Installation-specific durations are operating
inputs to that version and not portable schema, migration or source defaults. Activating a policy
version does not by itself enable deletion.

Chat persistence is the narrower exception to the last sentence: activation authorizes only the
calculation and immutable recording of a content deadline. It does not authorize expiry deletion,
partition detach/drop, object lifecycle action or WORM export. Policy supersession immediately
append-closes sessions bound to the prior version; it does not rewrite or delete their evidence.

Legal Hold is a versioned aggregate with typed place and governed release commands plus append-only
history, not a mutable object-manifest boolean. It takes precedence over ordinary expiry and blocks
explicit erasure, row pruning and partition detach/drop. A release-pending hold is treated as active.
The first partition implementation over-retains a whole partition when any applicable hold exists.

Object deletion follows canonical manifest/session state through a retryable typed erasure workflow.
The request binds workspace, target kind and UUID, target version/owner/classification, policy
version ID and payload hash, request reason/decision evidence and canonical payload hash.
Approval requires an independent checker, current policy and authorization plus a current
hold/version check. A future destructive executor additionally requires one-time atomic consumption
and a final authorization/hold/version check. Requests never carry raw
SQL, table names, object keys or provider operations. Immutable audit/release evidence is
pseudonymized where legally allowed rather than edited; a completion receipt preserves only the
minimum legally permitted evidence. Seed removal remains fixed namespace/run scoped and cannot match
non-seed resources.

The current implementation stops at APPROVED/REJECTED review evidence. APPROVED remains
`DISABLED_NOT_READY`: there is no consumption, worker claim, provider delete or partition operation.

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
