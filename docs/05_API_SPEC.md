# API specification

Generated OpenAPI at `/api/v1/openapi.json` is authoritative for implemented payload schemas. This document defines semantics, authorization and planned compatibility without implying that backlog endpoints already exist.

## Conventions

- Base path `/api/v1`; JSON UTF-8; RFC 3339 UTC timestamps.
- Protected requests require `Authorization: Bearer …` and `X-Workspace-Id: <UUID>`.
- `X-Request-Id` is accepted only when it matches the safe ID pattern; otherwise the server creates one.
- Mutation endpoints declare `Idempotency-Key` where replay could duplicate business effects.
- Aggregate updates declare `If-Match: "<version>"`; graph publish uses `"none"` or a release SHA-256.
- Errors are sanitized `application/problem+json` with
  `type,title,status,detail,instance,code,request_id,violations?,remediation?`.
- `401` is invalid identity, `403` audited policy denial, `404` may conceal forbidden existence, `409` version/idempotency conflict, `422` semantic validation, `429` grant/gateway quota, and `502/503` a classified dependency failure.
- On one `401`, the browser may complete standard in-memory OIDC renewal and retry only a `GET`/`HEAD`
  request or a request with its declared `Idempotency-Key`. It never retries another mutation,
  suppresses a policy `403`, or performs a redirect loop after renewal fails.
- High-risk authorization is fail-closed. `PHISHING_RESISTANT_AUTH_REQUIRED`,
  `AUTHENTICATION_TIME_REQUIRED`, `AUTHENTICATION_TIME_INVALID` and
  `AUTHENTICATION_TOO_OLD` are audited policy reason codes. Request fields and headers cannot assert
  them; only the normalized context from a verified OIDC token is used.
- Authentication-only denials may expose one bounded remediation kind:
  `FIDO2_REQUIRED`, `REAUTH_REQUIRED` or `FALLBACK_UNAVAILABLE`. Raw policy reasons, decision IDs,
  token claims and fallback payloads are never returned. If a non-auth policy reason is also
  present, no authentication remediation is offered because reauthentication cannot make that
  request permissible.

## Implemented endpoint inventory

### Authentication profile hydration

| Method/path | Authorization | Purpose |
|---|---|---|
| `GET /auth/me` | verified bearer identity; no Workspace header | sanitized subject, display name, email, realm roles, normalized assurance and authentication time for React in-memory hydration after an OIDC callback or silent SSO round-trip |
| `GET /admin/me` | read-only workspace administrator context | reports the current verified assurance (including ordinary `PASSWORD`/`OTHER_MFA`) and server-authorized administrator operations without triggering FIDO2/password reauthentication; each sensitive mutation applies its own assurance check |

### Health and operations

| Method/path | Authorization | Purpose |
|---|---|---|
| `GET /health/live` | public | process liveness only |
| `GET /health/ready` | dependency probe | canonical readiness |
| `GET /capabilities` | `operations.read` | sanitized capability states plus optional server-validated external UI links; no credential-bearing or client-supplied URL |
| `GET /operations/summary` | `operations.read` | current workspace counts for jobs, uploads, changes, outbox lag and non-deleted typed DataHub projections; the bounded (200 branches + explicit truncation) platform/database/schema coverage reports only asset and non-blank-description counts, never catalog rows, classification, tags, glossary terms or provider documents; includes the fail-closed retention-automation state |
| `GET /operations/metrics` | `operations.read` | bounded-label Prometheus HTTP metrics |

### Catalog facade

| Method/path | Action | Purpose |
|---|---|---|
| `GET /catalog/assets?q=&asset_type=&platform=&classification=&lifecycle=&cursor=&limit=` | `catalog.search` | ABAC-prefiltered ALL-term literal/full-text projection search with plain-text match fragments; non-empty `q` minimum defaults to 2; cursor is bound to the exact permission/policy/projection/request snapshot |
| `GET /catalog/facets?q=&asset_type=&platform=&classification=&lifecycle=&limit=` | `catalog.search` | permission-prefiltered asset type, platform and classification buckets; null platform remains an explicit null bucket |
| `GET /catalog/suggestions?q=&limit=` | `catalog.search` | permission-prefiltered name autocomplete, maximum 20; two-character requests use the bounded prefix path and longer requests may use trigram similarity |
| `GET /catalog/tree/nodes?q=&parent_kind=ROOT\|PLATFORM\|DATABASE\|SCHEMA&platform=&database=&schema=&cursor=&limit=` | `catalog.search` | lazy canonical Resource Tree branch; authorization-pruned child counts, branch cursor and cache context are bound to the request security/projection snapshot |
| `GET /catalog/assets/{asset_id}` | `catalog.read` | authorized local base detail plus typed DataHub enrichment; optional `stale_at` marks bounded fallback |
| `POST /catalog/assets/{asset_id}/description-previews` | `catalog.read` + `change.create` | read live `datasetProperties`, preserve every provider field, and return only the typed description diff, source/hash evidence and opaque quoted preview ETag; `Cache-Control: no-store, private` |
| `POST /catalog/assets/{asset_id}/description-change-requests` | `catalog.read` + `change.create` | require the exact preview `If-Match`, re-read DataHub, share-lock/revalidate the path asset and create one server-classified governed request |
| `GET /catalog/assets/{asset_id}/lineage?direction=UPSTREAM\|DOWNSTREAM\|BOTH&depth=1..3` | `catalog.read` | bounded typed DataHub lineage with set-based local authorization; a hidden intermediate truncates rather than bridges a path |
| `GET /catalog/export-capability` | `catalog.export` | separately authorized feature state; missing permission, dependency error or disabled worker is fail-closed in the UI |
| `POST /catalog/exports` | `catalog.export` | create an owner-scoped CSV job from exact typed search filters and an `Idempotency-Key`; RESTRICTED is denied |
| `GET /catalog/exports/{export_id}` | `catalog.export` + owner | bounded job/artifact status; never returns bucket, object key or a source cursor |
| `POST /catalog/exports/{export_id}/download` | `catalog.export` + owner | revalidate current permission/policy/projection and object metadata, then issue a 60-second URL with `Cache-Control: no-store` |
| `POST /catalog/sync/datahub` | `catalog.sync` | idempotently upsert one fixed-contract DataHub scan page |

Under ADR-0020, the four discovery endpoints and `GET /catalog/assets/{asset_id}` use the same
standard response schema for an eligible human security administrator's audited
`catalog.quarantine.read` review. Its query is restricted to non-deleted rows in that
administrator's current workspace so unclassified/`QUARANTINED` DataHub projections can be
classified. It may use the existing typed DataHub metadata enrichment for that catalog detail, but
never changes `/catalog/exports`, Chat, attachment, arbitrary provider or mutation authorization and
is not available to a service identity.

Search, facet and suggestion metadata identifies the built-in policy version, governed classification
policy version, authorization generation and committed local `projection_version`. The latter is not a
DataHub source cursor or proof that a full reconciliation completed. Facet values are textual at the
HTTP boundary: `classification` uses its enum name, as do `asset_type` and `platform` values. This
also keeps PostgreSQL `UNION ALL` aggregation type-consistent. Facet/suggestion `observed_at` is
nullable when no authorized row contributes a source observation.

The ordinary MANUAL description contract accepts only `{description}` for preview and
`{description,title,change_description}` for creation. The browser cannot submit a URN, Aspect name,
classification, provider document or source hash. The preview ETag is a canonical opaque binding of
workspace, path asset ID, current target fingerprint, Aspect hash and provider source version. An
empty description is an explicit clear proposal; a live no-op is rejected. Other provider fields,
including nested/custom properties, are copied from the verified live document and never returned to
the browser.

DataHub sync request:

```json
{"sync_id":"018f47aa-7c2e-7a11-8e54-3b08ef40fc91","offset":0,"limit":100}
```

Response carries `upserted,tombstoned,next_offset,total,observed_at`. A single active `sync_id` must start at offset zero and advance in order. The final page tombstones missing DataHub-owned rows; seed-owned rows are excluded. A scheduler never forwards arbitrary GraphQL. DataHub calls use a bounded-concurrency bulkhead and circuit breaker; stale detail fallback is never valid for applying or reconciling a change.

### Upload and registration

| Method/path | Action | Purpose |
|---|---|---|
| `GET /uploads?state=&limit=` | `registration.read` | caller-owned manifests; security administrators may see workspace scope |
| `GET /uploads/{upload_id}` | `registration.read` | manifest, worker state, validation summary/failure code |
| `POST /uploads` | `registration.create` | create private multipart quarantine intent with explicit format-only or bounded dataset-description content profile |
| `POST /uploads/{upload_id}/parts` | `registration.create` | issue short-lived part URL |
| `POST /uploads/{upload_id}/complete` | `registration.create` | persist completion intent; returns `202` |
| `POST /uploads/{upload_id}/preparations` | `registration.read` + `registration.validate` | queue/reuse the server-owned typed configuration for an exact accepted manifest version; requires `If-Match` and `Idempotency-Key`, accepts no body |
| `GET /uploads/{upload_id}/preparations?state=&limit=` | `registration.read` | list bounded typed preparation state/progress without object coordinates or parser payload |
| `GET /uploads/{upload_id}/preparations/{preparation_id}` | `registration.read` | read one upload-scoped typed preparation with private no-store response |
| `GET /uploads/{upload_id}/preparations/{preparation_id}/candidates?cursor=&limit=` | `registration.read` + `catalog.read` + `change.create` | page immutable V2 submitted evidence and separately authorized current ACTIVE DATASET targets; private no-store, opaque cursor, no total or provider/object coordinates |
| `POST /uploads/{upload_id}/registration-proposals` | `registration.read` + `change.create` + `change.raw.create` | operator/recovery-only raw proposal from an `ACCEPTED` upload; not exposed in the ordinary UI and not accepted as typed-content binding |

Completion does not mean accepted. Durable states are `INITIATED → COMPLETION_QUEUED → COMPLETING → QUARANTINED → VALIDATING → ACCEPTED`, with terminal `REJECTED/ABORTED/EXPIRED`. Workers stream object bytes, compare declared size/SHA-256, apply bounded format rules, copy to the accepted bucket, commit canonical location, then best-effort clean quarantine.

The first typed profile is `DATASET_DESCRIPTION_CSV_V1`: UTF-8-with-BOM-compatible CSV with the exact
ordered headers `asset_id,platform,database_name,schema_name,table_name,description`, maximum 512 MiB,
50,000 rows, 64 KiB per logical row and 10,000 description characters. Platform is bounded to 100,
database/schema to 255 and table name to 500 characters. The API derives the parser/schema/
validator configuration hash server-side and creates at most one preparation for an upload version
and configuration. It rejects non-`ACCEPTED`, stale-version, format-only and incomplete promoted-byte
evidence. The source-only parser accepts LF/CRLF and a BOM only at byte zero, preserves exact
description content and uses strict all-or-nothing failure: a valid result has `rejected_count=0`.
Candidate hashes bind workspace, asset, submitted identity, profile/schema and exact description.
The receipt root is an ordered result chain over ordinal and candidate hash, not a Merkle inclusion
proof. Candidate reads require a current classification snapshot and one set-based local projection
lookup; a legacy candidate or any missing, denied or identity-drifted target fails the whole page with
a non-disclosing response. The opaque cursor binds upload/preparation/receipt, subject permission
scope, policy/classification snapshot, projection watermark and limit. The parser worker, fenced
staging/finalize path and candidate-to-change command are not enabled; a `QUEUED` preparation is not
an executable proposal.

The current BULK UI sends `content_profile` explicitly rather than relying on the server default.
Only an `ACCEPTED` `DATASET_DESCRIPTION_CSV_V1` upload exposes preparation controls. It first reads
the no-store preparation list, then sends a bodyless create request with the exact quoted upload
manifest version and a new idempotency key. Format-only, failed/stale and `READY` preparation views
do not expose raw proposal, candidate execution or DataHub update actions.

### Change management

| Method/path | Action | Purpose |
|---|---|---|
| `GET /change-requests?state=&limit=` | `change.read` | clearance-filtered candidates followed by one grouped current-target authorization; hidden, deleted and legacy-unbound targets are omitted |
| `GET /change-requests/{id}` | `change.read` | items, immutable server target binding, approvals and transition audit; current-target denial is existence-hiding 404 |
| `POST /change-requests` | `change.raw.create` + `change.create` | hardware-human operator/recovery raw DataHub Aspect proposal; absent from the ordinary UI |
| `POST /change-requests/{id}/approvals` | `change.review` / `change.approve` | append immutable decision |
| `POST /change-requests/{id}/transitions` | derived | legal user-controlled transition/retry |

At creation time, the service resolves every `target_ref` through the authorization-pruned local catalog projection in
the request workspace, evaluates `change.create` against the target's actual system, domain and
classification, and rejects a request classification lower than any target. The executable aspect
allowlist is `datasetProperties`, `domains`, `globalTags`, `glossaryTerms`, `ownership` and
`schemaMetadata`. A request currently contains exactly one item until durable per-item checkpoints
exist. The item must carry the current provider aspect SHA-256; omission or mismatch fails closed
before provider mutation. The server persists a creation-time target binding and approval/forward
transition re-resolves current identity and scope under the same request transaction. Apply-time
requester/policy reauthorization, DataRiver target serialization and an external atomic CAS remain
required hardening gates.

`change.raw.create` is deny-by-default, classified as both high-risk and human-governance-only, and
is not granted by local identity or semiconductor seed bootstrap. A hardware-authenticated human
must receive it through controlled access administration; service accounts remain denied even if a
stored membership is misconfigured to contain the action. Typed MANUAL creation is the only current
ordinary edit surface and does not use this raw capability.

Operator/recovery raw change item contract:

```json
{
  "target_type": "DATAHUB_ASPECT",
  "target_ref": "urn:li:dataset:(urn:li:dataPlatform:postgres,my.table,PROD)",
  "aspect_name": "datasetProperties",
  "operation": "UPSERT",
  "before_hash": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
  "after_document": {"description":"Governed description"},
  "after_hash": null
}
```

The server canonicalizes and stores `after_hash`. It also stores read-only target asset/type/scope,
classification/lifecycle, source version/observation and binding-hash fields; those fields are not
accepted in the create body. If a supplied content hash differs, creation fails. `APPLYING`, `APPLIED`
and `APPLY_FAILED` are worker-only states. A requester cannot final-approve;
confidential/restricted requests require two distinct final approvers. `APPLIED` requires post-write
DataHub re-read hash equality. Legacy items without a verifiable server binding are quarantined and
cannot re-enter the ordinary workflow.

### Knowledge graph and analysis

| Method/path | Action | Purpose |
|---|---|---|
| `POST /knowledge/graphs` | `kg.create` | graph plus initial typed ontology |
| `GET /knowledge/graphs` | `kg.read` | clearance-filtered graphs |
| `POST/GET /knowledge/graphs/{graph_id}/changesets` | `kg.edit` / `kg.read` | create/list a base-release-pinned changeset |
| `POST .../changesets/{changeset_id}/operations` | `kg.edit` | append typed node/edge upsert/delete with provenance |
| `POST .../changesets/{changeset_id}/submit` | `kg.edit` | materialize and persist validation evidence |
| `POST .../changesets/{changeset_id}/reviews` | `kg.review` | independent approve/reject |
| `POST .../changesets/{changeset_id}/publish` | `kg.publish` | publish an approved changeset as an immutable release |
| `POST /knowledge/graphs/{graph_id}/releases` | `kg.publish` | validate and publish immutable snapshot |
| `GET /knowledge/graphs/{graph_id}/releases` | `kg.read` | list immutable releases |
| `POST .../releases/{release_id}/activate` | `kg.publish` | atomically select/roll back active release |
| `GET /knowledge/graphs/{graph_id}/releases/{release_id}/snapshot?maximum_nodes=` | `kg.read` | ABAC-filtered release view |
| `GET .../{release_id}/export?format=json-ld|edge-list` | `kg.export` | release-pinned governed export |
| `POST .../{release_id}/analysis/neighbors` | `sharing.invoke` | typed bounded neighbor traversal |

Neighbor request accepts only `node_id`, `direction=IN|OUT|BOTH`, an edge-type allowlist, `maximum_hops<=3` and `maximum_nodes<=500`. It cannot contain SQL, Cypher, labels or clauses. Every published node/edge requires ontology membership, valid endpoints, classification and provenance.

### API products and consumer grants

| Method/path | Action | Purpose |
|---|---|---|
| `POST/GET /api-products` | `sharing.manage` | create/list release-pinned product contracts |
| `POST /api-products/{id}/versions` | `sharing.manage` | create the next immutable contract draft |
| `POST .../versions/{version_id}/publish` | `sharing.publish` | strong-auth publish and deprecate prior current version |
| `POST/GET /api-products/{id}/grants` | `sharing.manage` | grant current version to OIDC `client_id` with scope/classification/time/quota |
| `POST .../grants/{grant_id}/revoke` | `sharing.manage` | immediately revoke a grant |
| `POST .../{id}/authorize-invocation` | `sharing.invoke` | atomic client/grant/scope/validity/quota check and usage record |
| `POST .../{id}/invoke/neighbors` | `sharing.invoke` | grant-metered, contract-bounded analysis on the pinned release |
| `POST .../{id}/invoke/snapshot` | `sharing.invoke` | grant-metered ABAC-filtered snapshot with scoped hash/counts |
| `POST .../{id}/invoke/chat` | `sharing.invoke` | deterministic evidence Chat over only the pinned authorized release |

Product versions accept only the registered `SNAPSHOT`, `NEIGHBORS` or `CHAT` surfaces and supported scopes. Credentials stay in the IdP/gateway; DataRiver stores only `consumer_client_id`. Replaying the same invocation idempotency key does not consume quota twice.

### Chat

| Method/path | Action | Purpose |
|---|---|---|
| `POST /chat/query` | `chat.query` plus `catalog.read` / `kg.read` per citation | persist a question and deterministic authorized-evidence answer |

Request is `{session_id?,question,maximum_evidence<=10}`. Response carries session/message IDs, answer and immutable evidence chunk metadata: `chunk_id`, resource/workspace-authorized classification and typed scope, source type/locator/version, SHA-256 content hash, effective interval and extraction method. Composer citations must be a non-empty, duplicate-free subset of the exact authorized chunk input and pass hash/workspace revalidation; any forged, empty or invalid citation fails closed to the exact answer `검증 불가` with no returned/persisted evidence. The baseline deliberately has no external LLM.

Final persistence requires a workspace ACTIVE retention-policy version. A new session binds the
exact policy ID/hash, database transaction time and policy-derived deadline in one locked
transaction. Missing active policy returns `409`; a legacy-unbound, expired or superseded-policy
session also returns `409` and the caller must start a new session. These failures persist no Chat
session/message. Policy activation is available only through the independent retention
maker-checker API; there is no Chat-specific duration parameter or fallback.

### Administrator membership access

| Method/path | Assurance/authorization | Purpose |
|---|---|---|
| `GET /admin/me` | eligible human security administrator with a valid current OIDC identity | internal subject identity, current-assurance operations, fallback availability and the supported action vocabulary; read discovery never grants mutation authority |
| `GET /admin/workspace-memberships?limit=` | eligible human security administrator with a valid current OIDC identity | bounded workspace membership display/version summaries, maximum 100 |
| `GET /admin/workspace-memberships/{subject_id}/access` | eligible human security administrator with a valid current OIDC identity | exact typed full access document plus display metadata, membership version and matching `ETag` |
| `PUT /admin/workspace-memberships/{subject_id}/access` | `admin.manage` + recent hardware WebAuthn | exact full access-document replacement for another subject |
| `GET /admin/fallback/workspace-membership-access-requests?state=&limit=` | eligible human security administrator with a valid current OIDC identity | bounded workspace fallback queue |
| `POST /admin/fallback/workspace-membership-access-requests` | eligible human security administrator + recent password reauth | create a five-minute typed maker request |
| `POST .../{request_id}/decisions` | independent eligible human checker + recent password reauth or hardware WebAuthn | append approve/reject evidence |
| `POST .../{request_id}/consume` | original maker + recent password reauth | atomically apply the approved command once |

All mutations require `Idempotency-Key` and a quoted positive `If-Match`. The create request's
version is the target membership version; decision and consume versions are the fallback aggregate
version. The only command is `WORKSPACE_MEMBERSHIP_ACCESS_UPDATE_V1` with `active`, `clearance`,
groups, allowed/denied actions and bounded system/domain UUID scopes. Unknown fields and unknown
actions are rejected. Maker, checker and target must be distinct; self-access mutation is forbidden.
The server rechecks both human administrators, the unchanged target version and at least two
remaining eligible human security administrators in the mutation transaction. Fallback is disabled
unless `ADMIN_PASSWORD_FALLBACK_ENABLED=true`; disabled requests return only the bounded
`FALLBACK_UNAVAILABLE` remediation.

Administrator read contracts are discovery only: an eligible authenticated human may load
`/admin/me` and the bounded read documents without password reauthentication, and the read path
never grants mutation authority. Service identities remain denied. Sensitive write/delete operations
continue to require their operation-specific hardware WebAuthn or typed password fallback policy;
the browser offers explicit reauthentication only after such a response and never retries or replays
a command automatically after return.
The list returns summaries only; a client must fetch the detail immediately before editing and use
its quoted version for `If-Match`. Unknown stored action/scope values fail closed instead of being
silently omitted. `allowed_operations` in `/admin/me` reflects the current token assurance, fallback
feature flag and effective retention/Legal-Hold/erasure action grants and denies. Clients use it to
avoid exposing or preloading unrelated administration surfaces; every mutation still performs its
operation-specific authorization and maker/checker/target validation.

### Classification access and inference-provider administration

| Method/path | Assurance/authorization | Purpose |
|---|---|---|
| `GET /admin/classification-access/policies?state=&limit=` | eligible human security administrator | list bounded policy versions |
| `GET /admin/classification-access/policies/current` | eligible human security administrator | return the active four-class policy or null |
| `GET /admin/classification-access/policies/{policy_id}` | eligible human security administrator | return one exact policy version and `ETag` |
| `POST /admin/classification-access/policies` | recent hardware WebAuthn | propose exactly four Search/Chat rules |
| `POST /admin/classification-access/policies/{policy_id}/decisions` | independent checker + recent hardware WebAuthn | approve/activate or reject a policy |
| `GET /admin/classification-access/restricted-search-grants?state=&subject_id=&limit=` | eligible human security administrator | list bounded policy-bound grants |
| `GET /admin/classification-access/restricted-search-grants/{grant_id}` | eligible human security administrator | return an exact grant and `ETag` |
| `POST /admin/classification-access/restricted-search-grants` | recent hardware WebAuthn | propose a typed resource/system/domain grant; the server binds the active policy ID/hash |
| `POST /admin/classification-access/restricted-search-grants/{grant_id}/decisions` | independent checker + recent hardware WebAuthn | approve or reject the bound grant |
| `POST /admin/classification-access/restricted-search-grants/{grant_id}/revocations` | recent hardware WebAuthn | revoke a grant immediately |
| `GET /admin/inference/provider-profiles?profile_key=&state=&limit=` | eligible human security administrator | list server-registered immutable profile versions |
| `GET /admin/inference/provider-profiles/{profile_version_id}` | eligible human security administrator | return an exact profile version and `ETag` |
| `POST /admin/inference/provider-profiles/{profile_version_id}/decisions` | independent checker + recent hardware WebAuthn | approve or reject a server-registered profile |
| `POST /admin/inference/provider-profiles/{profile_version_id}/revocations` | recent hardware WebAuthn | revoke a profile immediately |

Every mutation requires `Idempotency-Key`; decisions and revocations also require quoted positive
`If-Match`. The browser cannot create a provider profile and no contract accepts a provider endpoint,
credential or secret. Policy activation and request-time resolution revalidate immutable profile
versions, jurisdiction, classification ceiling and bounded residency/zero-retention attestations.
RESTRICTED Chat is invariantly denied; RESTRICTED Search still intersects the exact grant with normal
workspace, clearance and system/domain authorization.

### Retention policy and Legal Hold administration

| Method/path | Action | Purpose |
|---|---|---|
| `GET /admin/retention/policies?state=&limit=` | `retention.read` | list bounded policy versions and explicit disabled automation state |
| `GET /admin/retention/policies/current` | `retention.read` | return the workspace ACTIVE version or null |
| `POST /admin/retention/policies` | `retention.manage` + recent hardware WebAuthn | propose typed durations as runtime policy data |
| `POST .../policies/{policy_id}/decisions` | independent `retention.manage` checker + recent hardware WebAuthn | approve/activate or reject; atomically supersede the previous ACTIVE version |
| `GET /admin/retention/legal-holds?state=&limit=` | `retention.read` | list holds with append-only action history |
| `POST /admin/retention/legal-holds` | `legal_hold.place` + recent hardware WebAuthn | place a typed hold immediately |
| `POST .../legal-holds/{hold_id}/release-requests` | `legal_hold.release` + recent hardware WebAuthn | create a version-bound release request |
| `POST .../legal-holds/{hold_id}/release-decisions` | independent `legal_hold.release` checker + recent hardware WebAuthn | approve or reject release |
| `GET /admin/retention/erasure-requests?state=&limit=` | `retention.read` | list bounded Maker-Checker requests; approval is not execution |
| `GET /admin/retention/erasure-requests/{erasure_request_id}` | `retention.read` | return the exact request snapshot and quoted version |
| `POST /admin/retention/erasure-requests` | `erasure.request` + recent hardware WebAuthn | request review for a typed canonical target; the server resolves owner, version and classification |
| `POST .../erasure-requests/{erasure_request_id}/decisions` | independent `erasure.approve` checker + recent hardware WebAuthn | approve or reject after re-reading target, policy and applicable Legal Holds |

Every mutation requires `Idempotency-Key`; decisions and release commands also require a quoted
positive `If-Match`. Policy durations have no source default and are covered by a canonical payload
hash. Legal Hold placement and every release action have separate canonical hashes. Placement is
conservative and immediate; release requires a different human checker. Service identities are
denied. All responses expose `DISABLED_NOT_READY` for automatic partition/deletion effects, and
there is no delete, execute, consume, partition-detach or archive-verification endpoint in this
slice. Erasure request input cannot contain classification, owner, target version, object location,
SQL or provider commands. Approval rechecks the canonical target version/owner/classification, the
active policy ID and payload hash, and workspace/resource/subject Legal Holds. Rejection can close a
stale or expired request, but it never enables execution.

## DataHub adapter contract

The inward port exposes `scan_assets`, `get_asset`, `get_lineage`, `apply_change`, `read_aspect` and `capability`. Current HTTP routes use scan, detail, apply/reconcile and capability. Queries and proposal shapes are constants. The adapter classifies authentication, contract, rate-limit, network and provider failures without returning provider payloads or tokens.

`DATAHUB_EXPECTED_VERSION` supplies the exact stable DataHub release for a deployment; the current
example contract is `v1.6.0`. The adapter reads `/config.versions["acryldata/datahub"].version`; a
different or missing value degrades capability. RC, snapshot, head, latest and partial version values
are rejected during configuration. Production enforcement blocks enrichment, scan, apply and read-back
with sanitized `VERSION_MISMATCH`. This runtime check complements, rather than replaces, digest pinning
and live contract tests in the external DataHub deployment.

### Managed catalog export invariants

The API never accepts an object coordinate, provider endpoint, arbitrary column list, cursor or raw
query language for export. Creation persists a canonical request hash plus permission,
classification-policy, built-in-policy, CSV-safety and projection snapshots in the same transaction
as its job, outbox event and idempotency result. The worker reads only the local authorized
projection, always excludes `RESTRICTED`, emits a fixed RFC 4180 UTF-8 schema, fails closed on stale
snapshots and uses an attempt-unique private object key. Row, record and object-byte ceilings are
enforced. A stale/superseded lease cannot complete or overwrite a newer attempt.

Status is requester-owned. Download repeats authorization and snapshot checks, reconciles the stored
size, request metadata and provider ETag, and returns no storage coordinate other than the bounded
presigned URL. The runtime toggle defaults off. Enabling it without separate DB and S3 principals is
configuration-invalid; the checked-in local stack intentionally has no such credentials yet.

## Planned compatibility endpoints

The remaining backlog, not present in current OpenAPI, is upload cancel/download and governed erasure execution/consumption; automated graph extraction and projection rebuild; Chat session history/SSE/external-model adapters; immutable archive export/target-conformance workers; and job/audit browsing/retry. PostgreSQL can persist verified archive evidence, but no archive-export or deletion capability is exposed. The catalog-export source/API/UI contract exists but its isolated worker deployment remains disabled pending separately provisioned credentials. The disabled-first assistant inference source contract is not an HTTP route or deployed provider integration. Backlog features may not be emulated with generic provider or arbitrary query pass-through.
