# Feature specification

## Current-source implementation summary

This is a `target-gated` specification of the source after Phase 6E, not production acceptance.
PostgreSQL owns business truth; DataHub, object storage, Redis, Neo4j, Airflow and model providers
are fallible external capabilities. Every protected workflow is Workspace-scoped and fails closed
when identity, policy, source evidence or a required connector is unavailable.

| Capability | Primary actors | Current source contract | Canonical owner / unavailable behavior |
|---|---|---|---|
| Identity and Workspace | OIDC user, service subject | OIDC profile hydration, mandatory Workspace, in-memory token/session epoch, no application password | OIDC + PostgreSQL IAM; deny or explicit sign-in state |
| Catalog | authorized user, administrator review scope | bounded search/tree/detail/lineage, match evidence, cursor paging, authorized export jobs | PostgreSQL projection + DataHub detail; stale/degraded reads are explicit |
| Registration | Administrator, Data Steward, service worker | typed Manual and Bulk intake, private object receipts, bounded parsing, governed CR creation | PostgreSQL intent/evidence; S3/DataHub/Airflow failure never reports applied |
| Change management | requester, independent approver, worker | versioned CR rounds, maker-checker approvals, TEST evidence, queued application and read-back | PostgreSQL aggregate; provider acknowledgement alone is not completion |
| Data quality | Data Steward, Quality user | search-integrated recent score/status, asset-centric Rule/Run/trend inspector and reusable common Rules with atomic multi-asset mapping | PostgreSQL per-asset Quality evidence; common templates are non-executable authoring intent and unavailable dependencies stay locked |
| Policy and retention | security administrator, independent checker, scheduler/archive roles | reusable Role rules, No/Partial/Full access, retention/hold/erasure approval evidence | PostgreSQL policy/evidence; no direct destructive completion claim |
| Knowledge and Chat | steward, reviewer, authorized user | governed graph publication, bounded source jobs, grounded Chat/GraphRAG capability gates | PostgreSQL release/audit; Neo4j/LLM are optional projections/providers |
| API sharing | product manager, service consumer | versioned product contracts, subject-bound grants, atomic quota/result/replay evidence | PostgreSQL; revoked/expired/drifted grants deny first call and replay |
| Administration and operations | security administrator, operator | bounded membership/System/configuration views and typed commands; connector status is redacted | PostgreSQL + deployment config; secrets stay server-side, while authorized Admin may read bounded redacted effective coordinates that never become browser-supplied probe input |

Global UX rules are loading/empty/denied/degraded/error states, server paging rather than browser
accumulation, explicit confirmation for high-risk actions, bounded polling, and no fabricated
success. Remaining target gates include native WSL `linux/amd64`, real multi-human OIDC/WebAuthn,
external provider read-back, target load/recovery and physical retention evidence. Runtime API/OIDC
Origin validation is deliberately deferred as `R5-FE-04` P2 in the master backlog.

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

## Data quality management

- The human dashboard first obtains independent read/Profile/authoring/activation/manual/
  scheduling/operations capabilities. Only `read_access=AVAILABLE` loads resources; the
  database-time authorization lease is at most 30 seconds and expiry purges Quality query memory
  before capability revalidation.
- Overview, asset, Rule Set, Run, normalized expectation-result and issue reads all start from the
  Catalog authorization-pruned asset relation. Hidden assets cannot affect counts, score,
  coverage, trend, cursor sequence or issue frequency. PostgreSQL forced RLS remains an independent
  lower bound.
- Current score selects each visible ACTIVE Rule Set's current ACTIVE Version and its latest
  same-Version terminal Run. Only a latest `SUCCEEDED` Run contributes; later failure, stale or
  cancellation cannot be hidden by an older success. Execution state and quality outcome remain
  separate.
- Catalog Search requests one bounded Quality summary batch for the visible asset IDs and renders
  the latest pass rate plus `PASS/WARN/FAIL` in both the result row and selected Evidence panel.
  Quality denial or dependency failure does not hide an otherwise authorized Catalog result.
- The three tabs are `품질 대시보드 / 자산별 품질 현황 및 이력 / 공통 룰셋 관리`.
  The dashboard compares permission-scoped schema/table counts and the versioned managed
  `정확성/완전성/적시성` definitions. Selecting a metric opens one analysis dialog with target
  coverage, an evidence-backed gauge, a server-fact report and a bounded expandable risk table.
  Accuracy/completeness use latest-success typed Rule results; timeliness uses only the stored
  COMPLETE FULL/PARTITION Profile `stale_at` boundary.
- The asset tab reuses the Catalog global-search control and lazy
  `platform -> database -> schema -> asset` Resource Tree, then shows applied Rule Sets, the latest
  50 Runs and a 30-day score trend for the selected table. Its field Explorer lists the active
  deployment-owned fields with configured/active Rule counts and the latest field score. Selecting
  a field opens a right-side Drawer with that field's proposed/approved/active Rules, latest 50
  field-scoped Runs and 30-day trend while the table-wide summary remains visible. The former
  separate Overview/Run/Issue and maker-checker navigation is not part of the ordinary UI.
- A common Rule stores reusable typed `NOT_NULL/RANGE` authoring intent. The mapping dialog searches
  schema/table/field targets, filters by field type, supports checkbox and Shift range selection,
  and collects typed `RANGE` parameters either per compatible type group or per field. The server
  re-resolves every selected field inside its asset deployment binding, revalidates kind/type and
  parameter compatibility, and submits at most 25 assets and 100 Rules per asset as one atomic
  per-asset Rule Set proposal. The same targeted command can create a new Rule or bind a selected
  common Rule template. The Template never executes directly and `REGEX` remains safety-disabled.
- Asset Profile readiness uses only privacy-allowlisted FULL/PARTITION projection after the
  separate Profile read decision. SAMPLE values, raw partitions, distributions, failure rows,
  generated SQL and provider/source credentials are neither requested nor rendered.
- Rule creation/review/activation, manual execution and scheduling remain unavailable in the
  public UI until trusted server-owned field identity and source/workload/schedule readiness
  attestations exist. The browser shows the returned reason code and never substitutes example
  data or an optimistic local success.
- Common Rule creation remains available to a permitted user independently of mapping readiness.
  Mapping requires both the deployment-owned V2 field directory and current V3/V4 Quality
  retention readiness even for an administrator; the UI explains this dependency instead of
  treating `FIELD_IDENTITY_MAPPING_UNAVAILABLE` as a role failure.
- Score-policy metadata is returned with asset and field workspaces. V1 remains
  `UNWEIGHTED_RULE_PASS_RATE_V1`: score is passed Rules divided by all evaluated Rules; any blocking
  failure is `FAIL`, otherwise an advisory failure is `WARN`, all evaluated Rules passing is
  `PASS`, and no evaluated Rule is `UNKNOWN`. No product-specific numeric threshold is inferred.
  Scheduling is displayed only as capability readiness/reason text; the UI does not create or
  mutate a schedule.
- Until an accepted Quality-specific inference route exists, dashboard reports use
  `FACTS_ONLY/QUALITY_LLM_REPORT_ROUTE_UNAVAILABLE` and are labelled as server fact summaries.
  The browser does not impersonate an LLM report.

## Governance Document library

- Governance opens on **문서 조회**, which lists only currently `ACTIVE` managed documents and
  renders the selected published version, its metadata and authorized hierarchy. **문서 관리** is
  shown only when at least one create/edit/review/publish/archive axis is available. Every
  document request follows a 30-second capability lease and returns only permission-pruned
  summaries with an opaque cursor; read denial causes zero document requests.
- Authorized humans create a document/Template with native rich text or import bounded
  HTML/Markdown/DOCX. The server canonicalizes and sanitizes HTML; the browser renders allowlisted
  nodes without raw HTML insertion. Data classification/access, retention/disposal and Legal Hold
  starter blueprints create ordinary editable `DOCUMENT` aggregates. They are never silently
  seeded or shown as `ACTIVE`; an authorized author must create them and an independent reviewer
  must approve each version.
- Every edit creates a new immutable version. Draft authors submit for independent review; only an
  eligible non-author Checker can approve/publish or reject. The detail view shows version,
  initial author, version author/reviewer/time, applicability, object state, knowledge state,
  immutable review history and version-owned parent/authorized-child document links. Parent changes
  require a new version; self-links and cycles fail closed.
- Attachments belong to one Draft version and are create-only in the versioned
  `datariver-filefolder` prefix. The UI accepts no object key and exposes no list/delete/presign
  control. A stale aggregate ETag blocks the object write. Server-derived basenames distinguish
  the body (`doc_governance_<title>_<YYYYMMDD>_<serial>.html`) from editor-bottom references
  (`ref_governance_<title>_<YYYYMMDD>_<serial>.<ext>`), while UUID directories retain collision
  isolation and exact-version receipts.
- Archive is a reasoned high-risk command that changes lifecycle only. It never deletes a DB row,
  document version, attachment or MinIO object version.
- The authorized JSON export contains the selected sanitized body, public metadata, immutable
  version/review history, attachment metadata and permitted parent/child summaries. It never
  exposes bucket names, object keys, provider VersionIds, credentials, endpoints or Presigned URLs.
- A dedicated worker stores exact version artifacts, embeds published text and verifies the fixed
  Neo4j document/version/chunk projection. The evidence search sends only bounded text; the server
  uses its active embedding binding and returns only current published authorized chunks.

## Monitoring and operations

- Capability cards for API, PostgreSQL, DataHub, cache, queue, object storage, graph, LLM, Airflow and policy.
- The ordinary home dashboard uses `/operations/dashboard` for current typed DataHub asset and
  non-blank description coverage, active synchronized Glossary Term count, CR state and a bounded
  platform/database/schema breakdown. Its Quality card and compact Quality section use the
  existing permission-scoped `/quality/dashboard` facts. It does not request capability probes or
  display upload/job/outbox/dead-letter/audit facts. Local human fixtures receive the required
  `dashboard.read`, `quality.read` and `quality.profile.read` actions during idempotent bootstrap;
  Workspace, classification, System and Domain enforcement remain intact.
- Monitoring presents up to eight ordered Workspace dashboard tabs from the authenticated
  capabilities response. Eligible administrators see a **탭 수정** action on the tab rail and may
  change the label, order, credential-free HTTP(S) Dashboard Link and bounded page height through a
  version-fenced server update. A saved link is presentation metadata only: the server does not
  fetch it or treat it as a connector. Persisting the document with fresh administrator assurance
  approves those Dashboard Links for sandboxed, no-referrer iframe presentation; the edge CSP
  allows HTTP(S) frame sources for this server-returned descriptor only. A deployment-default
  Grafana page that has not been saved by an administrator still requires the exact-origin,
  explicit-enable and evidence gate. Every framed tab retains a new-window link because the target
  site may independently deny framing through its own CSP or `X-Frame-Options`, which DataRiver
  cannot override. The browser never creates a frame directly from an entered URL. The explicit
  `480..2000` pixel height lets each cross-origin Dashboard grow the page downward without unsafe
  document inspection (ADR-0090, ADR-0095, ADR-0097).
- Current platform capability observations are shown with the deployment inventory under Admin
  **System settings**, not repeated below the ordinary Monitoring dashboards.
- Health is `healthy`, `degraded`, `unavailable`, or `unknown`; an unrelated unavailable capability does not blank the whole UI.
- Job explorer shows attempts, retry class, correlation, external response hash and DLQ status without secret payloads.
- Operator replay is an audited command that creates a new attempt; it does not rewrite history.

## Knowledge Graph Studio

- Create graph and versioned ontology; import DataHub scope or uploaded sources.
- The first-depth Knowledge workspace separates **조회 및 생성**, consolidated **정보 관리** and
  **Chat Test**. Information Management uses the same canonical domain API as Studio Step 1 and
  manages description, unit and synonyms for exact Properties in the active immutable Studio
  Release. Graph Builder keeps only lightweight Property name/type authoring.
- A released Property Profile is PostgreSQL canonical, domain/classification authorized, forced-RLS
  isolated, ETag-fenced and idempotent. Archive preserves history while a partial unique constraint
  permits one later active profile for the same released Property; it never edits the ontology
  element or Neo4j projection.
- T-Box catalog discovery uses the same authorization-pruned Catalog search as the main search
  workspace, then narrows candidates to Dataset/Table/View and the Draft classification ceiling.
  Results and field selection use bounded tables; no browser fallback asset is manufactured.
- Extraction produces proposals with provenance/confidence, never direct mutations.
- Knowledge document source analysis is a durable, owner-scoped capability rather than an
  HTTP-request-bound inference call. Submission accepts only an integrity-verified `ACCEPTED`
  PDF/CSV/TXT/JSON/XML/HTML/DOCX/XLSX/PPTX owned by the current actor and only PUBLIC/INTERNAL
  inference classification, rejects legacy or unsafe document payloads, and pins the immutable source
  version/hash, graph version, explicit empty or exact governed active-release base, active
  ontology ID/checksum, parser contract and secret-free loaded deployment or activated System
  Configuration Chat/Embedding bindings, and
  returns `202 Accepted` with a job. A separately credentialed `datariver_knowledge` worker parses
  and embeds at bounded evidence-segment/batch sizes and may create only a typed `DRAFT` changeset. It cannot
  submit, review, publish, activate or project a release.
- The Data Ingestion UI resumes the current owner's active-first opaque-cursor job history, renders
  at most 100 rows, polls only while visible, stops after a bounded window and can restart the same
  selected job. Enqueue permits at most 20 non-terminal jobs per owner/graph, keeping all active
  work on the first page. The UI exposes explicit queued/running/retry/cancel/stale/failure
  states. Cancellation is optimistic-version fenced. Success links to the resulting DRAFT; neither
  submission nor fabricated progress is presented as completion. CONFIDENTIAL/RESTRICTED graphs
  remain visible according to ordinary authorization but do not offer this inference action.
- Before source read and each bounded provider egress, and again before final persistence, the
  worker reauthorizes the requester and revalidates every pinned source/base/graph/ontology/model
  binding. Final persistence repeats the checks under one PostgreSQL transaction. Drift or revoked
  authority produces a terminal `STALE` result with no pages, embeddings, extraction run,
  operations or changeset. Successful pages, bounded JSON embeddings, `DURABLE_SOURCE_V1`
  extraction evidence, typed operations, DRAFT, job/attempt/event, policy decision and outbox
  evidence commit atomically. Browser-visible provenance uses only
  `knowledge-source:<snapshot-id>#page=<n>` (physical page or deterministic evidence segment) and
  never reveals a bucket, object key, endpoint,
  credential or lease token.
- Changeset editor supports node/edge add, update, remove, diff, comments and validation.
- Validation checks ontology, referential integrity, duplicate identity, provenance, policy attributes and bounded quality rules.
- Review and publish create immutable releases through one atomic PostgreSQL command; publication
  does not activate. Only a release with exactly one independently reviewed published-changeset
  lineage and an exact verified canonical/shadow receipt can become active. The deprecated direct
  complete-snapshot route returns `410`, and ungoverned legacy releases are not consumable by
  Knowledge reads, general Chat or release-pinned Sharing.
- Neo4j is an ID-selecting rebuildable shadow. Every selected assertion is rehydrated from the exact
  PostgreSQL release before it can enter an LLM prompt; shadow properties or provenance never
  become canonical evidence.
- Every operation, immutable source and model proposal stays within the graph classification
  envelope. Model proposals inherit the source classification exactly, and confidential source
  inference fails before an external provider is called.
- Compare releases and export authorized JSON-LD or CSV edge lists.
- Projection status is visible and rebuildable from release content.

## Chat and analysis

- Conversation is workspace/owner-bound and persists only under an exact active retention-policy
  ID/hash and policy-derived deadline. Legacy, expired and superseded-policy sessions are
  append-closed. Explicit deletion remains governed backlog and is not a current Chat command.
- Existing sessions reuse only bounded, server-read completed USER intent under the same current
  owner/session/retention-policy fence. The fourth request and later re-compress that bounded input
  on every request; no assistant answer, evidence, citation or durable summary becomes context
  authority. Context preparation failure visibly degrades to the current question without raw
  history fallback.
- User chooses AUTO, general, vector or graph routing; the server records the requested/selected
  route and refuses an unavailable graph adapter without silent fallback.
- Retrieval filters before any development LLM invocation. Responses include ranked authorized
  evidence cards, route and bounded workflow state.
- Adapter reachability alone never authorizes inference. Every invoked stage's environment-selected
  immutable profile UUID and exact route/provider/model/deployment identity must match the active
  classification rule; only classifications satisfying the complete stage set may reach Chat,
  Embedding or Reranker.
- After composition, the exact classification policy/generation and every cited resource are
  reauthorized before persistence. Revocation, drift or dependency failure removes the answer and
  citations.
- Prompt/model/tool and provider/profile/policy identity metadata are audited without logging raw
  secrets or confidential content by default.
- Graph questions use registered typed query templates; generated raw Cypher is rejected.
- If an activated retrieval, reranking or composition adapter fails, Chat returns `검증 불가`
  without citations or a substituted strategy/model.

## API product sharing

- Publisher selects immutable graph release, registered query template, JSON schema, quota plan and expiration.
- A new grant binds one active non-expiring `SERVICE_ACCOUNT` Subject, its issuer, exact
  `client_id`, current product version, scopes, classification ceiling, validity and quotas.
  Client-only legacy grants remain non-invokable evidence; explicit owner binding upgrades an active
  row without discarding its identifier or historical usage.
- Snapshot, Neighbors and deterministic local Chat execute with fixed typed operations. One bounded
  transaction rechecks ABAC, service identity, current product/version/grant, governed release
  lineage and active retention policy, then atomically records one immutable usage row, exact
  classified replay result and UTC-month aggregate.
- The raw idempotency key is hashed. An exact retry returns the same invocation/result without
  consuming quota; changed binding conflicts. Failed or oversized work records nothing, result JSON
  is capped at 1 MiB, and result responses are `private, no-store`. Stable quota errors are also
  non-cacheable and provide a bounded advisory backoff; monthly admission still rechecks the
  database-owned UTC month rather than trusting the client header.
- The former authorization-only reservation endpoint returns `410`. Revocation or current
  identity/version/lineage/policy drift prevents stored-result disclosure.
- No external provider call is allowed while the invocation transaction holds locks. A future
  provider-backed surface requires a durable reserve/execute/settle worker.

## Administration

- Authentication/profile hydration is latest-only and memory-only. An opaque browser
  `securityEpoch` changes on subject, provider-session or security-bearing profile changes; it is
  never authorization. Requests and downloads capture Workspace plus epoch and discard results or
  `401` retries after drift. Ordinary same-session renewal keeps the stable API client and unrelated
  feature state, while a separate accepted-hydration revision hides and reloads `/admin/me`.
  An identical returned Admin context resumes the still-mounted subtree and retains its draft;
  Workspace/epoch or Admin-context fingerprint change, mismatch or denial remounts/purges it so
  rows, forms, ETags, confirmations and idempotency keys cannot cross a security boundary.
- The administrator user and Role lists are dense server-keyset pages of at most 100 rows; the browser requests 25, caps cursor history and discards aborted or late responses. A selected Role/member outside the current search page remains an explicit identifier rather than causing an unbounded preload. Membership access changes remain ETag-, assurance- and audit-protected. A Role version defines one secret-free Policy Book rule per PUBLIC/INTERNAL/CONFIDENTIAL/RESTRICTED classification: No/Partial/Full access, typed partial treatment, residency and processing-purpose allowlists. Missing rules deny. Role assignment/removal records exact normalized evidence in the same membership transaction, and the generic access form is disabled for Role-bound or unverifiable legacy evidence until the Role is removed or repaired. When the operator enables the governed Keycloak adapter, a recently hardware-authenticated security administrator may create a disabled IdP identity and six-month Workspace membership together, optionally materializing one active server-searched Role, before the identity is enabled. Temporary credentials pass only to the identity provider and require first-login replacement. Other IdPs keep account creation external.
- The adjacent administrator System tab pages the canonical System master separately from each System's assignees. A recently hardware-authenticated security administrator creates a System through a confirmation-gated, idempotent, audited command, then applies a bounded, confirmation-gated, ETag-fenced and idempotent delta of disjoint upserts/removals. Each resulting responsibility lane retains at least one active human Workspace member; role-local priorities are unique and start at one. The commands emit immutable outbox audit evidence. The compatibility full-replacement API remains, but the browser neither loads nor resubmits every assignee.
- Classification policies, RESTRICTED grants, inference profiles, retention policies, Legal Holds, erasure requests, renewals and fallback requests use the same bounded server-cursor and per-channel abort/stale-response rules across effect, refresh, mutation reload and unmount. Legal Hold and erasure lists omit history; exact details return only the newest 100 records with an explicit truncation flag. Retention review displays archive-only execution evidence separately and never labels approval or an immutable receipt as physical deletion.
- The administrator System settings tab is a server-backed, redacted inventory for
  deployment-managed PostgreSQL/OIDC bootstrap capabilities, separate Redis cache/delivery,
  DataHub GMS/Frontend, Airflow, S3/MinIO, LLM chat/embedding/reranker, Neo4j, Prometheus and
  Grafana. `.env`/orchestrator values plus mounted secret references are the only live source
  (ADR-0048). Admin exposes no SAVE, revision or ACTIVATE operation: it returns bounded redacted
  effective state, a blank key-only environment template, and one fixed server-owned typed probe.
  Browser input cannot select the probe destination. DNS-less isolated development deployments may
  opt exact IP literals into plaintext fixed probes only through the deployment environment; the
  IP must also be in the ordinary destination allowlist, while URL/port/CIDR/wildcard values remain
  rejected (ADR-0067). A separately guarded private-network
  OpenAI-compatible Chat/Embedding adapter cannot target a public endpoint and is not a production
  inference capability (ADR-0030, ADR-0033, ADR-0038). Reranking uses the Mac-only
  `LOCAL_LLAMA_CPP` bridge over an operator-selected Ollama-owned GGUF and executes the fixed
  `POST /v1/rerank` probe; it is not described as OpenAI-compatible. Historical database-backed
  System Settings revisions are non-runtime records and cannot activate a connector. The
  **테스트 후 반영** interaction applies only the fixed probe result to the current page:
  `미연결 → 연결중 → 연결됨/오류`. It never writes deployment configuration. Core and LLM
  navigation groups become green only when every configured, probeable member has a successful
  result. An enabled model without its exact stage-specific provider-profile UUID is shown as
  `추론 승인 필요`; transport availability never implies governed Chat authorization.
- Per-user CR activity and owned-table drill-downs are bounded Workspace/subject-bound cursor APIs. The server filters every CR/table through its ordinary ABAC action before display. Identity profile attributes remain IdP-managed; audit/security export and canonical terminology CRUD remain explicit governed-unavailable states rather than fabricated browser data.
- Policy changes are versioned, linted, tested against fixtures, approved and atomically activated.
- Connection configuration stores endpoints/capabilities and `secret_ref`, not plaintext credentials.
- Audit search/export is separately authorized and immutable to normal admins.

## Accessibility and convenience

- Complete keyboard navigation, semantic landmarks, focus restoration, accessible errors and minimum AA contrast.
- Stable URLs for search/detail/request/graph/job; filters encoded in URL where safe.
- Unsaved editor changes are guarded; large lists virtualize without breaking accessibility.
- Korean is the first UI locale; user-visible strings use an i18n catalog and English fallback.
