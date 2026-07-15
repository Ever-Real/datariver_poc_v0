# Feature specification

## Common interaction contract

All screens expose loading, empty, success, stale/degraded, validation, unauthorized, forbidden, conflict, rate-limited, and retryable-failure states. Destructive or publish actions require an explicit summary confirmation. Long tasks return a job link and update through bounded polling or authorized SSE. UI state never invents successful backend state.

## Catalog search and discovery

- Search text, domains, platforms, owners, tags, glossary terms, certification, quality, freshness, classification and lifecycle filters.
- Cursor pagination with server-enforced ABAC before enrichment.
- Detail includes canonical URN, description, schema, ownership, glossary, quality, freshness, lineage and explicit `observed_at`/`stale_at`.
- Saved filters are per subject/workspace; export requires separate `catalog.export` permission.
- No catalog read endpoint mutates DataHub.

Acceptance: hidden assets do not alter total count, autocomplete, facets or cursor sequence; DataHub credentials never reach the browser.

## Registration management

1. Request a multipart upload session after `registration.create` authorization.
2. Browser uploads directly to a quarantine object key.
3. Complete call supplies size, MIME and SHA-256; server verifies object metadata.
4. Validation job streams the object, scans it, detects structure, and produces row-level errors plus normalized preview.
5. User selects allowed changes and creates a registration/change request.
6. Approval and application follow the governance workflow.

Uploads can be aborted, expire automatically, and cannot be downloaded with an old authorization decision. Validation never equals approval.

## Change management

State machine:

```text
REGISTERED → IN_REVIEW → TESTING → FINAL_REVIEW → APPLY_QUEUED
→ APPLYING → APPLIED
                 └→ APPLY_FAILED → APPLY_QUEUED (authorized retry)
Any pre-apply review state → REJECTED or CANCELLED under policy
```

- Each transition declares allowed prior state, action, required evidence and actor separation.
- Requester cannot be final approver; high-classification changes require two distinct approvers and strong authentication.
- Optimistic `version` prevents lost updates.
- `APPLIED` requires target aspect re-read and content-hash match.
- Every attachment download and transition receives a fresh ABAC decision and audit event.

## Monitoring and operations

- Capability cards for API, PostgreSQL, DataHub, cache, queue, object storage, graph, LLM, Airflow and policy.
- Health is `healthy`, `degraded`, `unavailable`, or `unknown`; an unrelated unavailable capability does not blank the whole UI.
- Job explorer shows attempts, retry class, correlation, external response hash and DLQ status without secret payloads.
- Operator replay is an audited command that creates a new attempt; it does not rewrite history.

## Knowledge Graph Studio

- Create graph and versioned ontology; import DataHub scope or uploaded sources.
- Extraction produces proposals with provenance/confidence, never direct mutations.
- Changeset editor supports node/edge add, update, remove, diff, comments and validation.
- Validation checks ontology, referential integrity, duplicate identity, provenance, policy attributes and bounded quality rules.
- Review and publish create immutable releases; active pointer rollback selects a prior verified release.
- Compare releases and export authorized JSON-LD or CSV edge lists.
- Projection status is visible and rebuildable from release content.

## Chat and analysis

- Conversation is workspace-bound with retention policy and explicit deletion.
- User chooses catalog, graph and optional release scope only from authorized resources.
- Retrieval filters before LLM invocation. Responses include evidence cards, source locator, observed/release version and whether data is stale.
- Prompt/model/tool metadata are audited without logging raw secrets or confidential content by default.
- Graph questions use registered typed query templates; generated raw Cypher is rejected.
- If the LLM is unavailable, evidence results remain accessible as a degraded response.

## API product sharing

- Publisher selects immutable graph release, registered query template, JSON schema, quota plan and expiration.
- Consumer client obtains a scoped grant; credentials are managed by gateway/IdP and only references are stored.
- Every invocation enforces workspace/share grant, template bounds, timeout, row/hop limit and records usage.
- Revocation invalidates the policy version and cached grant within the documented TTL.

## Administration

- Manage workspace, membership reference and subject/resource attributes.
- Policy changes are versioned, linted, tested against fixtures, approved and atomically activated.
- Connection configuration stores endpoints/capabilities and `secret_ref`, not plaintext credentials.
- Audit search/export is separately authorized and immutable to normal admins.

## Accessibility and convenience

- Complete keyboard navigation, semantic landmarks, focus restoration, accessible errors and minimum AA contrast.
- Stable URLs for search/detail/request/graph/job; filters encoded in URL where safe.
- Unsaved editor changes are guarded; large lists virtualize without breaking accessibility.
- Korean is the first UI locale; user-visible strings use an i18n catalog and English fallback.
