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

### Health and operations

| Method/path | Authorization | Purpose |
|---|---|---|
| `GET /health/live` | public | process liveness only |
| `GET /health/ready` | dependency probe | canonical readiness |
| `GET /capabilities` | `operations.read` | sanitized capability states plus optional server-validated external UI links; no credential-bearing or client-supplied URL |
| `GET /operations/summary` | `operations.read` | workspace counts for jobs, uploads, changes and outbox lag, plus the fail-closed retention-automation state |
| `GET /operations/metrics` | `operations.read` | bounded-label Prometheus HTTP metrics |

### Catalog facade

| Method/path | Action | Purpose |
|---|---|---|
| `GET /catalog/assets?q=&asset_type=&platform=&classification=&lifecycle=&cursor=&limit=` | `catalog.search` | ABAC-prefiltered ALL-term literal/full-text projection search with plain-text match fragments; non-empty `q` minimum defaults to 2; cursor is bound to the exact permission/policy/projection/request snapshot |
| `GET /catalog/facets?q=&asset_type=&platform=&classification=&lifecycle=&limit=` | `catalog.search` | permission-prefiltered asset type, platform and classification buckets; null platform remains an explicit null bucket |
| `GET /catalog/suggestions?q=&limit=` | `catalog.search` | permission-prefiltered name autocomplete, maximum 20; two-character requests use the bounded prefix path and longer requests may use trigram similarity |
| `GET /catalog/tree/nodes?q=&parent_kind=ROOT\|PLATFORM\|DATABASE\|SCHEMA&platform=&database=&schema=&cursor=&limit=` | `catalog.search` | lazy canonical Resource Tree branch; authorization-pruned child counts, branch cursor and cache context are bound to the request security/projection snapshot |
| `GET /catalog/assets/{asset_id}` | `catalog.read` | authorized local base detail plus typed DataHub enrichment; optional `stale_at` marks bounded fallback |
| `GET /catalog/assets/{asset_id}/lineage?direction=UP\|DOWN\|BOTH&depth=1..3` | `catalog.read` | bounded typed DataHub lineage with set-based local authorization; a hidden intermediate truncates rather than bridges a path |
| `POST /catalog/sync/datahub` | `catalog.sync` | idempotently upsert one fixed-contract DataHub scan page |

Search, facet and suggestion metadata identifies the built-in policy version, governed classification
policy version, authorization generation and committed local `projection_version`. The latter is not a
DataHub source cursor or proof that a full reconciliation completed. Facet/suggestion `observed_at` is
nullable when no authorized row contributes a source observation.

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
| `POST /uploads` | `registration.create` | create private multipart quarantine intent |
| `POST /uploads/{upload_id}/parts` | `registration.create` | issue short-lived part URL |
| `POST /uploads/{upload_id}/complete` | `registration.create` | persist completion intent; returns `202` |
| `POST /uploads/{upload_id}/registration-proposals` | `registration.read` + `change.create` | create a governed aspect proposal from an `ACCEPTED` upload |

Completion does not mean accepted. Durable states are `INITIATED → COMPLETION_QUEUED → COMPLETING → QUARANTINED → VALIDATING → ACCEPTED`, with terminal `REJECTED/ABORTED/EXPIRED`. Workers stream object bytes, compare declared size/SHA-256, apply bounded format rules, copy to the accepted bucket, commit canonical location, then best-effort clean quarantine.

### Change management

| Method/path | Action | Purpose |
|---|---|---|
| `GET /change-requests?state=&limit=` | `change.read` | clearance-filtered list |
| `GET /change-requests/{id}` | `change.read` | items, approvals and transition audit |
| `POST /change-requests` | `change.create` | typed executable DataHub aspect proposal |
| `POST /change-requests/{id}/approvals` | `change.review` / `change.approve` | append immutable decision |
| `POST /change-requests/{id}/transitions` | derived | legal user-controlled transition/retry |

Implemented change item contract:

```json
{
  "target_type": "DATAHUB_ASPECT",
  "target_ref": "urn:li:dataset:(urn:li:dataPlatform:postgres,my.table,PROD)",
  "aspect_name": "datasetProperties",
  "operation": "UPSERT",
  "before_hash": null,
  "after_document": {"description":"Governed description"},
  "after_hash": null
}
```

The server canonicalizes and stores `after_hash`. If a supplied hash differs, creation fails. `APPLYING`, `APPLIED` and `APPLY_FAILED` are worker-only states. A requester cannot final-approve; confidential/restricted requests require two distinct final approvers. `APPLIED` requires post-write DataHub re-read hash equality.

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

### Administrator membership access

| Method/path | Assurance/authorization | Purpose |
|---|---|---|
| `GET /admin/me` | eligible human security administrator + recent password reauth or hardware WebAuthn | internal subject identity, current-assurance operations, fallback availability and the supported action vocabulary |
| `GET /admin/workspace-memberships?limit=` | eligible human security administrator + recent password reauth or hardware WebAuthn | bounded workspace membership display/version summaries, maximum 100 |
| `GET /admin/workspace-memberships/{subject_id}/access` | eligible human security administrator + recent password reauth or hardware WebAuthn | exact typed full access document plus display metadata, membership version and matching `ETag` |
| `PUT /admin/workspace-memberships/{subject_id}/access` | `admin.manage` + recent hardware WebAuthn | exact full access-document replacement for another subject |
| `GET /admin/fallback/workspace-membership-access-requests?state=&limit=` | eligible human security administrator + recent password reauth or hardware WebAuthn | bounded workspace fallback queue |
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

Administrator read contracts reuse the fallback `READ` assurance policy but do not require the
fallback feature to be enabled, so the hardware-key direct path can safely load the exact current
document. Ordinary password, OTP and service identities are denied before membership data is read.
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

The approved production contract is stable DataHub `v1.6.0`. The adapter reads the version from
`/config.versions["acryldata/datahub"].version`; a different or missing value degrades capability.
Production enforcement blocks enrichment, scan, apply and read-back with sanitized
`VERSION_MISMATCH`. This runtime check complements, rather than replaces, digest pinning and live
contract tests in the external DataHub deployment.

## Planned compatibility endpoints

The remaining backlog, not present in current OpenAPI, is governed server-side catalog export; upload cancel/download and governed erasure execution/consumption; automated graph extraction and projection rebuild; Chat session history/SSE/external-model adapters; immutable archive export/target-conformance workers; and job/audit browsing/retry. PostgreSQL can persist verified archive evidence, but no HTTP route, export worker or deletion capability is exposed. The disabled-first assistant inference source contract is not an HTTP route or deployed provider integration. Backlog features may not be emulated with generic provider or arbitrary query pass-through.
