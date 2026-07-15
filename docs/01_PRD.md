# Product requirements document

## Product statement

DataRiver gives data consumers, stewards, engineers, and governance operators one secure workspace to discover externally managed DataHub assets, request and approve metadata changes, observe platform health, curate versioned knowledge graphs, and use governed evidence in Chat and analysis APIs.

## Personas

| Persona | Primary outcome |
|---|---|
| Data consumer | find trustworthy, permitted data and understand lineage/context |
| Data steward | register assets and curate metadata/ontology with controlled approval |
| Approver | compare changes, validate impact, approve/reject with separation of duties |
| Data engineer | run durable integrations and diagnose/replay failed jobs |
| Data/knowledge architect | author ontology and immutable graph releases with provenance |
| API consumer | use a versioned, quota-bound graph analysis product without raw Cypher |
| Security/operations admin | manage attributes/policies and audit every decision and side effect |

## Functional requirements

- `FR-CAT-001`: search, autocomplete, filter, paginate, view detail, lineage, glossary, ownership, quality, and freshness through a DataHub facade.
- `FR-REG-001`: upload by direct multipart object transfer; validate and dry-run without loading the API process memory.
- `FR-GOV-001`: create, review, test, approve, queue, apply, reconcile, reject, cancel, and retry change requests with legal transition checks.
- `FR-MON-001`: expose capability-based health, job/audit status, metrics links, and actionable degraded states without blocking unrelated features.
- `FR-CHAT-001`: create sessions and answer from only authorized evidence, including source citations, policy decision, graph/catalog version, and degraded behavior.
- `FR-KG-001`: define versioned ontology, import/extract proposals, edit changesets, validate, review, publish immutable releases, rebuild projections, compare, deprecate, and rollback active pointers.
- `FR-SHR-001`: publish release-pinned JSON-LD/edge-list exports and typed analysis-query templates as API products with grants and quotas.
- `FR-ADM-001`: manage workspaces, subject attributes, resource attributes, policies, connections by secret reference, retention, and audit export.
- `FR-SEED-001`: install or remove a deterministic deep semiconductor value-chain pack only by explicit opt-in.

## Non-functional requirements

- `NFR-SEC-001`: default deny, deny precedence, application ABAC, PostgreSQL RLS defense in depth, separation of duties, short-lived credentials, and no secret response/logging.
- `NFR-REL-001`: canonical writes and outbox events commit atomically; external completion requires reconciliation.
- `NFR-MEM-001`: a 1 GiB upload must increase API RSS by no more than 64 MiB; list endpoints cap page size at 100.
- `NFR-PERF-001`: initial target on the documented reference host: cached search p95 <= 300 ms, uncached search p95 <= 800 ms, CR write p95 <= 400 ms, error rate < 1% under target load.
- `NFR-PORT-001`: no absolute user paths; clean clone starts through documented Docker Compose commands on Linux, Windows/WSL2, and macOS.
- `NFR-OBS-001`: every request/job has trace/request/correlation IDs; logs are structured and redact payloads/secrets.
- `NFR-ACC-001`: keyboard-operable responsive UI, visible loading/empty/error/stale states, WCAG 2.2 AA target.
- `NFR-EVO-001`: module boundaries are architecture-tested and external systems implement inward-facing ports.

## Product boundaries

DataRiver does not replace DataHub storage, operate the enterprise identity provider, expose GraphQL/Bolt/Cypher pass-through, act as a general BI tool, or allow LLMs to approve/publish changes. DataHub itself is never started or deleted by the default Compose deployment.

## Success measures

- zero cross-workspace/unauthorized evidence exposure in the policy matrix;
- 100% of applied changes linked to request, approval, outbox, attempt, reconciliation and audit records;
- 100% of published graph assertions have provenance;
- clean clone bootstrap and documented recovery drill pass;
- common user journeys complete without placeholder/mock production data.
