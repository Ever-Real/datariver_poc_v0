# Feature specification

## Common interaction contract

All screens expose loading, empty, success, stale/degraded, validation, unauthorized, forbidden, conflict, rate-limited, and retryable-failure states. Destructive or publish actions require an explicit summary confirmation. Long tasks return a job link and update through bounded polling or authorized SSE. UI state never invents successful backend state.

The shared shell follows the controlled v0.3 parity contract: 56-pixel navy GNB; compact scrollable primary menus; a capability-filtered administrator profile menu; optional server-validated auxiliary-system links; an 80-pixel page title; two-pixel edges; and a 1,800-pixel operational canvas. Dense data uses the shared TanStack table, cursor pagination, no-wrap ellipsis with keyboard-readable full text, accessible Dialog/Accordion semantics, and drawer behavior below the desktop breakpoint.

## Catalog search and discovery

- Literal multi-term search uses explicit ALL semantics across full text, name and description; `%`, `_` and backslash remain data rather than wildcard syntax. Domains, platforms, owners, tags, glossary terms, certification, quality, freshness, classification and lifecycle are the target filter set; the current facade exposes asset type, platform, classification and lifecycle.
- Cursor pagination with server-enforced ABAC before enrichment.
- An active human security administrator with `RESTRICTED` clearance and explicit
  `catalog.search`, `catalog.read` and `admin.manage` grants may use the audited ADR-0020 review
  scope to discover non-deleted quarantined projections in the current workspace for classification
  remediation. Ordinary users retain the normal lifecycle/classification scope. This read-only
  scope does not include export, Chat, attachment, arbitrary provider or mutation access; the
  existing typed DataHub metadata enrichment for catalog detail remains available.
- The Resource Tree lazily pages canonical `platform -> database -> schema -> asset` branches. Hierarchy is projected only from typed source containers and is never inferred by splitting an external URN.
- Detail includes canonical URN, description, schema, ownership, glossary, quality, freshness, lineage and explicit `observed_at`/`stale_at`. Current detail exposes the fixed-contract schema/ownership/glossary/quality fields returned by DataHub and bounded depth-1..3 lineage.
- Lineage candidate nodes and every intermediary are set-filtered through the same workspace/classification/scope authorization. A hidden intermediary truncates the path; visible endpoints are never reconnected across it.
- Saved filters are per subject/workspace; export requires separate `catalog.export` permission. The
  managed CSV job binds the normalized query/filter/sort, subject permission scope,
  classification-access snapshot, built-in policy version, CSV safety version and projection
  watermark. RESTRICTED is never exportable, including with a Search grant.
- No catalog read endpoint mutates DataHub.

Acceptance: hidden assets do not alter branch counts, autocomplete, facets, cursor sequence or an
export artifact; response paging does not expose a hidden global total; DataHub credentials and
object coordinates never reach the browser. Export is generated page-by-page by a separately
credentialed worker, fails if its security/source snapshot changes, neutralizes spreadsheet formula
execution, and reauthorizes a completed artifact before issuing a 60-second download URL. The
source/API/UI contract is implemented disabled-first; deployment enablement requires the isolated
DB/S3 principal gate. The browser must not crawl result pages as a substitute.

## Registration management

Manual metadata registration is a distinct workflow, not a Change Request.  After an authorized
user selects one DataHub dataset, the browser receives current table and field metadata through the
catalog detail facade and may edit Description, one Domain, Tags and Terms for the table and each
field.  Controlled values accept comma/Enter/Tab creation and permission-pruned existing-vocabulary
suggestions.  On Save, the server rechecks the active target, source version, schema field set and
`catalog.read` plus `registration.create`, then records immutable typed intent and a server-written
CSV receipt.  The browser receives only an opaque submission ID, status and serial; it never sees a
MinIO object key, an Airflow endpoint or a DataHub credential.  The configured InfoSchema bucket is
deployment-owned and has no source-code fallback.  The paused Airflow worker streams and hash-checks
that private CSV, then performs typed DataHub read–merge–read-back for table/column metadata.  Save
is shown as `QUEUED`; only a complete provider read-back becomes `APPLIED`.  Deployment activation
and a real Airflow/object-store/DataHub acceptance run remain separate runtime gates.

1. Request a multipart upload session after `registration.create` authorization.
2. Browser uploads directly to a quarantine object key.
3. Complete call supplies size, MIME and SHA-256; server verifies object metadata.
4. Validation job streams the object, scans it, detects structure, and produces row-level errors plus normalized preview.
5. User selects allowed changes and creates a registration/change request.
6. Approval and application follow the governance workflow.

Uploads can be aborted, expire automatically, and cannot be downloaded with an old authorization decision. Validation never equals approval.

The first typed BULK profile is an all-or-nothing dataset-description CSV. Its source-only parser
uses bounded async chunks, strict UTF-8 and CSV states, exact ordered headers, canonical lowercase
asset UUIDs, projection-compatible identity limits, duplicate rejection and exact source/candidate
hashes. It preserves description content, including an empty clear proposal and quoted newlines.
No runtime worker is wired. A separately published `READY` receipt can be inspected through a
bounded read-only candidate API: it revalidates V2 receipt/hash invariants, resolves the page of
targets in one authorization-pruned ACTIVE DATASET batch and exposes immutable submitted identity
separately from the current projection. Any legacy, missing, denied or identity-drifted target makes
the whole page unavailable without disclosing which row failed. Attempt-local staging must still be
atomically fenced before a receipt or candidate can become visible.

The BULK browser preserves the v0.3 300-pixel upload panel and dark workflow tracker while replacing
client-side parsing and simulated updates with server truth. It sends the explicitly selected profile
on upload initiation, lists/creates preparation only for an `ACCEPTED` typed source, uses the exact
quoted manifest `If-Match` and a fresh idempotency key, and displays indeterminate progress until the
server reports a row count. `READY` enables read-only candidate evidence only; no raw Aspect,
change-request or DataHub mutation action is exposed until the governed command contracts exist.

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
- The dashboard's legacy asset card layout is backed by the current typed DataHub projection: total non-deleted assets and non-blank description coverage, plus a bounded platform/database/schema breakdown. Tags, glossary mappings, quality scores, time-window history and audit rows are not manufactured when their governed read model is absent; their visible cards state that the metric is not collected under the current contract.
- Monitoring restores the legacy full-height observability panel and refresh control using the authenticated capabilities response. A configured server-validated Grafana link opens as an external page; iframe embedding remains disabled until the deployment supplies approved origin, SSO and CSP/sandbox evidence.
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

- Conversation is workspace/owner-bound and persists only under an exact active retention-policy
  ID/hash and policy-derived deadline. Legacy, expired and superseded-policy sessions are
  append-closed. Explicit deletion remains governed backlog and is not a current Chat command.
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
