# POC functional parity and provider boundaries

This document records what the no-Keycloak POC executes, what remains browser-memory state, and
what is deliberately unavailable. A visible page is not evidence that the production
authorization, persistence, worker, or provider mutation path ran.

## Functional inventory

| Area | POC behavior | State owner |
|---|---|---|
| Shell and navigation | Original page composition and navigation; compact `[poc]` badge | Browser |
| Dashboard | Counts, described assets, glossary terms, and schema metrics are aggregated from the complete DataHub scroll inventory; CR counts are the current POC session | DataHub + browser memory |
| Global and catalog search | Live suggestions, facets, filters, opaque next/previous cursors, result details, and lineage | DataHub |
| Resource Tree | Platform → database → schema → table expansion with complete bounded DataHub inventory reconciliation | DataHub |
| Catalog detail | Human-readable database/schema, paged columns, table/column tags and terms, and null-safe quality values | DataHub |
| Registration | Shared searchable Resource Tree, live DataHub detail, typed previews, CR creation, and user-created manual history | DataHub read + browser memory commands |
| Change management | Registration, review, changes requested, immutable revision/resubmission, test attachment/result, test approval, final approval, rejection/cancellation, and completion | Browser memory; attachments optionally stored through MinIO |
| Quality asset history tab | Same searchable Resource Tree and live DataHub columns; no fabricated quality scores, rules, runs, or trends | DataHub read |
| Chat | Runs only when DataHub and Chat LLM are both live; optional embedding/reranking stages; evidence comes only from returned DataHub assets | DataHub + configured LLMs |
| Monitoring | Provider probes plus optional exact-origin Grafana dashboard embed | POC server + Grafana |
| Admin | POC user creation is browser-memory only; deployment system configuration is redacted and provider probes are live | Browser memory + POC server |
| Knowledge and governance documents | No preloaded fixture records are returned | Empty until a separately approved canonical control plane exists |

## Workflow limits that are not silently simulated as production

- The no-auth POC does not start the production DataRiver API and therefore does not provide
  durable PostgreSQL workflow state, Valkey cache/leases, RLS, ABAC, multi-user maker-checker
  identity separation, worker receipts, or restart persistence.
- A single POC browser can exercise the complete change-request state machine, but one POC subject
  represents all approval roles. This is a process demonstration, not production approval evidence.
- DataHub reads are live. Registration/change records do not directly mutate DataHub. The manual
  registration receipt is explicitly marked `POC_MEMORY_ONLY`; an authenticated canonical worker
  is required for governed DataHub write/read-back evidence.
- Quality control-plane authoring/execution remains unavailable when there is no canonical quality
  service. The POC shows live assets and empty/unknown outcomes instead of invented results.
- Neo4j is started and probed when configured, but an empty Neo4j database is not seeded with
  synthetic entities. A canonical Knowledge registry/release service is required before Knowledge
  CRUD and publication can be claimed.
- PostgreSQL or Valkey containers alone cannot restore the original features: those features also
  require the authenticated API, workers, migrations, authorization policy, and durable identity
  semantics. They are therefore not added to this isolated no-auth provider gateway.

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
