# POC functional parity and provider boundaries

This document records what the no-Keycloak POC executes, what remains isolated POC state, and
what is deliberately unavailable. A visible page is not evidence that the production
authorization, persistence, worker, or provider mutation path ran.

## Functional inventory

| Area | POC behavior | State owner |
|---|---|---|
| Shell and navigation | Original page composition and navigation; compact `[poc]` badge | Browser |
| Dashboard | Counts, described assets, glossary terms, and schema metrics are aggregated from the complete DataHub scroll inventory; CR counts use POC state | DataHub + POC PostgreSQL/process memory |
| Global and catalog search | Live suggestions, facets, filters, opaque next/previous cursors, result details, and lineage | DataHub |
| Resource Tree | Platform → database → schema → table expansion with complete bounded DataHub inventory reconciliation | DataHub |
| Catalog detail | Human-readable database/schema, profiled rows/size, source created date, paged columns, table/column descriptions/tags/terms, and null-safe absent values | DataHub |
| Search interaction | Detail closes on an outside click; a Resource Tree table re-queries and focuses the matching Search Result row | Browser + DataHub |
| Registration | Shared searchable Resource Tree, live DataHub detail, typed previews, CR creation, and user-created manual history | DataHub read + POC state commands |
| Change management | Registration with request attachments, review, changes requested, immutable revision/resubmission, test attachment/result, test approval, final approval, rejection/cancellation, and completion | POC PostgreSQL/process memory; object bytes optionally MinIO |
| Quality asset history tab | Same searchable Resource Tree and live DataHub columns; no fabricated quality scores, rules, runs, or trends | DataHub read |
| Chat | AUTO uses a bounded LLM classifier; explicit GENERAL/VECTOR/GRAPH bypass it. VECTOR uses DataHub metadata plus configured embedding/reranking, GRAPH uses bounded DataHub lineage and optional Neo4j knowledge edges; evidence cards preserve their live source type | DataHub/Neo4j + configured LLMs |
| Monitoring | Provider probes plus optional exact-origin Grafana dashboard embed | POC server + Grafana |
| POC USER/Admin | Registration, Knowledge and live Glossary move under the profile menu; user role is developer/data_steward/viewer/admin; System, assignee and DataHub schema scope records are user-created; a TanStack table shows every current OPEN feature permission | POC PostgreSQL/process memory + DataHub |
| Knowledge Studio/Registry | No fixture assets; user-created Domain, Draft, direct T-Box edits, live DataHub source selection, A-Box bindings, review/publication and registry reads | POC PostgreSQL/process memory + DataHub; Neo4j remains evidence/projection |
| Governance documents | No fixture documents; user-created immutable versions support submit, approve/publish or reject, Archive, product blueprints, export/evidence and MinIO attachments when configured | POC PostgreSQL/process memory + MinIO/Neo4j capability gates |
| Glossary | Terms attached to live DataHub assets and their table counts; no local seed | DataHub |

## Workflow limits that are not silently simulated as production

- The no-auth POC does not start the production DataRiver API. Compose PostgreSQL provides restart
  persistence for the isolated POC JSON state, but not the production schema, RLS, ABAC,
  multi-user maker-checker identity separation, worker receipts, retention or audit evidence.
- A single POC browser can exercise the complete change-request state machine, but one POC subject
  represents all approval roles. This is a process demonstration, not production approval evidence.
- DataHub reads are live. Registration/change records do not directly mutate DataHub. The manual
  registration receipt is explicitly marked `POC_MEMORY_ONLY`; an authenticated canonical worker
  is required for governed DataHub write/read-back evidence.
- Quality control-plane authoring/execution remains unavailable when there is no canonical quality
  service. The POC shows live assets and empty/unknown outcomes instead of invented results.
- Neo4j is started and probed when configured, but an empty Neo4j database is not seeded with
  synthetic entities. POC Knowledge/Chat records are not production graph-release evidence.
- Redis caches only short-lived DataHub inventory/detail responses. Its loss affects latency only.
  pgvector is available for bounded future vector state but does not itself accelerate catalog
  pages. Production still requires the authenticated API, workers, migrations and authorization.

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
