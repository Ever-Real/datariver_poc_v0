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
| `GET /capabilities` | `operations.read` | sanitized capability states |
| `GET /operations/summary` | `operations.read` | workspace counts for jobs, uploads, changes and outbox lag |
| `GET /operations/metrics` | `operations.read` | bounded-label Prometheus HTTP metrics |

### Catalog facade

| Method/path | Action | Purpose |
|---|---|---|
| `GET /catalog/assets?q=&asset_type=&platform=&lifecycle=&cursor=&limit=` | `catalog.search` | ABAC-prefiltered literal/full-text projection search; non-empty `q` minimum defaults to 2 |
| `GET /catalog/assets/{asset_id}` | `catalog.read` | authorized local base detail plus typed DataHub enrichment; optional `stale_at` marks bounded fallback |
| `POST /catalog/sync/datahub` | `catalog.sync` | idempotently upsert one fixed-contract DataHub scan page |

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

## DataHub adapter contract

The inward port exposes `scan_assets`, `get_asset`, `get_lineage`, `apply_change`, `read_aspect` and `capability`. Current HTTP routes use scan, detail, apply/reconcile and capability. Queries and proposal shapes are constants. The adapter classifies authentication, contract, rate-limit, network and provider failures without returning provider payloads or tokens.

The approved production contract is stable DataHub `v1.6.0`. The adapter reads the version from
`/config.versions["acryldata/datahub"].version`; a different or missing value degrades capability.
Production enforcement blocks enrichment, scan, apply and read-back with sanitized
`VERSION_MISMATCH`. This runtime check complements, rather than replaces, digest pinning and live
contract tests in the external DataHub deployment.

## Planned compatibility endpoints

The remaining backlog, not present in current OpenAPI, is catalog facets/suggestions/lineage routes; upload cancel/download/erasure; automated graph extraction and projection rebuild; Chat session history/SSE/external-model adapters; authored policy administration; and job/audit browsing/retry. They may not be emulated with generic provider or arbitrary query pass-through.
