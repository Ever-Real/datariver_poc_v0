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
- Detail includes canonical URN, description, schema, ownership, glossary, quality, freshness, lineage and explicit `observed_at`/`stale_at`. Type and classification badges, URN and copy action share one compact line. Top-level `Table Details` and `Lineage` tabs separate the metadata accordions from the lazy bounded depth-1..3 graph; column metadata is an accordion within `Table Details`. The table detail summary presents platform/database/schema/domain then owner/rows/size/created date in four-column rows, followed by full-width description and side-by-side terms/tags, without exposing source version as a display field. The catalog renders authorized lineage top-to-bottom (`upstream 2 → upstream 1 → current → downstream 1 → downstream 2`) on a pale grid canvas whose viewport is strictly constrained to the current detail-pane width and initially fits its content. The fixed-coordinate canvas is isolated from its ancestors' inline-size calculation, so changing tabs cannot widen the URN, tabs, accordion, or page and cannot create a horizontal scrollbar; widening the pane only gives its contents more available width. A stage retains every node, placing at most three columns on each row before continuing on the next row. Users may pan the canvas, reposition a node from its border or fixed-width stage badge, and zoom with controls or Ctrl-wheel; clicking the table/view name always opens its authorized local detail. A node's `상세` action opens the actual DataHub Lineage page only through a server-built, deployment-allowlisted URL; the sandboxed frame relies on DataHub's own SSO/guest session and never receives a DataRiver credential or DataHub service token.
- Lineage candidate nodes and every intermediary are set-filtered through the same workspace/classification/scope authorization. A hidden intermediary truncates the path; visible endpoints are never reconnected across it.
- Saved filters are per subject/workspace; export requires separate `catalog.export` permission. The
  managed CSV job binds the normalized query/filter/sort, subject permission scope,
  classification-access snapshot, built-in policy version, CSV safety version and projection
  watermark. RESTRICTED is never exportable, including with a Search grant.
- No catalog read endpoint mutates DataHub.
- Full reconciliation reserves one workspace page before reading DataHub, keeps provider cursors
  server-only, resumes Airflow retries from the persisted public page ordinal and reduces an
  oversized provider response down to a one-entity page. Missing-row deletion remains disabled
  without accepted point-in-time evidence.

Acceptance: hidden assets do not alter branch counts, autocomplete, facets, cursor sequence or an
export artifact; response paging does not expose a hidden global total; DataHub credentials and
object coordinates never reach the browser. Export is generated page-by-page by a separately
credentialed worker, fails if its security/source snapshot changes, neutralizes spreadsheet formula
execution, and reauthorizes a completed artifact before issuing a 60-second download URL. The
source/API/UI contract is implemented disabled-first; deployment enablement requires the isolated
DB/S3 principal gate. The browser must not crawl result pages as a substitute.

## Registration management

Registration fails closed at the page boundary. Before either workbench loads an upload,
submission, candidate or report, the browser requests a private/no-store capability for the current
DataRiver session. Only an active human security administrator or canonical Data Steward is
eligible; inactive, service and all other identities render an unavailable state and cause no
Registration resource request. A Data Steward sees only their Manual history, while a security
administrator may explicitly switch to bounded workspace history.

Manual metadata registration is a distinct workflow, not a Change Request.  After an authorized
user selects one DataHub dataset, the browser receives current table and field metadata through the
catalog detail facade and may edit Description, one Domain, Tags and Terms for the table and each
field. Existing controlled values remain on one horizontally scrollable badge line with thin
previous/next controls. A compact far-right `+` opens a small floating search/input surface directly
below that same input. A user may select a permission-pruned existing-vocabulary suggestion first,
or add a comma/Enter/Tab-delimited new Tag/Term as governed proposal intent when no suitable value
exists. A badge exposes its remove action only on hover or keyboard focus. The browser retains only
the current provider page (at most 100 fields) plus a sparse map of changed field values. On Save,
the server rechecks the active target, the catalog projection version and the provider canonical
version, reads a fresh complete/non-truncated provider schema, overlays only the sparse edits and
reauthorizes `catalog.read` plus `registration.create`. It then records the complete final snapshot
as immutable typed intent and a server-written CSV receipt using conditional object creation. The
browser receives only an opaque submission ID,
status and serial; it never sees a MinIO object key, an Airflow endpoint or a DataHub credential.
The configured InfoSchema bucket is deployment-owned and has no source-code fallback. The paused
Airflow worker invokes DataRiver with a purpose-bound service identity; DataRiver streams and
hash-checks the private CSV, then performs typed DataHub read–merge–read-back for five fixed aspects.
Database-time leases, a maximum of 20 attempts and one active apply per asset fence retries. Save is
shown as `QUEUED`; only five matching read-backs become `APPLIED`. The workbench polls a bounded
status/history page for at most 20 checks/120 seconds, stops while hidden, aborts stale requests and
displays append-only attempt/aspect evidence without provider credentials or object coordinates.
A later edit, provider-page move or asset switch invalidates an in-flight Save result, so a late
response cannot be presented as applying the current draft. Expired final Manual attempts are
terminalized before the claimant scans onward, and older work for the same asset remains FIFO ahead
of newer edits.
Deployment activation and a real
Airflow/object-store/DataHub acceptance run remain separate runtime gates.

1. Request a multipart upload session after `registration.create` authorization.
2. Browser uploads directly to a quarantine object key.
3. Complete call supplies size, MIME and SHA-256; server verifies object metadata.
4. Validation job streams the object, scans it, detects structure, and produces row-level errors plus normalized preview.
5. User selects allowed changes and creates a registration/change request.
6. Approval and application follow the governance workflow.

Uploads can be aborted, expire automatically, and cannot be downloaded with an old authorization decision. Validation never equals approval.

The typed BULK dataset-description CSV/XLSX profiles are all-or-nothing, limited to 16 MiB and
10,000 rows. Their parsers use bounded reads, canonical lowercase asset UUIDs,
projection-compatible identity limits, duplicate rejection and exact source/candidate hashes. CSV
additionally enforces strict UTF-8/CSV states and exact ordered headers. Description content,
including an empty clear proposal and quoted CSV newlines, is preserved. A purpose-bound Airflow
call claims one preparation under database-time lease/retry fencing and atomically publishes a
`READY` receipt/candidate set only after accepted-object identity and full-input hash verification.
XLSX ZIP/XML parsing and candidate serialization run off the event loop; candidates replay from a
gzip attempt-local spool with a 256 KiB memory threshold, 64 MiB hard cap and 16-row delivery
batches instead of retaining the 10,000-row set in browser or API memory. Expired final
preparations are failed and flushed before the worker scans onward.
The bounded candidate API revalidates V2 receipt/hash invariants, resolves the page of targets in one
authorization-pruned ACTIVE DATASET batch and exposes immutable submitted identity separately from
the current projection. Any legacy, missing, denied or identity-drifted target makes the whole page
unavailable without disclosing which row failed.

The BULK browser preserves the v0.3 300-pixel upload panel and dark workflow tracker while replacing
client-side parsing and simulated updates with server truth. It sends the explicitly selected profile
on upload initiation, lists/creates preparation only for an `ACCEPTED` typed source, uses the exact
quoted manifest `If-Match` and a fresh idempotency key, and displays indeterminate progress until the
server reports a row count. `READY` enables candidate paging and an exact one-candidate preview. The
server re-reads and safely merges the current `datasetProperties` document, preserves unknown fields
and returns an opaque ETag. With `If-Match` and an idempotency key, the browser may create one
governed Change Request whose single server-authored description item and immutable candidate
binding commit atomically. No raw Aspect, provider document, object coordinate, new table/column or
direct DataHub mutation action is exposed.

## Change management

The new-CR related-table editor keeps table and selected-column evidence in one compact hierarchy:
each column is visually a child of its table with a `컬럼` badge and a small `기존`/`신규` or
`변경` state marker. All table-input controls, including Tag/Term controls, have the same 29-pixel
height. Existing table intake omits the redundant Platform/Database display; a typed
`requested_change` text field sits between Tags and column addition at table and column level and is
preserved in immutable intake evidence without replacing metadata Description. Tag/Term follows the same
single-line scrollable badges, nearby floating input, vocabulary-first and comma-aware proposal
interaction as Registration: opening `+` reads the authorization-pruned workspace projection only;
a typed keyword narrows that same projection
query before a new proposal is offered. Provider failure retains the projection-only result. The column row uses the same eight-track grid as its table row: its
hierarchy spacer occupies the Schema track, then column item/Type/Description/Term/Tag/requested-change/
management align with table/Table/Owner/description/Terms/Tags/requested-change/column-addition.
This is presentation only and does not alter the typed target or approval contract.

State machine:

```text
REGISTERED → IN_REVIEW → TESTING → FINAL_REVIEW → APPLY_QUEUED
→ APPLYING → APPLIED
                 └→ APPLY_FAILED → APPLY_QUEUED (authorized retry)
REGISTERED → IN_REVIEW → TESTING → FINAL_REVIEW → COMPLETED (typed intake only)
Any pre-apply review state → REJECTED or CANCELLED under policy
```

- Each transition declares allowed prior state, action, required evidence and actor separation.
- Requester cannot be final approver; high-classification changes require two distinct approvers and strong authentication.
- Optimistic `version` prevents lost updates.
- `APPLIED` requires target aspect re-read and content-hash match.
- Lists return scalar summaries through keyset pagination; exact details are fetched only after
  selection and are hard-capped at 200 items, 600 approvals, 200 transitions, 50 rounds and 200
  test runs. Apply reports expose at most 200 item results and 20 attempts.
- The v0.3-shaped multi-target CR intake re-reads each selected existing dataset on the server and
  records requested table/column metadata as `DATAHUB_INTAKE`; new tables are server-minted manual
  proposals. These non-executable records can become `COMPLETED` only after independent final
  approval. `COMPLETED` is a human workflow outcome, not a DataHub mutation/read-back claim.
- Every attachment download, upload finalization and transition receives a fresh ABAC decision and
  audit event. Uploads first return `202 STARTED`; a separate least-privilege worker proves provider
  HEAD metadata and the full byte hash before the current human may finalize. Ambiguous network,
  408 and 5xx responses recover by the exact client-generated upload UUID. The browser pauses
  polling while hidden, retains the same ID across a bounded retry and can explicitly recover at
  most ten server-filtered current-round STORED intents while reporting any partial failure.

## Monitoring and operations

- Capability cards for API, PostgreSQL, DataHub, cache, queue, object storage, graph, LLM, Airflow and policy.
- The dashboard's legacy asset card layout is backed by the current typed DataHub projection: total non-deleted assets and non-blank description coverage, plus a bounded platform/database/schema breakdown. Tags, glossary mappings, quality scores, time-window history and audit rows are not manufactured when their governed read model is absent; their visible cards state that the metric is not collected under the current contract.
- Monitoring restores the legacy full-height observability panel and refresh control using the authenticated capabilities response. A configured server-validated Grafana link opens as an external page by default. A sandboxed no-referrer iframe appears only when the server reports an available descriptor derived from deployment-owned `UI_GRAFANA_URL`, matching exact-origin `GRAFANA_EMBED_BASE_URL`, explicit enablement and a non-empty SSO/frame-policy evidence reference; the same origin must be present in web CSP `frame-src`. The browser never creates a frame from an entered URL.
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

- The administrator user and Role lists are dense server-keyset pages of at most 100 rows; the browser requests 25, caps cursor history and discards aborted or late responses. A selected Role/member outside the current search page remains an explicit identifier rather than causing an unbounded preload. Membership access changes remain ETag-, assurance- and audit-protected. A Role version defines one secret-free Policy Book rule per PUBLIC/INTERNAL/CONFIDENTIAL/RESTRICTED classification: No/Partial/Full access, typed partial treatment, residency and processing-purpose allowlists. Missing rules deny. Role assignment/removal records exact normalized evidence in the same membership transaction, and the generic access form is disabled for Role-bound or unverifiable legacy evidence until the Role is removed or repaired. When the operator enables the governed Keycloak adapter, a recently hardware-authenticated security administrator may create a disabled IdP identity and six-month Workspace membership together, optionally materializing one active server-searched Role, before the identity is enabled. Temporary credentials pass only to the identity provider and require first-login replacement. Other IdPs keep account creation external.
- The adjacent administrator System tab pages the canonical System master separately from each System's assignees. A recently hardware-authenticated security administrator applies a bounded, confirmation-gated, ETag-fenced and idempotent delta of disjoint upserts/removals. Each resulting responsibility lane retains at least one active human Workspace member; role-local priorities are unique and start at one. The command emits immutable outbox audit evidence. The compatibility full-replacement API remains, but the browser neither loads nor resubmits every assignee.
- Classification policies, RESTRICTED grants, inference profiles, retention policies, Legal Holds, erasure requests, renewals and fallback requests use the same bounded server-cursor and per-channel abort/stale-response rules across effect, refresh, mutation reload and unmount. Legal Hold and erasure lists omit history; exact details return only the newest 100 records with an explicit truncation flag. Retention review displays archive-only execution evidence separately and never labels approval or an immutable receipt as physical deletion.
- The administrator System settings tab is a server-backed, redacted inventory for deployment-managed PostgreSQL/OIDC bootstrap capabilities, separate external Redis cache/delivery, DataHub GMS/Frontend, Airflow, S3/MinIO, LLM chat/embedding/reranker, Neo4j, Prometheus and Grafana. Every item carries category, requirement level and explicit required/secret field metadata. Inventory lookup reads only current/activated revision evidence; bounded history exposes non-secret revision hash/TEST/activation facts. SAVE accepts exact server-owned mounted-secret reference names, TEST executes a fixed typed probe, and credential/provider response values are never returned. In development only, connector YAML may be versioned and activated; a separately guarded private-network OpenAI-compatible Chat/Embedding adapter is not a provider-profile route, cannot target a public endpoint and is not a production inference capability (ADR-0030, ADR-0033, ADR-0038).
- Audit/security export, canonical terminology CRUD, user-profile edit and per-user CR/owned-table drill-down remain explicit governed-unavailable states until separately authorized, masked and server-paged APIs exist. The Admin UI does not fabricate their rows or expose silent controls.
- Policy changes are versioned, linted, tested against fixtures, approved and atomically activated.
- Connection configuration stores endpoints/capabilities and `secret_ref`, not plaintext credentials.
- Audit search/export is separately authorized and immutable to normal admins.

## Accessibility and convenience

- Complete keyboard navigation, semantic landmarks, focus restoration, accessible errors and minimum AA contrast.
- Stable URLs for search/detail/request/graph/job; filters encoded in URL where safe.
- Unsaved editor changes are guarded; large lists virtualize without breaking accessibility.
- Korean is the first UI locale; user-visible strings use an i18n catalog and English fallback.
