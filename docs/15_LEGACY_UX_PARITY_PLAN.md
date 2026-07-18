# Legacy UX parity plan

## Purpose and boundary

This artifact controls the migration of the proven DataRiver v0.3 interaction model into the v1 platform. The target is deliberate visual and workflow familiarity: an experienced v0.3 user should recognize the global navigation, dense tables, page titles, search, registration, change-management, knowledge, governance, monitoring, and Chat interactions without retraining.

Parity does not make the legacy runtime, database, credentials, or external-system access patterns a dependency. The v1 domain boundaries, OIDC/ABAC enforcement, PostgreSQL canonical workflow state, immutable evidence, transactional outbox, private object manifests, DataHub anti-corruption layer, and rebuildable graph projections remain authoritative.

## Source precedence

When sources disagree, use this order:

1. v1 security, ownership, data-retention, and architecture decisions;
2. current controlled v1 requirements and API/data contracts;
3. this parity plan and its acceptance matrix;
4. v0.3 screen layout, labels, interaction density, and workflow intent;
5. v0.3 implementation details only when they satisfy all higher-order controls.

The reference source is read-only. No legacy secret, token, password, runtime configuration, build artifact, mock fallback, database row, or package tree may be copied into a v1 image or commit.

## Visual and interaction contract

The shared UI contract is:

- a 56-pixel navy GNB with DataRiver identity, scrollable primary menus, compact global search, approved auxiliary-system links, and a capability-filtered profile menu;
- warm-cream application background, `#0a192f` navigation, `#004b87` primary accent, square two-pixel radii, restrained shadow, and compact Korean-first typography;
- an approximately 80-pixel page-title box with a blue square icon, title, short description, and right-aligned actions;
- high-density TanStack-style tables with sticky 11-pixel headers, approximately 13-pixel monospace identifiers, tight rows, server paging, explicit sorting, no accidental wrapping, ellipsis, and full-value hover/focus text;
- the operational canvas grows to a 1,800-pixel maximum; the Resource Tree is 300 pixels and the catalog detail workspace is approximately 550 pixels at its default desktop size;
- panels and tables have a practical minimum width and use contained horizontal scrolling instead of collapsing operational columns into unreadable cards; below the 960-pixel desktop breakpoint, tree and detail surfaces become keyboard-accessible drawers;
- accordions expose row detail in context; graph selections expose node/edge detail without losing the current query state;
- URL-addressable search, filter, sort, page, selected record, and module-tab state where a copied URL is safe to share;
- keyboard focus, skip navigation, labelled controls, non-color status cues, and explicit loading, empty, stale, unauthorized, conflict, rate-limit, and failure states.

Visual similarity never permits an invented success state. A disabled action must state the missing capability or prerequisite.

## Safe-substitution decisions

| Legacy-visible behavior | v1 implementation rule |
|---|---|
| DataHub links and lineage detail | Use a server-provided, allowlisted deployment capability. Iframes are sandboxed and never accept a client-supplied arbitrary URL. |
| Grafana monitoring iframe | Use only a configured, server-approved origin and capability. Absence renders an honest unavailable state, not a hard-coded localhost fallback. |
| Dynamic connection values | UI receives redacted capability metadata only. Secrets remain secret references and are never returned to the browser. |
| DataHub write from an ingestion action | Upload or edit creates a validated proposal; approval and a scoped worker apply it; DataHub read-back verifies completion. |
| Manual and bulk display names | Preserve the required logical name in the manifest while the physical object key stays unpredictable, workspace-scoped, and server-generated. |
| CR attachment filename convention | Preserve the convention as approved display metadata. The browser never selects the bucket or physical object key. |
| Attachment download | Resolve an attachment UUID on the server, re-check workspace, CR ownership, current ABAC and retention state, audit the decision, and only then issue a short-lived download. A client filename or object URL is never authority. |
| Neo4j as graph source of truth | PostgreSQL immutable knowledge release is canonical. Neo4j or another graph engine is a private, rebuildable projection. |
| Text-to-Cypher | Natural-language analysis compiles to a bounded server-side query plan or approved template. Raw LLM Cypher and public Bolt access are prohibited. |
| LLM extraction directly updating a graph | LLM output is an evidence-linked proposal changeset that passes schema validation, policy checks, and human approval. |
| Chat-generated Cypher | Use an authorized, bounded graph template and typed parameters. Do not log or execute raw generated Cypher or raw prompts. |
| Client-side Excel export | Export is generated from a fresh, server-authorized result scope and requires the export capability; it cannot infer access from visible rows. |
| Production mock or cached fallback | No mock fallback. A bounded stale response carries its source version, observation time, and stale reason. |

## Enterprise integration directive — ordered delivery (2026-07-17)

The current delivery objective is **visual and workflow parity with the v0.3 application**, not a
replacement dashboard or mock-data demonstration. Every legacy route, menu, title box, dense grid,
dialog, accordion and empty/loading/error state must remain recognizable at its v0.3 location while
its data and commands use the typed v1 API. A provider or contract gap is never an excuse to remove
the surrounding v0.3 screen: the visible control must show the real unavailable/degraded state and
must not invent a successful result.

The work is deliberately ordered so that a visual clone is built over real, bounded state rather
than browser-owned authority:

| Step | Scope | Completion evidence |
|---|---|---|
| 0 | This traceability plan, the v0.3 source inventory and architecture/security contracts | each directive requirement has a parity row or an explicit governed backend dependency |
| 1 | Admin catalog visibility, custom login, Workspace/OIDC hydration and token renewal | human security administrator sees its workspace's quarantined DataHub projection through the real API; ordinary users remain policy-pruned; in-memory pre-expiry renewal plus one idempotent `401` retry and reload cases pass |
| 2 | Common shell and catalog | v0.3 GNB/profile menu/title box, dense Tree/result/detail/lineage layout use live catalog APIs with no mock records |
| 3 | Registration, CR, knowledge, monitoring, governance and Chat submenus | each legacy control is wired to a typed command/read model, or visibly reports the server's real unavailable/degraded capability without a fabricated outcome |
| 4 | End-to-end acceptance | administrator and non-administrator browser journeys, API negative cases, reference-viewport comparison and documented deployment gates pass |

### Non-negotiable implementation rules

- Roles, profile and tokens remain server-verified and React-memory-only; the URL may retain a
  validated Workspace/page selection but never authorization.
- A `401` is recovered through the OIDC provider's standard refresh/renewal flow and the original
  idempotent read request is retried once. A failed renewal returns to the existing custom login
  state without an authentication loop or a fabricated response.
- The administrator's unclassified/quarantined DataHub projection is a separate, read-only,
  audit-recorded catalog-review scope. It cannot authorize export, Chat retrieval, arbitrary
  provider calls, DataHub mutation, attachment access, cross-workspace access or a service account;
  the existing typed DataHub metadata enrichment remains available for catalog detail.
- The clone contains no client mock dataset, fake counts, fake workflow success or browser-held
  provider credential. Visible controls are driven by real API state.
- Each completed step includes focused tests and a separate commit. UI parity remains incomplete
  until the administrator and ordinary-user browser acceptance journeys pass at the reference
  viewports.

## Screen and capability traceability

Status values are `READY` (parity accepted), `PARTIAL` (a governed v1 contract or first UI exists), `PLANNED`, and `BLOCKED` (requires an external deployment decision or service).

| ID | Area | Required parity outcome | Current status | Acceptance focus |
|---|---|---|---|---|
| UX-PAR-001 | Common shell | v0.3-recognizable GNB, page title, compact sizing, profile administration menu | PARTIAL | source/unit complete; profile exposes URL-restored Workspace selection, security-key/logout controls and server-derived administrator sections. OIDC profile/role state is hydrated from `/auth/me` into React memory; `/admin/me` reports the verified current assurance without demanding step-up; pre-expiry OIDC renewal and a one-time idempotent `401` retry preserve a verified session without browser storage. Sensitive mutations alone show reauthentication guidance. Authenticated reference-viewport visual snapshot remains open |
| UX-PAR-002 | Global search | debounced authorized suggestions with preview, minimum length, multi-keyword handoff | PARTIAL | stale-cache labelling, no cross-workspace or policy-version leakage |
| UX-PAR-003 | Catalog layout | left Resource Tree, middle dense result table, filter/facet bar, paging and export | SOURCE COMPLETE | typed PostgreSQL/Oracle tree, dense real-projection columns, `ALL` search targets, bounded cursor pagination, total count, server-authorized CSV/XLSX export and URL-restored Workspace/page are implemented. Isolated export-worker runtime and authenticated visual acceptance remain deployment gates. |
| UX-PAR-004 | Catalog detail | row accordion with table/column metadata and lineage graph | SOURCE COMPLETE | fixed-contract detail/columns, URN copy feedback and bounded authorization-pruned deterministic React lineage graph are implemented; selected-state URL/back-forward and the authenticated visual gate remain. |
| UX-PAR-005 | DataHub lineage | selected lineage node opens an allowlisted sandboxed DataHub view | PARTIAL | opaque asset-ID descriptor, exact-origin configuration, CSP, no-referrer sandbox and new-tab fallback are implemented disabled-first; DataHub identity/frame-header evidence remains external |
| UX-PAR-006 | Manual registration | tree selection, table/column edit, controlled term/tag selection, delete proposal | SOURCE COMPLETE | the v0.3 left tree plus `Table Properties` and `Column Schema Specifications` workbench structure is restored over the typed canonical tree/detail. It retains live, hash-fenced description and controlled-metadata change proposals rather than legacy direct provider writes; unavailable provider fields render as absent source data rather than client values. |
| UX-PAR-007 | Bulk registration | CSV/XLS upload, validation summary, correction and proposal creation | PARTIAL | the 300-pixel upload panel, typed-profile selector and dark workflow tracker restore the v0.3 visual structure while multipart quarantine, real validation states and version-fenced full-read-back promotion replace simulated browser execution. Forced-RLS preparation evidence, exact accepted-evidence API, bounded parser contract and an authorization-pruned candidate read API exist disabled-first; the UI creates/reads bodyless server preparation, shows actual progress and renders candidate evidence only after an explicit authorized read. Runtime parser/target resolution/staging plus candidate correction, typed candidate-to-CR creation and preview controls remain closed; raw proposal UI is absent |
| UX-PAR-008 | Change overview | status overview by system/owner and legacy-recognizable workflow buckets | PARTIAL | the UI labels the authorized current request window and uses the server state filter; system/owner grouped totals remain blocked until an exact same-ABAC grouped contract exists |
| UX-PAR-009 | Change list/detail | dense CR table, accordion/modal detail, review/re-request/test/completion transitions | PARTIAL | a keyboard-operable dense table, freshly authorized accessible detail, immutable target/approval/transition evidence, explicit `CHANGES_REQUESTED` → re-registration and version-fenced commands are implemented. A denied command is never replayed automatically and a conflict reloads detail while preserving the reason; server command summaries, revision/test/attachment flows and authenticated browser E2E remain |
| UX-PAR-010 | CR creation | legacy field loading, `CR-system-date-random4`, urgency and due-date semantics | PARTIAL | server-issued `CR-{safe-platform}-{YYMMDD}-{random4}` number and workspace uniqueness are implemented; collision retry, urgency/due date and ordinary typed create form remain |
| UX-PAR-011 | CR attachments | multiple request/test attachments, re-edit/re-request, authorized download | PLANNED | display convention, private physical key, checksum and content disposition |
| UX-PAR-012 | Knowledge registry | assets, versions, status, diff/history, source provenance | PARTIAL | immutable releases and explicit draft/validated/published state |
| UX-PAR-013 | T-Box studio | entity/relation authoring, schema validation, version-up and preview | PARTIAL | typed ontology and invalid-relation negative tests |
| UX-PAR-014 | Knowledge enrichment | file/schema sources, chunk settings, LLM proposal, preview/save | PLANNED | evidence chunks, model/provider/classification policy, no direct publish |
| UX-PAR-015 | A-Box and graph link | existing-schema and dynamic proposal flows linked to catalog asset URNs | PLANNED | canonical URN/provenance and entity-resolution review |
| UX-PAR-016 | Graph viewer | responsive graph canvas with node/edge detail and bounded traversal | PARTIAL | projection watermark, inaccessible nodes/edges absent |
| UX-PAR-017 | Knowledge evaluation | Chat/test set, similarity and groundedness evaluation, GraphRAG loop | PLANNED | reproducible dataset/revision and denial-case scoring |
| UX-PAR-018 | Monitoring | full-height observability panel, refresh, approved Grafana direct link and honest platform capability state | PARTIAL | iframe embedding remains blocked on allowlisted origin, SSO/session boundary and sandbox policy evidence |
| UX-PAR-019 | Governance documents | left statute-like TOC, version/date/department/owner and governed edit | PLANNED | immutable versions, Maker-Checker publish and authorization |
| UX-PAR-020 | Chat modes | GENERAL, VECTOR, GRAPH, AUTO selector, per-user history and favorites | PARTIAL | separate inference worker, mode policy and timeout/degraded states |
| UX-PAR-021 | Chat evidence | right evidence accordion, workflow/status, asset badges, detail modal and graph | PARTIAL | every factual claim cites authorized, versioned evidence |
| UX-PAR-022 | Administration | profile-only capability menu for users, access, classification, retention and audit | PARTIAL | server capability discovery; no client role guess |
| UX-PAR-023 | Administrator profile dropdown | Restore the v0.3 top-right rounded profile control, verified identity header, profile/settings rows, administrator menu composition and logout row at the same screen position | PARTIAL | restored through server-verified `/auth/me` and `/admin/me` memory state with focused component coverage; legacy audit-log, alarm-rule and Korean-dictionary APIs are not present in v1, so those visible rows state their real unavailable status instead of reintroducing local role storage or mock routes. Authenticated reference-viewport acceptance remains open |

`BLOCKED` means the browser must render a useful unavailable state until the deployment capability is supplied. It does not permit a hard-coded local endpoint.

## v0.3 source-level page and control checklist (2026-07-17)

This is the implementation audit for the read-only reference at
`../datariver_v0_3/src/frontend/src`. It covers every route registered in
the legacy `App.tsx`, plus the visible GNB/Profile dropdown and their nested
controls. `PRESENT` means that a safe v1 replacement is actually available;
it does **not** claim authenticated browser acceptance. `UNAVAILABLE` is an
intentional, explained v1 state rather than a dead menu or mock panel;
`UNSAFE_NOT_PORTED` marks a prohibited legacy mechanism.

| Legacy route / source surface | Controls observed in v0.3 | v1 disposition and current evidence | Status |
|---|---|---|---|
| `/login` `LoginPage` | Browser username/password form and local token creation | v1 uses the organization OIDC authorization-code + PKCE flow. The Keycloak `datariver` login theme restores the v0.3 DataRiver visual shell while credentials remain posted only to Keycloak; the local password/token implementation is not retained. | PRESENT (local runtime visual check complete; target deployment gate open) |
| Common GNB and `ProfileDropdown` | Primary menus, global suggestion search, external system icons, profile, admin links, logout | `AppShell` keeps the navigation/search/profile interaction. External links come only from `/capabilities`; profile controls expose a URL-restored non-authoritative Workspace selection, security-key enrollment, sensitive-operation reauthentication and OIDC logout. Admin items come only from `/admin/me`, never a client `role` field. | PARTIAL |
| `FloatingChatWidget` | Global shortcut that opens a Chat surface from every protected page | v1 keeps a first-class Chat navigation item. A floating launcher is deferred until it can preserve typed Chat session/evidence state without a client-side bypass. | PARTIAL |
| `/` `DashboardPage` | Date filters, asset/quality cards, expandable platform list, governance shortcut, audit summary | The v0.3 card/grid/expandable platform layout is restored from `/operations/summary` using current typed DataHub projection counts and description coverage, CR state, capability and outbox data. The visible period controls, tag/glossary/quality cards and audit area explicitly report unavailable until their governed historical/read-model contracts exist; no client fallback value is fabricated. | PARTIAL |
| `/search` `SearchPage` | Query/suggestions, advanced filters, tree, dense sortable table, paging, Excel, detail/columns, lineage, URN copy, DataHub iframe | `CatalogPage` binds typed table/view, platform/database/schema, owner/domain/term/tag and source-created metadata from the local DataHub projection, with URN copy feedback and a bounded React lineage graph. It never infers an absent source field. Filter scope can be selected from the typed tree; server-authorized CSV/XLSX exports use the same fresh authorization/source snapshot and are not built from visible browser rows. Isolated-worker deployment remains an operator gate. | SOURCE COMPLETE |
| `/ingestion` `IngestionPage` | Manual table/column edit, CSV selection/template, preview paging, version/save and Airflow trigger | `RegistrationPage` restores compact hover-only MANUAL/BULK tabs, the v0.3 left canonical tree, `Table Properties`, and `Column Schema Specifications`, including the Oracle schema fallback. MANUAL now stages independent typed description/domain/tag/term evidence and a server-authored private CSV receipt; it deliberately has no browser-triggered Airflow command, client bucket/key, or direct DataHub write. Airflow apply/read-back, Bulk apply and candidate correction remain open. | IN PROGRESS |
| `/change-management` `ChangeManagementPage` and CR views | System/assignee/status buckets, text/date filters, refresh, new request, list/detail/modals | `GovernancePage` has a typed, authorization-fresh list/detail and guarded transitions/approvals, plus a zero-safe status summary, stage badge filtering, restored request-list fields and `신규 CR 신청` entry. System/owner grouped totals, urgency/due-date, revision/test and attachment contracts remain open. | PARTIAL |
| `/quality` `QualityPage` | Dataset search, rule list, rule create/action controls | `QualityPage` is an explicit unavailable capability because no v1 quality rules/results/issues contract exists. It must not show legacy static results. | UNAVAILABLE |
| `/monitoring` `MonitoringPage` | Refresh and Grafana iframe/failure panel | `MonitoringPage` restores the full-height monitoring panel and refreshes server-owned capability data. It exposes only the `/capabilities` allowlisted Grafana direct link; the iframe portion remains blocked until approved origin, SSO and sandbox evidence exist, and no localhost fallback is restored. | PARTIAL |
| `/governance` `GovernancePage` | Document TOC, text/visual tabs, in-place edit | `PolicyGovernancePage` is an explicit unavailable state until immutable document versions, maker-checker approval and policy authorization are implemented. A non-persistent textarea is intentionally absent. | UNAVAILABLE |
| `/chat` `LLMChatPage` | Session create/open/rename/delete/favorite, mode tabs, prompt/stop, evidence drawer, asset detail/lineage, retry/copy/feedback | `ChatPage` supplies an evidence-first question flow using authorized citations. Durable sessions/favorites, typed modes, resumable runs, feedback/retry and evidence-detail contracts remain open; raw Cypher is not exposed. | PARTIAL |
| `/profile` `ProfilePage` | Personal name/email/department edit, password change, DataHub linking, usage panels | v1 delegates identity/profile/password lifecycle to OIDC. `/auth/me` supplies the verified display profile to React memory; the profile menu supports only a server-validated Workspace selection, security key and sign-out. No shadow identity editor or DataHub account linking is presented. | PRESENT (safe substitution) |
| `/admin/users` `UsersPage`, `UserDetailModal`, `UserFormModal`, `SystemsManagementView` | Search/filter, user create/edit/delete, password field, system assignment | `MembershipAccessAdmin` exposes workspace membership, group/action/scope/clearance change through server validation, assurance, confirmation and audit. `RoleAccessAdmin` adds a simple RBAC template facade that writes the same ETag-guarded membership Access document and preserves server-side ABAC enforcement; it never sends a browser-owned DataHub policy mutation. Generic identity CRUD/password reset/system mutation has no v1 contract and is not displayed. | PARTIAL |
| `/admin/dictionary` `DictionaryPage` | Search/scope chips, JSON export, mapping create/edit/delete modal | No governed glossary translation/version/export API exists. The menu is not restored until a typed vocabulary proposal/review contract exists. | UNAVAILABLE |
| `/admin/audit-logs` `AuditLogsPage` | Metadata audit search/filter/paging/export/detail | v1 writes auditable decisions/evidence but does not expose a scoped human audit-read API. There is no client-side log mock or admin menu entry. | UNAVAILABLE |
| `/admin/system-audit` `SystemAuditLogsPage` | Security-access log search/filter/paging/export | No separately authorized security-audit read/retention contract exists. It is intentionally not surfaced. | UNAVAILABLE |
| `/admin/alarm-rules` `AlarmRulesPage` | Rule creation, enable/disable, edit/delete | No notification-rule aggregate, delivery, escalation or audit contract exists. Do not restore the legacy in-memory toggles. | UNAVAILABLE |
| `/admin/connections` `ConnectionsPage` | Endpoint, ID/secret fields, connection test/save, provider settings | Browser-side endpoint/credential editing is prohibited. v1 offers approved inference-provider profiles under governed administration; infrastructure credentials remain operator-managed secret references. | PRESENT (safe substitution) |
| `/admin/connections` `admin/SystemSettingsPage` | YAML endpoint/auth-secret editor, ping/save for DataHub/Neo4j/Airflow/Grafana/MinIO/LLM | `SystemSettingsPage` is deliberately not ported. A browser cannot submit arbitrary YAML, URLs or secrets, and no arbitrary SSRF-capable ping route may be added. | UNSAFE_NOT_PORTED |
| `/knowledge` `KnowledgeDashboard` | Registry/Studio/Chat shortcuts | `KnowledgePage` has graph creation/list and immutable-release vocabulary. The old layout shortcuts can be added only to routes backed by the same release/projection contracts. | PARTIAL |
| `/knowledge/registry` `RegistryView` | Asset table, row detail/history, JSON edit, create/edit/delete | v1 supports graph/release state but not arbitrary JSON graph save/delete UI. Typed changesets, validation, approval and releases replace raw blob editing. | PARTIAL |
| `/knowledge/ingest` `IngestionStudio` | DB/file source selector, LLM analysis, visual editor, raw Cypher editor/preview, execute and graph preview | Raw Cypher, filesystem-like source selection and direct Neo4j execution are forbidden. The future replacement is an approved source snapshot plus typed, evidence-linked changeset reviewed before immutable release. | UNSAFE_NOT_PORTED |
| `/knowledge/chat` `KnowledgeChat` and `QuerySearch` | Asset selector, natural-language query, answer/evidence and displayed/copied Cypher | v1 Chat is permitted only through bounded, authorized query templates and citations. It cannot reveal or execute generated Cypher; GraphRAG evaluation/session contracts remain planned. | PARTIAL |

### Legacy security disposition

The audit also found the following legacy implementation mechanisms. They are
not merely deferred visual work; they are prohibited replacements.

| Legacy mechanism | Reference locations | v1 rule / verification |
|---|---|---|
| Long-lived bearer token in `localStorage` and logout by clearing storage | `contexts/AuthContext.tsx`, `lib/api.ts`, GNB, ingestion, CR and Chat views | OIDC user/token plus verified profile/roles use `InMemoryWebStorage` and React memory; Workspace is a non-authoritative validated URL selection. `scripts/verify_static.py` rejects `localStorage` anywhere below `frontend/src` and persistent session storage in `AuthProvider`. |
| Browser-submitted endpoint, ID, secret or YAML; client-controlled connection ping | `ConnectionsPage.tsx`, `admin/SystemSettingsPage.tsx`, `lib/api.ts` | Secrets stay in server/operator-managed references. Provider profile approval is typed and audited; there is no generic endpoint/YAML/secret route. |
| Client raw Cypher editor/generator and displayed generated Cypher | `knowledge/IngestionStudio.tsx`, `knowledge/QuerySearch.tsx`, `LLMChatPage.tsx` | Browser receives no raw Cypher surface. The planned graph contract accepts typed changesets and uses registered bounded templates only. |
| Hard-coded or hostname-rewritten localhost links and raw external iframe | GNB, `SearchPage.tsx`, `MonitoringPage.tsx`, knowledge diff view | `/capabilities` supplies redacted, allowlisted links. The monitoring page may open a configured Grafana link directly, while safe DataHub embedding requires a server-issued descriptor and Grafana iframe embedding remains unavailable pending deployment evidence. |
| Client-issued DataHub token / direct external command | `lib/api.ts`, ingestion/search views | The browser never receives provider credentials. DataHub is an ACL-backed anti-corruption dependency and writes proceed through approved worker jobs plus read-back. |
| Mock CR creation, static quality/audit/alarm data and non-persistent document edits | CR views, quality/audit/alarm/governance pages | A v1 screen requires a typed canonical contract. Otherwise it renders an explained unavailable state and does not invent success, history or authorization. |

Before changing any `PARTIAL`, `UNAVAILABLE`, or `BLOCKED` row to `READY`, add
the governing API/data contract, negative authorization tests, and an
authenticated visual/browser acceptance result. Do not restore an omitted menu
by linking it to a placeholder.

## Ordered corrective implementation checklist (2026-07-18)

This is the implementation inventory produced by a fresh source-level comparison of the v0.3
React pages/components and their corresponding API routers.  It supplements, rather than rewrites,
the safe-substitution decisions above.  Entries may be checked only after the source contract,
focused tests and applicable browser/runtime evidence exist.

### 1. Home and session hydration

- [x] `PAR-REC-001` Return a verified active `default_workspace_id` from `/auth/me`; choose only an
  active membership for the verified `(issuer, sub)`, prefer the explicit membership marker and
  never treat the resulting browser state as authorization.
- [x] `PAR-REC-002` Inject that default into Auth/App memory after OIDC callback or silent SSO without
  local/session storage, show the existing hydration spinner until complete, and preserve an
  explicitly selected URL Workspace as a non-authoritative convenience value.
- [x] `PAR-REC-003` Keep every Dashboard/Governance Center shortcut on in-application history
  navigation; prove it does not reload, show the login surface, or discard the hydrated Workspace.

### 2. Catalog search, tree and detail

- [x] `PAR-REC-004` Reconcile all eligible catalog rows through bounded cursor paging; retain the
  maximum HTTP page size and use next cursors rather than a browser/GraphQL `10000` bypass.
- [x] `PAR-REC-005` Preserve ADR-0020's human security-administrator review scope on search, facets,
  tree and detail only; ordinary users remain policy-pruned and review scope never authorizes
  export, Chat, attachment or mutation access.
- [x] `PAR-REC-006` Normalize typed provider platform/database/schema containers for PostgreSQL and
  Oracle Resource Tree branches; no browser URN splitting or synthetic database names.
- [x] `PAR-REC-007` Restore the v0.3 dense result columns (`No`, type, platform, database, schema,
  owner, domain, terms, tags and description), advanced filters, detail accordion/columns, URN copy
  feedback and bounded local lineage graph using only real projection/enrichment fields.
- [x] `PAR-REC-008` Restore the visible CSV/XLSX export entry design on the server-authorized export
  boundary. CSV remains worker-gated and XLSX requires its own approved server-side contract; neither
  is simulated from browser-visible rows.

### 3. Registration workbench

- [x] `PAR-REC-009` Archive the replaced v1 MANUAL body under `.legacy_archive/` before removal.
- [ ] `PAR-REC-010` The CR-coupled MANUAL body is archived and replaced with the v0.3 left Resource
  Tree plus selected-table properties and column-grid inputs.  It now stages independent typed
  metadata evidence and a server-authored CSV receipt.  The source now includes an Airflow
  service-account apply/read-back worker with CSV hash/shape verification and aspect leases; a live
  MinIO/DataHub/Airflow acceptance run remains required before this item can be marked complete.
  The browser never writes a provider directly.
- [x] `PAR-REC-011` Match the compact angular MANUAL/BULK tab treatment and hover-only Korean help;
  retain actual upload/preparation state instead of the legacy simulated Airflow tracker.

### 4. Change-request dashboard

- [ ] `PAR-REC-012` Add an authorization-filtered schema/system summary table with zero rows,
  expandable assignee details and status-cell filtering from one consistent server read model.
- [ ] `PAR-REC-013` Restore the top-right `신규 CR 신청` action, side status chips and v0.3-equivalent
  dense list columns, including request date, requested due date, priority and urgency.
- [ ] `PAR-REC-014` Add only typed, auditable CR fields/assignee mappings with model, migration,
  contract and access tests; no client-derived owner/system assignment.

### 5. Integrated administration center

- [ ] `PAR-REC-015` Restore the user/master and system-assignment layouts over canonical Workspace
  membership access, with active status, group/role template, system/schema scope and developer/Data
  Steward priority views.
- [ ] `PAR-REC-016` Add a governed external-service profile master for the approved service catalog.
  It may manage redacted endpoint metadata and write-only secret references, but never plaintext
  credentials, arbitrary URLs/YAML or a client-controlled network ping.
- [ ] `PAR-REC-017` Record every replaced/deleted source module in `.legacy_archive/`, execute the
  focused checks after each numbered step, and retain one local commit per verified step.

## Required v1 contract deltas

These contracts are required to reproduce the legacy interaction without reproducing its unsafe data flow:

1. a canonical, cursor-paged Resource Tree endpoint with `platform`, `database`, `schema`, and `table` nodes, `has_children`, authorization-pruned counts, and security/source metadata;
2. explicit multi-keyword semantics (`ALL` by default) and plain-text match fragments or offsets so the browser can highlight without rendering server HTML;
3. a bounded, permission-pruned lineage endpoint with depth, node-count, and timeout limits;
4. an authorization-bound export job created from the exact query/filter/sort and security/source snapshot;
5. typed table- and existing-column-description proposals are implemented; typed domain, glossary-term and tag proposals remain required for ordinary manual editing, and raw aspect JSON is not the normal user contract;
6. revision history and restore-proposal contracts rather than direct rollback;
7. governed vocabulary suggestion and creation proposals;
8. bounded upload preview plus row/column validation issue contracts;
9. server-issued `CR-{safe-system-slug}-{YYMMDD}-{random4}` numbers with collision retry, legal transition summaries, revision rounds, and private multi-attachment manifests;
10. a versioned policy-document aggregate with stable ordered section IDs, immutable document versions, draft/review/approve/publish, optimistic concurrency, and Maker-Checker enforcement;
11. server-described safe-embed or external-link capabilities for DataHub and Grafana, backed by exact scheme/host/port allowlists and CSP;
12. owner- and workspace-scoped Chat sessions/favorites plus durable assistant runs, authorized resumable SSE, cancel, and typed workflow events;
13. registered graph query templates with typed parameters, authorized knowledge releases, hop/node/time limits, and no raw Cypher surface.

The browser must never build the tree by preloading the full catalog, infer canonical hierarchy by splitting a URN, or re-fetch every page in parallel to create an export.

Change-request revisions are not terminal rejection. The v1 domain must represent `CHANGES_REQUESTED` or an equivalent revision round and allow a governed resubmission. `APPLIED` is reached only after the worker effect and DataHub read-back/hash verification; the UI also exposes queued, applying, and failed operational states without equating them to completion.

Chat modes are typed as `AUTO`, `GENERAL`, `VECTOR`, and `GRAPH`. Manual targets come only from server-authorized asset, release, and graph-template choices. Router decisions and workflow steps are server events, not client animations. There is no automatic downgrade to a different mode when it would change the security or evidence contract.

All migrated overlays use the shared accessible Dialog contract: labelled modal semantics, portal, focus trap, initial focus, Escape handling, focus restoration, scroll lock, and a dirty-state confirmation. Accordion and dense-table rows expose keyboard actions and explicit expanded relationships.

## Knowledge and GraphRAG lifecycle

The normal Studio path is:

```text
immutable source snapshot
→ parse and bounded chunk preview
→ ontology or A-Box extraction proposal
→ typed graph changeset
→ deterministic validation
→ independent review
→ immutable release
→ shadow projection and drift verification
→ active release pointer switch
```

Direct release snapshot publication is not exposed to ordinary Studio users. If retained for migration or recovery, it is an operator-only capability with separate audit and promotion evidence.

Knowledge source requests accept only approved identifiers and bounded settings: source kind, canonical source ID, graph/workspace ID, classification, version/hash, observation time, parser profile, chunk/overlap limits, and an object manifest or catalog scope ID. They never accept a filesystem path, endpoint, credential, raw SQL, raw HTTP, bucket/key command, or client-supplied provider.

A separate knowledge-extraction worker consumes immutable snapshots and an approved extraction/provider profile. It may produce typed ontology deltas or graph operations with stable IDs, provenance, confidence, warnings, and cost/latency metrics. It cannot publish a release, switch the active pointer, mutate DataHub or a canonical graph, or execute raw SQL/Cypher/HTTP.

Registry and Studio surfaces expose these real states:

- graph: `DRAFT`, `ACTIVE`, `ARCHIVED`;
- projection: `NOT_BUILT`, `BUILDING`, `VERIFIED`, `DRIFTED`, `FAILED`;
- extraction: `SOURCE_SELECT`, `UPLOADING` or `SNAPSHOTTING`, `PARSING`, `PROPOSING`, `PROPOSAL_READY`, `EDITING`, `VALIDATING`, `CHANGESET_READY`, `FAILED`, `CANCELLED`.

The graph canvas starts from a bounded subgraph and expands neighbors progressively; it never fetches an entire production graph. Layout is deterministic from stable IDs. Node detail includes stable ID, display name, type, classification, ontology/release version, provenance count, confidence, and stale/projection state. Edge detail includes type/direction, endpoint names, classification, confidence, provenance count, effective interval, and release version.

GraphRAG evaluation is pinned to an immutable graph release, query-template revision, dataset revision, routing revision, and model/provider profile. It records route accuracy, citation precision/recall, groundedness/faithfulness, abstention correctness, response similarity, TTFT, token rate, and total latency. Similar wording alone cannot satisfy the accuracy gate.

## Delivery stages and live status

| Stage | Scope | Status | Exit evidence |
|---|---|---|---|
| 0 | objective, legacy audit, parity matrix and safe substitutions | COMPLETE | all legacy screens and unsafe patterns mapped; controlled-doc review complete |
| 1 | common shell, route/state model and shared Dialog/DataTable/Accordion primitives | SOURCE COMPLETE; VISUAL GATE OPEN | type/lint/build, 47 FE tests and capability-negative shell tests pass; authenticated snapshots remain |
| 2 | search, Resource Tree, table result, detail and lineage | SOURCE COMPLETE; DEPLOYMENT GATES OPEN | source/API/FE unit gates, deterministic lineage graph, typed PostgreSQL/Oracle tree and server-managed CSV/XLSX export are implemented; isolated export-worker runtime approval, DataHub SSO/frame evidence, full URL state and authenticated visual gates remain |
| 3 | manual and bulk registration | IN PROGRESS — INDEPENDENT MANUAL RECEIPT/PREPARATION | source/unit and prior live Vite/API/APISIX contract gates pass. MANUAL records table and field description/domain/tag/term intent with immutable target/source evidence and a server-authored private CSV receipt; it does not claim provider application. BULK explicitly selects a bounded dataset-description profile, queues/reads one server-owned preparation from exact accepted-byte evidence and restores the v0.3 dark status tracker with actual server state. Its pure streaming parser and authorization-pruned candidate read plane are implemented and tested; the UI can render candidate evidence after an explicit fresh authorized read, but candidate correction, typed candidate-to-CR creation and per-row preview remain closed. Raw generic/upload proposal actions are deny-by-default hardware-human operations with no ordinary browser form. Remaining worker/candidate/provenance UI, typed domain/term/tag provider application, worker apply-time requester/policy reauthorization, target serialization/provider CAS, authenticated browser E2E and target object-version evidence remain |
| 4 | change overview, list, workflow and attachments | IN PROGRESS — AUTHORIZED READ PLANE | bounded list/state-filter and fresh-detail contracts, keyboard/focus/loading/empty states, target/approval/transition evidence and explicit command confirmation are unit-tested. Same-ABAC grouped overview, server command summaries, revision/test/attachment flows and authenticated browser E2E remain |
| 5 | knowledge registry, ontology, graph and evaluation | NOT STARTED | release/projection/provenance, bounded graph and graph-policy tests |
| 6 | governance documents and monitoring | NOT STARTED | versioned policy tests and safe-embed capability tests |
| 7 | multi-mode Chat and evidence panel | NOT STARTED | red-team, provider-routing, citation and streaming SLA tests |
| 8 | optional seed, browser E2E, performance, security and operations closure | NOT STARTED | clean-clone, E2E, load/soak, restore and acceptance report |

Each stage is delivered as one or more reviewable commits. A commit must include its relevant tests and controlled-document updates; runtime-only evidence is recorded separately from source-complete claims.

## Acceptance protocol

### Functional and contract acceptance

- Every visible action maps to a typed `/api/v1` contract or a documented unavailable capability.
- List counts, facets, autocomplete, export, detail, graph, and Chat evidence share the same workspace, authorization, classification-policy, access-snapshot, and source/projection version boundary.
- Mutations carry idempotency and optimistic-concurrency controls and return an auditable job/request link for asynchronous work.
- Manual, bulk, change attachment, knowledge proposal, and erasure flows preserve Maker-Checker separation where policy requires it.
- Attachment and Chat session identifiers are opaque server IDs; client filenames, URLs, user IDs, or object keys are never used as authorization evidence.

### Visual and interaction acceptance

- Reference viewports: 1920 by 1080 and 1440 by 900, plus drawer behavior below the 960-pixel desktop breakpoint.
- Compare common shell and each primary page against the v0.3 reference for color, spacing, content density, column order, button placement, accordion behavior, graph detail, and modal hierarchy.
- Exact reuse is not required for legacy behavior that would weaken accessibility, security state visibility, or responsive data readability.
- No-wrap content has ellipsis plus keyboard-accessible full text; tables retain headers and primary identifiers while scrolling.

### Verification ladder

1. focused domain/backend and frontend component tests;
2. frontend typecheck, lint, unit tests, and production build;
3. backend Ruff, strict mypy, relevant pytest, and architecture checks;
4. migration/schema verification for every persistence change;
5. browser journeys with positive and negative authorization personas;
6. runtime readiness and dependency-degradation tests;
7. performance, soak, recovery, and supply-chain gates before promotion.

## Open deployment gates

- Production DataHub is stable `1.6.0` pinned by digest; a development `head` stack is not promotion evidence.
- Production object storage must pass versioning, encryption, replication, restore, retention/Object Lock, license, maintenance, and vulnerability gates. A legacy MinIO deployment is not accepted merely because its UI matches the old system.
- True HA requires at least three independent failure domains and off-host distributed storage. A single-host Compose deployment is labelled `Single-node Pilot`.
- The observability target is OTel Collector, Prometheus, Grafana, Alertmanager, Tempo, and Loki, with enterprise observability connected through the OTel boundary when available.
- Administrator security-key step-up is primary. Typed-password reauthentication plus independent Maker-Checker approval is compensating fallback only; mobile OTP is not required for the closed-network profile.
