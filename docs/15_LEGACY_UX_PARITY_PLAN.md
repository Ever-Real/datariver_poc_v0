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

## Screen and capability traceability

Status values are `READY` (parity accepted), `PARTIAL` (a governed v1 contract or first UI exists), `PLANNED`, and `BLOCKED` (requires an external deployment decision or service).

| ID | Area | Required parity outcome | Current status | Acceptance focus |
|---|---|---|---|---|
| UX-PAR-001 | Common shell | v0.3-recognizable GNB, page title, compact sizing, profile administration menu | PARTIAL | visual snapshot, capability-negative menu tests, keyboard flow |
| UX-PAR-002 | Global search | debounced authorized suggestions with preview, minimum length, multi-keyword handoff | PARTIAL | stale-cache labelling, no cross-workspace or policy-version leakage |
| UX-PAR-003 | Catalog layout | left Resource Tree, middle dense result table, filter/facet bar, paging and export | PARTIAL | server paging/sort/filter, permission-safe counts and export |
| UX-PAR-004 | Catalog detail | row accordion with table/column metadata and lineage graph | PLANNED | selected state survives paging; unauthorized neighbors are absent |
| UX-PAR-005 | DataHub lineage | selected lineage node opens an allowlisted sandboxed DataHub view | BLOCKED | deployment capability and framing policy verified |
| UX-PAR-006 | Manual registration | tree selection, table/column edit, controlled term/tag selection, delete proposal | PARTIAL | logical name `UPLOAD_METADATA_MANUAL_YYMMDD_SERIALNO`; no direct write |
| UX-PAR-007 | Bulk registration | CSV/XLS upload, validation summary, correction and proposal creation | PARTIAL | logical name `UPLOAD_METADATA_BULK_YYMMDD_SERIALNO`; MIME/hash/size validation |
| UX-PAR-008 | Change overview | status overview by system/owner and legacy-recognizable workflow buckets | PARTIAL | counts use the same ABAC predicate as the list |
| UX-PAR-009 | Change list/detail | dense CR table, accordion/modal detail, review/re-request/test/completion transitions | PARTIAL | legal transition matrix, optimistic conflict, evidence audit |
| UX-PAR-010 | CR creation | legacy field loading, `CR-system-date-random4`, urgency and due-date semantics | PLANNED | server-issued number, uniqueness and idempotency |
| UX-PAR-011 | CR attachments | multiple request/test attachments, re-edit/re-request, authorized download | PLANNED | display convention, private physical key, checksum and content disposition |
| UX-PAR-012 | Knowledge registry | assets, versions, status, diff/history, source provenance | PARTIAL | immutable releases and explicit draft/validated/published state |
| UX-PAR-013 | T-Box studio | entity/relation authoring, schema validation, version-up and preview | PARTIAL | typed ontology and invalid-relation negative tests |
| UX-PAR-014 | Knowledge enrichment | file/schema sources, chunk settings, LLM proposal, preview/save | PLANNED | evidence chunks, model/provider/classification policy, no direct publish |
| UX-PAR-015 | A-Box and graph link | existing-schema and dynamic proposal flows linked to catalog asset URNs | PLANNED | canonical URN/provenance and entity-resolution review |
| UX-PAR-016 | Graph viewer | responsive graph canvas with node/edge detail and bounded traversal | PARTIAL | projection watermark, inaccessible nodes/edges absent |
| UX-PAR-017 | Knowledge evaluation | Chat/test set, similarity and groundedness evaluation, GraphRAG loop | PLANNED | reproducible dataset/revision and denial-case scoring |
| UX-PAR-018 | Monitoring | embedded Grafana page plus honest platform capability state | BLOCKED | allowlisted origin, SSO/session boundary and sandbox policy |
| UX-PAR-019 | Governance documents | left statute-like TOC, version/date/department/owner and governed edit | PLANNED | immutable versions, Maker-Checker publish and authorization |
| UX-PAR-020 | Chat modes | GENERAL, VECTOR, GRAPH, AUTO selector, per-user history and favorites | PARTIAL | separate inference worker, mode policy and timeout/degraded states |
| UX-PAR-021 | Chat evidence | right evidence accordion, workflow/status, asset badges, detail modal and graph | PARTIAL | every factual claim cites authorized, versioned evidence |
| UX-PAR-022 | Administration | profile-only capability menu for users, access, classification, retention and audit | PARTIAL | server capability discovery; no client role guess |

`BLOCKED` means the browser must render a useful unavailable state until the deployment capability is supplied. It does not permit a hard-coded local endpoint.

## Required v1 contract deltas

These contracts are required to reproduce the legacy interaction without reproducing its unsafe data flow:

1. a canonical, cursor-paged Resource Tree endpoint with `platform`, `database`, `schema`, and `table` nodes, `has_children`, authorization-pruned counts, and security/source metadata;
2. explicit multi-keyword semantics (`ALL` by default) and plain-text match fragments or offsets so the browser can highlight without rendering server HTML;
3. a bounded, permission-pruned lineage endpoint with depth, node-count, and timeout limits;
4. an authorization-bound export job created from the exact query/filter/sort and security/source snapshot;
5. typed table, column, domain, glossary-term, and tag proposal DTOs for ordinary manual editing; raw aspect JSON is not the normal user contract;
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
| 1 | common shell, route/state model and shared Dialog/DataTable/Accordion primitives | IN PROGRESS | shell tests, accessibility checks and reference viewport snapshots |
| 2 | search, Resource Tree, table result, detail and lineage | NOT STARTED | API/FE unit tests, authorization negatives, paging/cache contracts |
| 3 | manual and bulk registration | NOT STARTED | upload/validation/proposal/apply tests and object-manifest evidence |
| 4 | change overview, list, workflow and attachments | NOT STARTED | transition, Maker-Checker, attachment and audit tests |
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
