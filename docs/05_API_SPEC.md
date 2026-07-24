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
- Sanitized domain-error responses use `Cache-Control: private, no-store`. A `429` includes an
  integer advisory `Retry-After`; Sharing per-minute exhaustion returns `60`, while monthly
  exhaustion uses the pre-completion database UTC boundary with a 60-second floor. Admission always
  rechecks the current database month, so the header is a backoff hint rather than a reset promise.
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
| `GET /auth/me` | verified bearer identity; no Workspace header | sanitized subject, display name, email, realm roles, normalized assurance/authentication time, one server-selected active `default_workspace_id` and operator-owned capability flags including `password_change_supported`. No provider URL or credential is returned; every later request still verifies Workspace membership and assurance. |
| `GET /admin/me` | read-only workspace administrator context | reports the current verified assurance (including ordinary `PASSWORD`/`OTHER_MFA`) and server-authorized administrator operations without triggering FIDO2/password reauthentication; each sensitive mutation applies its own assurance check |

### Health and operations

| Method/path | Authorization | Purpose |
|---|---|---|
| `GET /health/live` | public | process liveness only |
| `GET /health/ready` | dependency probe | canonical readiness |
| `GET /capabilities` | `operations.read` | sanitized capability states plus optional server-validated external UI links and a disabled-first Grafana embed descriptor; no credential-bearing or client-supplied URL |
| `GET /operations/summary` | `operations.read` | current workspace counts for jobs, uploads, changes, outbox lag and non-deleted typed DataHub projections; the bounded (200 branches + explicit truncation) platform/database/schema coverage reports only asset and non-blank-description counts, never catalog rows, classification, tags, glossary terms or provider documents; includes the fail-closed retention-automation state |
| `GET /operations/metrics` | `operations.read` | bounded-label Prometheus HTTP metrics |

### Catalog facade

| Method/path | Action | Purpose |
|---|---|---|
| `GET /catalog/assets?q=&search_fields=&asset_type=&platform=&database=&schema=&domain=&classification=&lifecycle=&cursor=&limit=` | `catalog.search` | ABAC-prefiltered ALL-term local projection search with plain-text match fragments and bounded `total`; `total_exact=true` only proves an exhaustive first page, otherwise `total` is the page-local lower bound and `next_cursor` is authoritative; each summary returns at most 1,000 description characters, 20 tags and 20 terms (240 characters per value) with explicit truncation flags; `search_fields` is the fixed `SCHEMA,TABLE,COLUMN,TAG,TERM,DESCRIPTION` vocabulary, and non-empty `q` minimum defaults to 2; cursor is bound to the exact permission/policy/projection/request snapshot |
| `GET /catalog/facets?q=&search_fields=&asset_type=&platform=&database=&schema=&domain=&classification=&lifecycle=&limit=` | `catalog.search` | permission-prefiltered asset type, platform, database, schema, domain, classification and lifecycle buckets computed with the identical search-field predicate and one server-ranked `GROUPING SETS` aggregation; each collection is bounded by `limit`, and null source values remain explicit null buckets |
| `GET /catalog/suggestions?q=&limit=` | `catalog.search` | permission-prefiltered ALL-term autocomplete over the same fixed Schema/Table/Column/Tag/Term/Description vocabulary as default catalog search, maximum 20; each item returns database/schema context and bounded plain-text `matches`, and the response declares `match_mode=ALL` |
| `GET /catalog/tree/nodes?q=&parent_kind=ROOT\|PLATFORM\|DATABASE\|SCHEMA&platform=&database=&schema=&cursor=&limit=` | `catalog.search` | lazy canonical Resource Tree branch; authorization-pruned child counts, branch cursor and cache context are bound to the request security/projection snapshot |
| `GET /catalog/assets/{asset_id}?field_offset=&field_limit=&field_source_version=` | `catalog.read` | authorized local base detail plus typed DataHub enrichment; detail display metadata is bounded to 10,000 description characters, 100 tags and 100 terms (1,000 characters per value) with explicit truncation flags; schema fields are serialized in an offset page (default 100, maximum 200), subsequent pages may bind the first page's source version and fail with 409 if it changes, and the provider projection retains at most 1,000 unique fields; total/total-exact/available/truncated/offset/limit/has-more metadata makes the bound explicit, with `total` representing the proven lower bound when `total_exact=false`; optional `stale_at` marks bounded fallback |
| `GET /catalog/assets/{asset_id}/datahub-lineage-embed` | `catalog.read` | after local authorization, return only the server-built exact configured DataHub `/dataset/{encoded-URN}/Lineage` URL or an explicit disabled/not-configured state; never returns a provider token or accepts a browser URL |
| `POST /catalog/assets/{asset_id}/description-previews` | `catalog.read` + `change.create` | read live `datasetProperties`, preserve every provider field, and return only the typed description diff, source/hash evidence and opaque quoted preview ETag; `Cache-Control: no-store, private` |
| `POST /catalog/assets/{asset_id}/description-change-requests` | `catalog.read` + `change.create` | require the exact preview `If-Match`, re-read DataHub, share-lock/revalidate the path asset and create one server-classified governed request |
| `GET /catalog/assets/{asset_id}/lineage?direction=UPSTREAM\|DOWNSTREAM\|BOTH&depth=1..3` | `catalog.read` | bounded typed DataHub lineage with set-based local authorization; a hidden intermediate truncates rather than bridges a path |
| `GET /catalog/export-capability` | `catalog.export` | separately authorized feature state; missing permission, dependency error or disabled worker is fail-closed in the UI |
| `POST /catalog/exports` | `catalog.export` | create an owner-scoped CSV or XLSX job from exact typed search filters and an `Idempotency-Key`; RESTRICTED is denied |
| `GET /catalog/exports/{export_id}` | `catalog.export` + owner | bounded job/artifact status; never returns bucket, object key or a source cursor |
| `POST /catalog/exports/{export_id}/download` | `catalog.export` + owner | revalidate current permission/policy/projection and object metadata, then issue a 60-second URL with `Cache-Control: no-store` |
| `GET /catalog/sync/datahub/{sync_id}` | `catalog.sync` | return governed run state, public next-page ordinal, seen/expected counts and the verified-snapshot flag for bounded scheduler resume; never returns the provider cursor |
| `POST /catalog/sync/datahub` | `catalog.sync` | reserve and idempotently commit one fixed-contract DataHub scroll page; the request carries only the server page ordinal, never a provider cursor; an oversized response adaptively reduces its bounded page size |

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
HTTP boundary: `classification` uses its enum name, as do `asset_type`, `platform`, database,
schema, domain and lifecycle values. Facet/suggestion `observed_at` is
nullable when no authorized row contributes a source observation.

Catalog query expansion is bounded to 12 unique whitespace-delimited terms and 120 characters per
term. Every term must match at least one enabled field. Match evidence uses only
`NAME|DESCRIPTION|SCHEMA|COLUMN|TAG|TERM`; a long value is split into bounded fragments so every
declared `matched_term` occurs in the returned plain text. The browser renders text, never
provider/server HTML.

Every catalog asset summary/detail carries `description_truncated`, `tags_truncated` and
`terms_truncated`. Each schema field additionally carries type/description/term/tag truncation
evidence. `false` means the value was complete at that response boundary, not that DataHub contains
no other Aspect. The local search projection itself stores at most 10,000 description characters,
100 tags, 100 terms and 1,000 column paths under ADR-0039.

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

Response carries
`upserted,tombstoned,next_offset,total,observed_at,tombstone_status`. `next_offset` is a page ordinal,
not the opaque DataHub scroll cursor. A single active `sync_id` starts at zero and advances in order;
the server persists the cursor, first-page total, distinct seen count and snapshot assertion.
`GET /catalog/sync/datahub/{sync_id}` returns only the governed run state, next public page ordinal,
seen/expected counts and snapshot-consistency flag; it never exposes the provider cursor. Airflow
reads this progress before each task attempt, jumps directly to the persisted page and returns
without replaying an already completed run. The server reserves a workspace reconciliation under
one transaction-scoped advisory lock before calling DataHub, so different runs cannot fetch
concurrent snapshots and apply them in reverse order. Identical concurrent idempotency keys replay
the first committed result after that lock instead of making a second provider request.
`tombstone_status` is `NOT_FINAL`, `APPLIED`, or
`SUPPRESSED_UNVERIFIED_SNAPSHOT`. Missing DataHub-owned rows are tombstoned only after terminal,
stable-total, exact-seen completion and an operator-evidenced PIT configuration under ADR-0040;
seed-owned rows are always excluded. Cursor expiry abandons the run without deletion. A scheduler
never forwards arbitrary GraphQL. A bounded DataHub response overflow halves the page size down to
one entity while retaining the same server-owned cursor. Queue, version probe, GraphQL and adaptive
attempts share a fixed 10-second reservation budget below the runtime database's 15-second statement
and 30-second idle-transaction timeouts; budget expiry rolls back and is retryable. Other
non-retryable failures abandon a continuation without deletion. DataHub calls use a
bounded-concurrency bulkhead and circuit breaker; stale detail fallback is never valid for applying
or reconciling a change.

### Upload and registration

| Method/path | Action | Purpose |
|---|---|---|
| `GET /uploads/operator-capability` | authenticated DataRiver session | private/no-store page gate; returns only eligible/reason/fixed role labels and Admin workspace-history capability, never token or raw group evidence |
| `GET /uploads?state=&limit=` | `registration.read` | bounded caller-authorized manifests after active-human Admin/Data Steward identity enforcement |
| `GET /uploads/{upload_id}` | `registration.read` | manifest, worker state, validation summary/failure code |
| `POST /uploads` | `registration.create` | create private multipart quarantine intent with an explicit format-only, dataset-description or typed catalog-metadata content profile |
| `GET /uploads/profiles/{content_profile}/template` | active human Admin/Data Steward | download the exact server-versioned header-only CSV/XLSX template; private/no-store, configuration-hash ETag and no browser-authored schema |
| `GET /uploads/metadata-vocabulary?kind=&q=&cursor=&limit=` | active human Admin/Data Steward | keyset-page at most 50 ACTIVE local DOMAIN/TAG/TERM UUIDs and display names; no provider URN, endpoint, Aspect or payload |
| `POST /uploads/metadata-vocabulary/sync` | active human security administrator + `catalog.sync` | reserve and reconcile one ordered DataHub kind page using `sync_id`, server cursor and `Idempotency-Key`; only a complete verified snapshot may inactivate unseen local entries |
| `POST /uploads/{upload_id}/parts` | `registration.create` | issue short-lived part URL |
| `POST /uploads/{upload_id}/complete` | `registration.create` | persist completion intent; returns `202` |
| `POST /uploads/{upload_id}/preparations` | `registration.read` + `registration.validate` | queue/reuse the server-owned typed configuration for an exact accepted manifest version; requires `If-Match` and `Idempotency-Key`, accepts no body |
| `GET /uploads/{upload_id}/preparations?state=&limit=` | `registration.read` | list bounded typed preparation state/progress without object coordinates or parser payload |
| `GET /uploads/{upload_id}/preparations/{preparation_id}` | `registration.read` | read one upload-scoped typed preparation with private no-store response |
| `GET /uploads/{upload_id}/preparations/{preparation_id}/candidates?cursor=&limit=` | `registration.read` + `catalog.read` + `change.create` | page immutable V2 submitted evidence and separately authorized current ACTIVE DATASET targets; private no-store, opaque cursor, no total or provider/object coordinates |
| `GET /uploads/{upload_id}/preparations/{preparation_id}/candidates/{candidate_id}/preview` | `registration.read` + `catalog.read` + `change.create` | revalidate exact candidate/receipt/object identity and current target, safely merge live `datasetProperties`, return only typed before/after evidence plus quoted preview ETag |
| `POST /uploads/{upload_id}/preparations/{preparation_id}/candidates/{candidate_id}/change-request` | `registration.read` + `catalog.read` + `change.create` | require preview `If-Match` and `Idempotency-Key`; atomically create one server-authored dataset-description CR item, outbox event and immutable candidate binding |
| `GET /uploads/{upload_id}/preparations/{preparation_id}/metadata-candidates?cursor=&limit=` | `registration.read` + `catalog.read` + `change.create` | page immutable V3 row groups and separately authorized current targets; emits only fixed record/candidate kinds, local counts/hashes and bounded field samples |
| `GET /uploads/{upload_id}/preparations/{preparation_id}/metadata-candidates/{candidate_id}/preview` | `registration.read` + `catalog.read` + `change.create` | re-read one current DataHub Aspect, resolve local vocabulary UUIDs server-side, apply a fixed compiler and return a bounded redacted diff plus preview ETag |
| `POST /uploads/{upload_id}/preparations/{preparation_id}/metadata-candidates/{candidate_id}/change-request` | `registration.read` + `catalog.read` + `change.create` | require preview `If-Match` and `Idempotency-Key`; atomically bind exactly one V3 group to one fixed-Aspect CR item and outbox event |
| `POST /uploads/{upload_id}/registration-proposals` | `registration.read` + `change.create` + `change.raw.create` | operator/recovery-only raw proposal from an `ACCEPTED` upload; not exposed in the ordinary UI and not accepted as typed-content binding |
| `POST /registration/bulk-preparations/execute` | `catalog.sync` purpose-bound service account only | claim and execute at most one due typed preparation under DB-time lease/retry fencing; requires Airflow-owned `X-Run-Id` plus ordinal `X-Run-Call` 1..8. The hashed call receipt is atomic with canonical claim/terminal state, so response-loss replay cannot consume later work; returns only opaque processing state/count |
| `POST /registration/manual-submissions` | `catalog.read` + `registration.create` | additive v1 contract for exactly one current dataset: legacy clients send the complete non-empty `columns` array, while current clients send sparse `column_edits` (including an empty array); exactly one shape is allowed. Both require `Idempotency-Key` and projection `source_version`; current clients also pin the 64-hex `provider_source_version`, while a legacy omission is resolved from the same fresh provider read. The server rehydrates the complete non-truncated provider schema before creating the immutable DB/CSV receipt; storage coordinates are never exposed |
| `GET /registration/manual-submissions?scope=mine|workspace&state=&cursor=&limit=` | `registration.read` active human Admin/Data Steward | private/no-store keyset history; Data Steward is owner-only, workspace scope is security-Admin-only; default 25, maximum 100 |
| `GET /registration/manual-submissions/{submission_id}` | `registration.read` active human Admin/Data Steward | exact owner/Admin report with at most 20 immutable attempts and five ordered aspect results per attempt |
| `POST /registration/manual-submissions/apply` | `catalog.sync` service account only | claim at most one durable MANUAL receipt, verify its private CSV hash/shape and provider source version, then hold one entity-wide DataHub mutation lock across all five typed apply/read-backs; requires Airflow-owned `X-Run-Id` plus ordinal `X-Run-Call` 1..10. The hashed call receipt is atomic with claim/terminal state and exact replay performs no second provider call; scheduled only by the paused Airflow DAG |
| `GET /catalog/vocabulary?kind=TAG|TERM|DOMAIN&q=&limit=` | `catalog.search` | bounded suggestions come only from the authorization-pruned synchronized workspace projection. An entered query may be one normalized character (unlike general catalog search's two-character minimum). Global DataHub vocabulary search is not unioned because its provider contract has no workspace/classification predicate; canonical provider-ref selection remains a governed server-side registration contract. |

Completion does not mean accepted. Durable states are `INITIATED → COMPLETION_QUEUED → COMPLETING → QUARANTINED → VALIDATING → ACCEPTED`, with terminal `REJECTED/ABORTED/EXPIRED`. Workers stream object bytes, compare declared size/SHA-256, apply bounded format rules, copy to the accepted bucket, commit canonical location, then best-effort clean quarantine.

The compatibility typed profiles are `DATASET_DESCRIPTION_CSV_V1` and
`DATASET_DESCRIPTION_XLSX_V1`. The V3 profiles are `CATALOG_METADATA_ROWS_CSV_V1` and
`CATALOG_METADATA_ROWS_XLSX_V1`; they use the exact ten-column
`record_kind,asset_id,platform,database_name,schema_name,table_name,field_path,operation,value_text,controlled_ref`
contract for table/column descriptions and DOMAIN/TERM/TAG changes. Controlled references are
Workspace-local UUIDs obtained from the no-store vocabulary route, never browser-supplied DataHub
URNs. The server maps each record kind to exactly one allowlisted Aspect and caps each grouped
column-description candidate at 1,000 operations and each controlled-reference candidate at 100.
CSV and XLSX compile to their profile-bound canonical evidence; header order and MIME/profile must
match exactly, and XLSX ZIP/XML relationships are attack-bounded.

All four executable typed profiles are limited
to 16 MiB, 10,000 rows, 64 KiB per logical row and 10,000 description characters. The compatibility CSV is
UTF-8-with-BOM-compatible with exact ordered headers
`asset_id,platform,database_name,schema_name,table_name,description`. Platform is bounded to 100,
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
staging/finalize path and typed candidate-to-change command use server-owned contracts. A `QUEUED`
preparation is still not an executable proposal; only a fenced `READY` V2 candidate can be previewed
and bound to one governed Change Request. For V3 publication the database reauthorizes the
initiating human and exact local target set against the current worker receipt/attempt/lease before
target validation, then performs a final transaction-locking reauthorization before writing any row
or candidate evidence. Candidate serialization uses a fixed 64 MiB attempt spool; overflow is
`EVIDENCE_TOO_LARGE`, not `SOURCE_HASH_MISMATCH`. At apply time it repeats current human, target, binding,
policy and worker-lease authorization immediately before every provider read/write; revocation
therefore yields zero provider calls. Public candidate/preview/CR responses do not expose provider
URNs, arbitrary Aspect names, raw provider documents or object coordinates.

The current BULK UI sends `content_profile` explicitly rather than relying on the server default.
Only an `ACCEPTED` typed dataset-description upload exposes preparation controls. It first reads
the no-store preparation list, then sends a bodyless create request with the exact quoted upload
manifest version and a new idempotency key. Format-only and failed/stale views expose no execution.
`READY` pages candidates at 20 (maximum 50), previews one current target and creates only the
ETag-fenced typed Change Request; it never exposes the raw proposal or direct DataHub update path.

### Change management

| Method/path | Action | Purpose |
|---|---|---|
| `GET /change-requests?state=&limit=` | `change.read` | compatibility route retaining the published v1 full-record list and overview envelope for existing consumers; private/no-store, maximum 100 |
| `GET /change-requests/summaries?state=&cursor=&limit=` | `change.read` | additive low-resource route used by the current UI: keyset-paged scalar summaries followed by one grouped current-target authorization; hidden, deleted and legacy-unbound targets are omitted; maximum 50 |
| `GET /change-requests/{id}` | `change.read` | exact selected aggregate only; hard caps are 200 items, 600 approvals, 200 transitions, 50 rounds and 200 test runs; current-target denial is existence-hiding 404 |
| `GET /change-requests/{id}/apply-report` | `change.read` | private/no-store fresh-authorized provider reconciliation evidence; at most 200 item results and 20 attempts, hashes/versions only |
| `POST /change-requests/{id}/attachments` | current `change.edit` target authorization | multipart upload with optional client-generated `upload_id`; precommits the exact ID, writes create-only provider bytes and returns private `202 STARTED`, never bucket/object key |
| `GET /change-requests/{id}/attachment-uploads/{upload_id}` | initiating current subject | private/no-store exact intent status for ambiguous response recovery |
| `GET /change-requests/{id}/attachment-uploads?round_id=&limit=` | initiating current subject | `round_id` required, limit 1–10; server filters the exact CR, round and STORED state before ordering/limit so historical rounds cannot starve recovery |
| `POST /change-requests/{id}/attachment-uploads/{upload_id}/finalize` | current `change.edit` target authorization | rechecks membership, deny rules, classification, System/Domain, TEST assignment, target binding and current CR round/version/state; FINALIZED replay repeats authorization and returns the same immutable attachment |
| `POST /change-requests` | `change.raw.create` + `change.create` | hardware-human operator/recovery raw DataHub Aspect proposal; absent from the ordinary UI |
| `POST /change-requests/intake` | `change.create` | ordinary v0.3-shaped CR registration: server re-reads authorized existing table/column identity, records typed multi-target intake evidence including a separate bounded `requested_change` note at table/column level, and server-mints any new-table proposal identifier; no provider mutation occurs |
| `POST /change-requests/{id}/approvals` | `change.review` / `change.approve` | append immutable decision |
| `POST /change-requests/{id}/transitions` | derived | legal user-controlled transition/retry |
| `POST /change-requests/{id}/complete-intake` | `change.review` | after independent final approval, records an accountable `COMPLETED` result for a non-executable intake; cannot create `APPLIED` |

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
| `POST /knowledge/graphs/{graph_id}/releases` | retired | always returns `410 Gone` with the `direct-release-retired` problem; governed changeset publication is the only release-creation route |
| `GET /knowledge/graphs/{graph_id}/releases` | `kg.read` | list immutable releases |
| `POST .../releases/{release_id}/activate` | `kg.publish` | atomically select/roll back active release |
| `GET /knowledge/graphs/{graph_id}/releases/{release_id}/snapshot?maximum_nodes=` | `kg.read` | ABAC-filtered release view |
| `GET .../{release_id}/export?format=json-ld|edge-list` | `kg.export` | release-pinned governed export |
| `POST .../{release_id}/analysis/neighbors` | `sharing.invoke` | typed bounded neighbor traversal |
| `POST .../sources/{upload_id}/analyze` | `kg.edit` | require `Idempotency-Key`, validate and pin one eligible source/configuration, enqueue a durable job and return `202`; no parsing or inference occurs in the request |
| `GET .../source-analysis-jobs?cursor=&limit=` | owner of the submitted job | active-first owner-scoped keyset page, `limit=1..100`; cursor binds workspace, graph, actor and ordering, no total is exposed, and enqueue caps non-terminal jobs at 20 per owner/graph |
| `GET .../source-analysis-jobs/{job_id}` | owner of the submitted job | return bounded state/stage/progress, attempt limits, version/timestamps, sanitized failure code and a result only after success |
| `POST .../source-analysis-jobs/{job_id}/cancel` | owner + `kg.edit` | require a positive-version `If-Match` and `Idempotency-Key`; queued/retry work cancels immediately, running work becomes `CANCEL_REQUESTED`, and terminal success is immutable |
| `POST .../releases/{release_id}/project` | `kg.publish` | rebuild a release-scoped Neo4j shadow and verify its canonical read-back hash before recording `SHADOW_VERIFIED` |
| `POST .../releases/{release_id}/graphrag` | `kg.read` + `chat.query` | bounded node/relationship evidence retrieval and citation-constrained local model answer |

Neighbor request accepts only `node_id`, `direction=IN|OUT|BOTH`, an edge-type allowlist, `maximum_hops<=3` and `maximum_nodes<=500`. It cannot contain SQL, Cypher, labels or clauses. Every published node/edge requires ontology membership, valid endpoints, classification and provenance.

PDF analysis accepts only an `ACCEPTED` `application/pdf` upload owned by the current actor, with
declared and observed SHA-256/size equality, a 50 MiB hard limit and PUBLIC/INTERNAL classification
within the graph envelope. The enqueue transaction pins source version/hash/classification, graph
version, explicit empty or exact governed active-release base, active ontology ID/checksum, parser
hash and secret-free loaded deployment or activated System Configuration Chat/Embedding binding
documents and hashes. The same
actor/key/request replays one job; key reuse with a changed actor, graph, upload or payload is a
conflict. Submission is unavailable when the separately credentialed worker capability is disabled.

Job states are `QUEUED`, `RUNNING`, `RETRY_WAIT`, `CANCEL_REQUESTED`, `SUCCEEDED`, `FAILED`,
`STALE` and `CANCELLED`; terminal states use stage `COMPLETED`. The response never includes attempts,
lease material, provider error bodies, secret references, endpoints, buckets or object keys.
Successful result fields are the DRAFT `changeset_id`, page/node/edge counts, evidence hash and
model identities. Model-proposed evidence must be an exact normalized substring of the referenced
parsed page; the excerpt/hash/page hash survive review and release through an opaque
`knowledge-source:<snapshot-id>#page=<n>` locator. The worker reauthorizes the requester and rejects
source, graph/base, ontology or activated-binding drift atomically before proposal persistence.
Projection and changeset publication are high-risk and retain the recent hardware-WebAuthn gate.
GraphRAG requires a DB projection receipt whose release hash matches the immutable release and
rejects citations outside the authorized node/relationship evidence package.

### API products and consumer grants

| Method/path | Action | Purpose |
|---|---|---|
| `POST/GET /api-products` | `sharing.manage` | create/list release-pinned product contracts |
| `POST /api-products/{id}/versions` | `sharing.manage` | create the next immutable contract draft |
| `POST .../versions/{version_id}/publish` | `sharing.publish` | strong-auth publish and deprecate prior current version |
| `POST/GET /api-products/{id}/grants` | `sharing.manage` | bind an active non-expiring service Subject + issuer + OIDC `client_id` to the current version with scope/classification/time/quota |
| `POST .../grants/{grant_id}/revoke` | `sharing.manage` | immediately revoke a grant |
| `POST .../{id}/authorize-invocation` | retired | `410 Gone`; authorization without a completed result never reserves quota |
| `POST .../{id}/invoke/neighbors` | `sharing.invoke` | atomic grant-metered bounded analysis; exact key/binding replays the stored `NEIGHBORS_V1` result |
| `POST .../{id}/invoke/snapshot` | `sharing.invoke` | atomic ABAC-filtered snapshot; exact key/binding replays the stored `SNAPSHOT_V1` result |
| `POST .../{id}/invoke/chat` | `sharing.invoke` | atomic deterministic pinned-release answer; exact key/binding replays the stored `CHAT_LOCAL_V1` result |

Product versions accept only the registered `SNAPSHOT`, `NEIGHBORS` or `CHAT` surfaces and supported
scopes. Credentials stay in the IdP/gateway; DataRiver stores Subject/issuer/client references, not
secrets. `Idempotency-Key` is 16..200 characters and persisted only as SHA-256. Request hash binds
the caller permission fingerprint, product/version/release/contract, surface/scope and canonical
payload. A completed exact replay returns the same invocation ID and body without quota; changed
binding conflicts. Result JSON is at most 1 MiB and all three result routes send
`Cache-Control: private, no-store`. Concurrent per-minute or monthly admission permits only the
bounded winner; a rejected call records no ledger, result or aggregate increment.

### Chat

| Method/path | Action | Purpose |
|---|---|---|
| `POST /chat/query` | `chat.query` plus `catalog.read` / `kg.read` per citation | persist a question and authorized-evidence answer; development may use local Ollama or one allowlisted private OpenAI-compatible fixed tool contract, while all cited chunk IDs are revalidated server-side |

Request is `{session_id?,question,maximum_evidence<=10}`. Response carries session/message IDs, answer and immutable evidence chunk metadata: `chunk_id`, resource/workspace-authorized classification and typed scope, source type/locator/version, SHA-256 content hash, effective interval and extraction method. Composer citations must be a non-empty, duplicate-free subset of the exact authorized chunk input and pass hash/workspace revalidation; any forged, empty or invalid citation fails closed to the exact answer `검증 불가` with no returned/persisted evidence. The baseline deliberately has no external LLM.

Final persistence requires a workspace ACTIVE retention-policy version. A new session binds the
exact policy ID/hash, database transaction time and policy-derived deadline in one locked
transaction. Missing active policy returns `409`; a legacy-unbound, expired or superseded-policy
session also returns `409` and the caller must start a new session. These failures persist no Chat
session/message. Policy activation is available only through the independent retention
maker-checker API; there is no Chat-specific duration parameter or fallback. The local
host-development launcher may explicitly enable a security-administrator-only
`EPHEMERAL_NO_STORE` response: it still performs Chat and evidence ABAC, but creates no session,
message, citation or retention binding and production configuration rejects the mode.

### Administrator membership access

Access Role write documents accept optional `data_access_rules`, with no more than one rule for each
classification. A granted rule requires non-empty residency and processing-purpose scope; Partial
requires exactly one MASK/REDACT/TOKENIZE treatment; No Access accepts neither treatment nor scope.
Responses return the exact current Role-version rules. Omitting a classification is a fail-closed
missing rule, not inheritance. For compatibility with existing typed clients, omitting the entire
`data_access_rules` field on Role update preserves the exact current rules; an explicit empty
array creates a new Role version with no rules and therefore default denial. Explicit `null` is
rejected. Rule arrays are normalized before both storage and canonical hashing, so semantically
identical region/purpose permutations produce identical evidence. Existing catalog authorization remains the intersection of ABAC,
classification policy and RLS; this contract does not expose source-row data or a masking bypass.

| Method/path | Assurance/authorization | Purpose |
|---|---|---|
| `GET /admin/me` | eligible human security administrator with a valid current OIDC identity | internal subject identity, current-assurance operations, fallback availability and the supported action vocabulary; read discovery never grants mutation authority |
| `GET /admin/workspace-memberships?q=&status=&limit=&cursor=` | eligible human security administrator with a valid current OIDC identity | workspace/filter-bound keyset page of membership display/version summaries, maximum 100 |
| `POST /admin/identity-users` | eligible human security administrator + recent hardware WebAuthn + enabled governed Keycloak adapter | idempotently create a disabled marked Keycloak identity, temporary `UPDATE_PASSWORD` credential and canonical six-month Workspace membership, optionally from an active Role, then enable the identity. The password is excluded from request hash, DB, outbox and response. |
| `GET /admin/workspace-memberships/me/summary` | current active member | server-calculated membership expiry, renewal opening and pending-request facts; browser time is not authorization input |
| `POST /admin/membership-renewals/me` | current member during the final 30 days + `Idempotency-Key` | request exactly six calendar months beyond the observed current expiry; one pending request per member |
| `GET /admin/membership-renewals/me?limit=&cursor=` | current member | bounded own renewal keyset history |
| `GET /admin/membership-renewals?state=&limit=&cursor=` | eligible global administrator | bounded shared pending/history keyset queue for all eligible administrators |
| `POST /admin/membership-renewals/{request_id}/decisions` | independent eligible global administrator + recent hardware WebAuthn + `If-Match`/`Idempotency-Key` | approve/reject; approval atomically verifies and extends the membership expiry |
| `GET /admin/access-roles?q=&status=&limit=&cursor=` | eligible human security administrator with membership-read capability | bounded workspace/filter-bound Role page with current assignment counts and exact four-class rules |
| `POST /admin/access-roles` | `admin.manage` + recent hardware WebAuthn | create one workspace Role from the typed action vocabulary and bounded System/Domain UUID scopes; credentials and arbitrary policy expressions are not accepted |
| `PUT /admin/access-roles/{role_id}` | `admin.manage` + recent hardware WebAuthn + quoted `If-Match` | update display metadata or an unused Role's security definition; the Role key is immutable and security changes fail while assigned |
| `DELETE /admin/access-roles/{role_id}` | `admin.manage` + recent hardware WebAuthn + quoted `If-Match` | deactivate an unassigned Role; no row or audit evidence is deleted |
| `PUT /admin/workspace-memberships/{subject_id}/role` | `admin.manage` + recent hardware WebAuthn | assign one active Role, or remove it, by materializing the governed membership access document; requires `If-Match` and `Idempotency-Key` and prohibits self-change |
| `GET /admin/systems?q=&status=&limit=&cursor=` | eligible human security administrator with a valid current OIDC identity | bounded canonical System page with active state, System version and set-based assignee count; assignment rows are not embedded |
| `GET /admin/systems/{system_id}/assignees?limit=&cursor=` | eligible human security administrator with a valid current OIDC identity | System-version-bound keyset page of Developer/Data Steward assignments |
| `PATCH /admin/systems/{system_id}/assignees` | `admin.manage` + recent hardware WebAuthn | apply disjoint assignment `upserts`/`removals`, maximum 100 combined; requires `If-Match` and `Idempotency-Key`, locks the System/targets, rejects missing or identical-only changes, validates the complete resulting lanes, emits one audit event and returns the new System version/`ETag` |
| `PUT /admin/systems/{system_id}/assignees` | `admin.manage` + recent hardware WebAuthn | compatibility complete replacement under the same lane, version, idempotency and audit invariants; the Admin browser uses `PATCH` |
| `GET /admin/system-configuration` | eligible human security administrator with a valid current OIDC identity | fixed server-owned inventory for PostgreSQL, OIDC, separate Redis cache/delivery, S3, DataHub and feature connectors. Every item includes `category`, `requirement` (`BOOTSTRAP_REQUIRED`, `CORE_CONNECTOR`, `FEATURE_CONNECTOR`), description, ordered `connection_requirements[{key,label,required,secret,example}]`, management plane, exact saved/TEST/activated/API-loaded versions and restart scope. Deployment-managed bootstrap entries are read-only. Development templates contain only non-secret values and strict mounted-secret reference names. |
| `GET /admin/system-configuration/{system_id}/versions?limit=` | eligible human security administrator in development, `SYSTEM_CONFIGURATION_READ` | newest-first bounded revision history (maximum 100) containing configuration hash, creator, fixed TEST evidence and activation evidence. It returns no endpoint, YAML document or credential value. Deployment-managed bootstrap entries have no database history route. |
| `PUT /admin/system-configuration/{system_id}` | eligible human security administrator in development, `SYSTEM_CONFIGURATION_UPDATE`, quoted `If-Match` | save a new immutable YAML revision. Literal sensitive values are rejected; only `file:/run/secrets/<name>` references are accepted. This route is unavailable outside development. |
| `POST /admin/system-configuration/{system_id}/test` | eligible human security administrator in development, `SYSTEM_CONFIGURATION_UPDATE` | test the exact saved current revision through one server-owned fixed connector probe and persist bounded evidence. Redis uses authenticated `PING`; other scopes remain fixed and typed. The request cannot supply a URL or command. Availability is not activation or process readiness. |
| `POST /admin/system-configuration/{system_id}/activate` | eligible human administrator in development, recent hardware WebAuthn, `SYSTEM_CONFIGURATION_ACTIVATE`, quoted `If-Match` | select the current AVAILABLE revision for next startup. Fails when no typed runtime consumer exists; never hot-reloads or restarts API/workers. |
| `GET /admin/workspace-memberships/{subject_id}/access` | eligible human security administrator with a valid current OIDC identity | exact typed full access document plus display metadata, membership version and matching `ETag` |
| `PUT /admin/workspace-memberships/{subject_id}/access` | `admin.manage` + recent hardware WebAuthn | exact full access-document replacement for another subject |
| `GET /admin/fallback/workspace-membership-access-requests?state=&limit=&cursor=` | eligible human security administrator with a valid current OIDC identity | bounded workspace/state-bound fallback keyset queue |
| `POST /admin/fallback/workspace-membership-access-requests` | eligible human security administrator + recent password reauth | create a five-minute typed maker request |
| `POST .../{request_id}/decisions` | independent eligible human checker + recent password reauth or hardware WebAuthn | append approve/reject evidence |
| `POST .../{request_id}/consume` | original maker + recent password reauth | atomically apply the approved command once |

Membership assignment and fallback mutations require `Idempotency-Key`; every replacement or
decision requires a quoted positive `If-Match`. Role-definition creation is bounded by the
workspace/key uniqueness contract; Role update/deactivation uses optimistic `If-Match` and appends
outbox audit evidence. The fallback create request's
version is the target membership version; decision and consume versions are the fallback aggregate
version. The only command is `WORKSPACE_MEMBERSHIP_ACCESS_UPDATE_V1` with `active`, `clearance`,
groups, allowed/denied actions and bounded system/domain UUID scopes. Manual/fallback documents
reject every `datariver-role-*` group; only the dedicated Role-assignment route may create or remove
that server-managed compatibility marker together with normalized assignment evidence. The marker
must match the locked Role row; an exact same Role/version/canonical-access request is rejected as a
no-op rather than recorded as `REASSIGNED`. The assignment access hash is
the canonical materialized access document and deliberately excludes the optimistic
`expected_membership_version`; changing only the expected version cannot manufacture a new Role
assignment. The Phase 3 editor displays the normalized assignment status and disables generic
manual/fallback editing for Role-bound or unverifiable legacy evidence. The Role must be removed or
repaired through the dedicated route first; the backend retains the same fail-closed enforcement.
Unknown fields and unknown actions are rejected. Maker, checker and target must be
distinct; self-access mutation is forbidden.
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
feature flag and effective retention/Legal-Hold/erasure action grants and denies. Hardware mutation
operations are advertised only while `authentication_time` is present, not future-dated and within
the deployed high-risk age. Role create/update/deactivate independently re-authorize `admin.manage`,
lock and recheck the current human administrator membership, and bind the decision ID and assurance
to their outbox event. Clients use it to
avoid exposing or preloading unrelated administration surfaces; every mutation still performs its
operation-specific authorization and maker/checker/target validation.

### Classification access and inference-provider administration

| Method/path | Assurance/authorization | Purpose |
|---|---|---|
| `GET /admin/classification-access/policies?state=&limit=&cursor=` | eligible human security administrator | list bounded state-bound policy versions |
| `GET /admin/classification-access/policies/current` | eligible human security administrator | return the active four-class policy or null |
| `GET /admin/classification-access/policies/{policy_id}` | eligible human security administrator | return one exact policy version and `ETag` |
| `POST /admin/classification-access/policies` | recent hardware WebAuthn | propose exactly four Search/Chat rules |
| `POST /admin/classification-access/policies/{policy_id}/decisions` | independent checker + recent hardware WebAuthn | approve/activate or reject a policy |
| `GET /admin/classification-access/restricted-search-grants?state=&subject_id=&limit=&cursor=` | eligible human security administrator | list bounded policy-bound grants |
| `GET /admin/classification-access/restricted-search-grants/{grant_id}` | eligible human security administrator | return an exact grant and `ETag` |
| `POST /admin/classification-access/restricted-search-grants` | recent hardware WebAuthn | propose a typed resource/system/domain grant; the server binds the active policy ID/hash |
| `POST /admin/classification-access/restricted-search-grants/{grant_id}/decisions` | independent checker + recent hardware WebAuthn | approve or reject the bound grant |
| `POST /admin/classification-access/restricted-search-grants/{grant_id}/revocations` | recent hardware WebAuthn | revoke a grant immediately |
| `GET /admin/inference/provider-profiles?profile_key=&state=&limit=&cursor=` | eligible human security administrator | list server-registered immutable profile versions; `profile_key` is exact |
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
| `GET /admin/retention/policies?state=&limit=&cursor=` | `retention.read` | list bounded policy versions and explicit disabled automation state |
| `GET /admin/retention/policies/current` | `retention.read` | return the workspace ACTIVE version or null |
| `POST /admin/retention/policies` | `retention.manage` + recent hardware WebAuthn | propose typed durations as runtime policy data |
| `POST .../policies/{policy_id}/decisions` | independent `retention.manage` checker + recent hardware WebAuthn | approve/activate or reject; atomically supersede the previous ACTIVE version |
| `GET /admin/retention/legal-holds?state=&limit=&cursor=` | `retention.read` | list bounded hold summaries; action arrays are omitted and `action_history_truncated=true` states that detail is required |
| `GET /admin/retention/legal-holds/{hold_id}` | `retention.read` | return the exact hold with at most the newest 100 append-only actions and an explicit truncation flag |
| `POST /admin/retention/legal-holds` | `legal_hold.place` + recent hardware WebAuthn | place a typed hold immediately |
| `POST .../legal-holds/{hold_id}/release-requests` | `legal_hold.release` + recent hardware WebAuthn | create a version-bound release request |
| `POST .../legal-holds/{hold_id}/release-decisions` | independent `legal_hold.release` checker + recent hardware WebAuthn | approve or reject release |
| `GET /admin/retention/erasure-requests?state=&limit=&cursor=` | `retention.read` | list bounded Maker-Checker requests; approval is not execution |
| `GET /admin/retention/erasure-requests/{erasure_request_id}` | `retention.read` | return the exact request snapshot and quoted version |
| `GET /admin/retention/erasure-requests/{erasure_request_id}/execution-evidence` | `retention.read` | return private/no-store archive-only command, attempt, receipt and event evidence without provider credentials or implying deletion |
| `POST /admin/retention/erasure-requests` | `erasure.request` + recent hardware WebAuthn | request review for a typed canonical target; the server resolves owner, version and classification |
| `POST .../erasure-requests/{erasure_request_id}/decisions` | independent `erasure.approve` checker + recent hardware WebAuthn | approve or reject after re-reading target, policy and applicable Legal Holds |

Every mutation requires `Idempotency-Key`; decisions and release commands also require a quoted
positive `If-Match`. Policy proposal input retains the legacy `rules` object for V1 compatibility
and may add a strict `contract`. A V2 contract contains `effective_from`, optional
`effective_until`, `execution_authorization_hours` from 1 through 168 and exactly four
`class_rules`: one each for `COMPLETED_OPERATIONS`, `CHAT_CONTENT`, `AUDIT_EVIDENCE` and
`OBJECT_DATA`. Each class rule supplies `unit` (`DAYS`, `MONTHS` or `YEARS`), non-negative
`minimum`, positive `maximum >= minimum`, and `archive_disposition` (`NO_ARCHIVE`,
`EVIDENCE_ONLY` or `CONTENT_WORM`). The response returns `contract_version` and the exact contract;
legacy rows return `SINGLE_DEADLINE_V1` and `contract: null` and cannot enter execution.
For `POLICY_BOOK_V2`, legacy `rules.chat_content_days` is the default session scheduling deadline and
must be inside the V2 `CHAT_CONTENT` minimum/maximum bounds. Execution eligibility uses the V2 Chat
minimum; immutable execution evidence uses the V2 `AUDIT_EVIDENCE` maximum from the frozen planning
basis. No numeric field is interpreted as deletion authority.

List responses never expand per-row Legal Hold or erasure approval history. Exact detail reads return
at most the newest 100 actions/approvals in chronological order and set the corresponding
`*_history_truncated` flag when older evidence exists.

Policy durations have no source default and are covered by a canonical payload hash. Legal Hold
placement and every release action have separate canonical hashes. Placement is
conservative and immediate; release requires a different human checker. Service identities are
denied. All responses expose `DISABLED_NOT_READY` for automatic partition/deletion effects, and
there is no delete, execute, consume, partition-detach or archive-verification endpoint in this
slice. Erasure request input cannot contain classification, owner, target version, object location,
SQL or provider commands. Approval rechecks the canonical target version/owner/classification, the
active policy ID and payload hash, and workspace/resource/subject Legal Holds. Rejection can close a
stale or expired request, but it never enables execution.

The optional internal `retention-archive` worker profile is not an HTTP capability. When explicitly
enabled with dedicated principals and a verified WORM target, it may create one archive-only command
for an approved Chat-session request under an effective `POLICY_BOOK_V2` contract. It records only
minimal approval/execution evidence and can end at
`ARCHIVE_VERIFIED_DESTRUCTIVE_DISABLED`, `BLOCKED` or `RETRY_WAIT`. There is no client-supplied
object key, provider command, retry endpoint or destructive state. Capability attestation,
conditional object create and expired-lease read-only reconciliation are internal worker contracts;
no HTTP caller can supply an attestation ID or trigger a recovery fence.

## DataHub adapter contract

The inward port exposes `scan_assets`, `get_asset`, `get_lineage`, `apply_change`, `read_aspect` and `capability`. Current HTTP routes use scan, detail, apply/reconcile and capability. Queries and proposal shapes are constants. The adapter classifies authentication, contract, rate-limit, network and provider failures without returning provider payloads or tokens.

`DATAHUB_EXPECTED_VERSION` supplies the exact stable DataHub release for a deployment; the current
example contract is `v1.6.0`. The adapter reads `/config.versions["acryldata/datahub"].version`; a
different or missing value degrades capability. `DATAHUB_ALLOWED_VERSIONS` is empty by default and may
contain only an explicitly reviewed numbered RC for that exact configured release (for example,
`v1.6.0rc1` for `v1.6.0`). Snapshot, head, latest, partial values and RCs from any other release line
are rejected during configuration. Production enforcement blocks enrichment, scan, apply and read-back
with sanitized `VERSION_MISMATCH`. This runtime check complements, rather than replaces, digest pinning
and live contract tests in the external DataHub deployment.

### Managed catalog export invariants

The API never accepts an object coordinate, provider endpoint, arbitrary column list, cursor or raw
query language for export. Creation persists a canonical request hash plus permission,
classification-policy, built-in-policy, format-safety and projection snapshots in the same transaction
as its job, outbox event and idempotency result. The worker reads only the local authorized
projection, always excludes `RESTRICTED`, emits one fixed CSV or XLSX column schema, fails closed on stale
snapshots and uses an attempt-unique private object key. Row, record and object-byte ceilings are
enforced. A stale/superseded lease cannot complete or overwrite a newer attempt.

Status is requester-owned. Download repeats authorization and snapshot checks, reconciles the stored
size, request metadata and provider ETag, and returns no storage coordinate other than the bounded
presigned URL. The runtime toggle defaults off. Enabling it without separate DB and S3 principals is
configuration-invalid; the checked-in local stack intentionally has no such credentials yet.

## Planned compatibility endpoints

The remaining backlog, not present in current OpenAPI, is upload cancel/download and any destructive
erasure execution; Mode A ontology generation and database/dynamic one-pass source ingestion; Chat
session history/SSE and production external-model adapters; general archive-range export plus
job/audit browsing/retry. The
internal Phase 2 worker can persist verified approval evidence, but no archive or deletion capability
is exposed to clients. The catalog-export source/API/UI contract exists but its isolated worker
deployment remains disabled pending separately provisioned credentials. The disabled-first assistant
inference source contract is not a production external-provider claim. The durable PDF worker uses
the fixed deployment/System Configuration bindings already loaded at startup; there is no
browser-created provider profile, endpoint or credential route. Backlog features may not be emulated
with generic provider or arbitrary query pass-through.
