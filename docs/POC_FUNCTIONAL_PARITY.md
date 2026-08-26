# POC functional parity and provider boundaries

This document records what the no-Keycloak POC executes, what remains isolated POC state, and
what is deliberately unavailable. A visible page is not evidence that the production
authorization, persistence, worker, or provider mutation path ran.

## Functional inventory

| Area | POC behavior | State owner |
|---|---|---|
| Shell and navigation | Original page composition and navigation; compact `[poc]` badge | Browser |
| Dashboard | Counts, described assets, glossary terms, and schema metrics are aggregated from the complete DataHub scroll inventory; CR counts use POC state | DataHub + POC PostgreSQL/process memory |
| Global and catalog search | Live suggestions, facets, filters, opaque next/previous cursors, result details, and lineage. Non-empty Catalog queries use the original `ALL`-keyword semantics across the enabled table/description/schema/column/tag/term fields and display provider-derived match fragments instead of a synthetic name match | DataHub |
| Resource Tree | Platform → database → schema → table expansion with complete bounded DataHub inventory reconciliation | DataHub |
| Catalog detail | Human-readable database/schema, newest non-sample full-table rows/size with narrow connector-property compatibility, source created date, paged columns, table/column descriptions/tags/terms, null-safe absent values, and Dataset-only lineage with DataHub display names; ghost/sibling placeholders are excluded | DataHub |
| Search interaction | Detail closes on an outside click; a Resource Tree table re-queries and focuses the matching Search Result row | Browser + DataHub |
| Registration | Shared searchable Resource Tree, live DataHub detail, typed previews, CR creation, and user-created manual history | DataHub read + POC state commands |
| Change management | Registration with request attachments, review, recoverable changes requested, immutable revision/resubmission, test attachment/result, test approval, final approval, cancellation, and completion. Finalized CR attachment metadata and its MinIO locator persist in POC PostgreSQL so restart does not erase the prerequisite for a typed TEST result. Review approval records its evidence and advances to TESTING as one explicit UI command sequence. TESTING presents only complement and approval request actions. Approval names missing current-round fields, or records the PASSED result when needed, records TEST approval and advances to FINAL_REVIEW as one version-fenced UI command sequence | POC PostgreSQL; object bytes in MinIO when configured |
| Quality management | The permission-scoped quality dashboard is the default tab. In POC mode, 품질관리는 등록관리·지식관리·용어사전과 함께 the profile submenu에 위치한다. The asset history tab keeps the shared searchable Resource Tree and live DataHub columns; no fabricated quality scores, rules, runs, or trends | DataHub read |
| Chat | The dense three-pane conversation/history/evidence composition is retained while account-scoped sessions and completed messages persist in POC PostgreSQL. Same-origin SSE exposes real workflow stages and bounded server-approved answer chunks before the canonical persisted result; the browser does not replay a complete result string. Same-session continuity derives at most five bounded recent Q/A turns without making a previous answer current evidence. AUTO applies bounded fast rules then a compact typed LLM decision; explicit GENERAL/VECTOR/GRAPH bypass it. Exact table questions load complete live DataHub table/column/profile evidence. Semantic VECTOR uses the V2 table document containing every provider-returned field name/type/description/tag/term and reconciles the complete inventory from server startup before optional reranking. Semantic discovery defaults to five evidence items but honors an explicit list size up to 20. Complete table/dataset/view counts and unfiltered lists use a separate full-inventory route, so a top-k sample is never reported as the DataHub total. Questions are capped at 12,000 characters with a live counter. Answer focus follows incoming approved chunks until user scrolling cancels it. Safe Markdown headings, lists, quotes, code, tables and inline emphasis retain authored line breaks and spacing in answers; question bubbles retain the submitted multiline spacing. Human evidence cards stay compact while composition receives the full evidence. GRAPH resolves entities before direction-preserving bounded DataHub lineage and optional Neo4j knowledge edges. Direct typed GMS remains the application contract; MCP is optional external-agent interoperability, not a required source | DataHub/POC PostgreSQL/pgvector/Neo4j + configured LLMs |
| Monitoring | Provider probes plus optional exact-origin Grafana dashboard embed | POC server + Grafana |
| POC USER/Admin | Registration, Quality, Knowledge and live Glossary remain separate profile items. Account/access, the OPEN feature-permission inventory, system settings and retention/erasure governance are reached through one `관리자메뉴` item and remain four tabs on that page. The nested security-policy view renders the existing four-class redacted `STATIC_FLOOR` contract; no governed policy/provider/grant record is fabricated. User role is developer/data_steward/viewer/admin; System, assignee and DataHub schema scope records are user-created | POC PostgreSQL/process memory + DataHub |
| Knowledge Studio/Registry | No fixture assets; user-created Domain, Draft, direct T-Box edits, live DataHub source selection, A-Box bindings, review/publication and registry reads | POC PostgreSQL/process memory + DataHub; Neo4j remains evidence/projection |
| Governance documents | No fixture documents; user-created immutable versions support submit, approve/publish or reject, Archive, product blueprints, export/evidence and MinIO attachments when configured. The Tiptap/ProseMirror editor supports headings, bounded block font sizes and indentation, inline formatting, lists, quotes, links, persistent alignment and tables while preserving the existing allowlist-sanitized HTML boundary. HTML file import additionally retains a bounded static CSS subset through a revalidated React presentation token; JavaScript, event handlers, URL CSS and embedded content remain disabled | POC PostgreSQL/process memory + MinIO/Neo4j capability gates |
| Glossary | Live DataHub Term definitions are grouped as expandable GlossaryNode → Term rows through the shared TanStack Table. DataHub relationship totals and lazy bounded relation pages reconcile URN-based table and column term applications separately; clickable counts open distinct right-side table and column accordions. Glossary Term remains the honest leaf type and no local vocabulary or asset is seeded | DataHub |

## Workflow limits that are not silently simulated as production

- The no-auth POC does not start the production DataRiver API. Compose PostgreSQL provides restart
  persistence for the isolated POC JSON state, but not the production schema, RLS, ABAC,
  multi-user maker-checker identity separation, worker receipts, retention or audit evidence.
- A single POC browser can exercise the complete change-request state machine, but one POC subject
  represents all approval roles. This is a process demonstration, not production approval evidence.
  The open POC action vocabulary includes `change.edit`, which is the existing revision/resubmission
  contract permission; this does not weaken the authenticated production authorization boundary.
- DataHub reads are live. Registration/change records do not directly mutate DataHub. The manual
  registration receipt is explicitly marked `POC_MEMORY_ONLY`; an authenticated canonical worker
  is required for governed DataHub write/read-back evidence.
- Quality control-plane authoring/execution remains unavailable when there is no canonical quality
  service. The POC shows live assets and empty/unknown outcomes instead of invented results.
- Neo4j is started and probed when configured, but an empty Neo4j database is not seeded with
  synthetic entities. POC Knowledge/Chat records are not production graph-release evidence.
- The fixed 72-question `frontend/chat-router-benchmark.mjs` dataset is a repeatable evaluation
  input contract, not a measured target-model accuracy claim. Provider-specific routing accuracy
  and latency remain Prep/operations evidence.
- Redis caches only short-lived DataHub inventory/detail responses. Its loss affects latency only.
  pgvector stores the rebuildable POC Chat Catalog projection from ADR-0116/0117. It does not accelerate
  ordinary catalog pages or establish a production recall/latency claim. Production still requires
  the authenticated API, workers, migrations and authorization.

## Grafana environment contract

Set all four values to enable the monitoring dashboard:

```dotenv
UI_GRAFANA_URL=http://grafana.internal:3000/d/datariver/platform
GRAFANA_EMBED_BASE_URL=http://grafana.internal:3000
GRAFANA_EMBED_ENABLED=true
GRAFANA_EMBED_EVIDENCE_REFERENCE=prep-grafana-config-v1
```

`UI_GRAFANA_URL` and `GRAFANA_EMBED_BASE_URL` must have the same exact scheme, host, and port.
Grafana must allow iframe embedding for the POC origin. Credentials are not sent to the browser by
DataRiver; the internal Grafana access policy remains responsible for dashboard access.
