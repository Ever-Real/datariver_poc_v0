# ADR-0117: POC live Chat stream and DataHub profile compatibility

- Status: Accepted for the authentication-free POC only
- Date: 2026-08-12
- Refines: ADR-0089, ADR-0116
- Does not modify: production Chat authorization, canonical Catalog ownership, or provider write
  authority

## Context

The POC browser waited for a JSON Chat result and replayed synthetic `IN_PROGRESS` workflow rows
after completion. The first semantic question also waited for the complete DataHub inventory to be
embedded. This hid real progress and coupled user latency to a rebuildable projection refresh.
DataHub connector versions also expose full-table profile observations differently: multiple
profiles can be returned, some sampled profiles are newer than the full-table observation, and
reviewed legacy source extensions may put row count or byte size into DatasetProperties custom
properties. Reading only the first profile lost valid Oracle and PostgreSQL observations.

## Decision

The POC server exposes a same-origin SSE Chat endpoint. It emits workflow events when the real
authorization, routing, retrieval, reranking, composition, citation and persistence stages start or
finish, then emits exactly one final result. The POC browser consumes this stream directly and does
not manufacture progress events. Fast greeting, definition, discovery and graph heuristics execute
before any whole-inventory read; the bounded typed classifier remains the fallback. No user text is
accepted as Cypher, GraphQL or provider request syntax.

Semantic retrieval embeds the query immediately, searches already persisted pgvector rows, and
incrementally embeds a bounded DataHub lexical candidate window when that binding is empty. A
complete hash-incremental reconciliation is scheduled in the background at a bounded interval.
The question therefore does not wait for full-inventory rebuild, while the full projection remains
the eventual table-level recall surface described by ADR-0116.
Graph composition carries only the resolved table identity, bounded provider description and
directional relationships. Column-detail evidence remains available to exact metadata questions
but is not repeated into a lineage prompt. Because lineage relationships are already typed provider
facts, the graph route renders the upstream/downstream report deterministically instead of waiting
for a second Chat-model pass. Exact cross-platform matches remain separate evidence items; a fuzzy
fallback is limited to the highest-ranked candidate and is labelled as a candidate in the answer.
When DataHub full-text search fails to rank an exact physical or qualified name in its bounded
result page, entity resolution rechecks the cached complete DataHub inventory before using a
semantic candidate. This does not create a second source of truth: both paths remain provider reads.

Catalog detail requests read up to ten DataHub DatasetProfiles, discard query/sample profiles, and
choose the newest profile containing a usable table metric. An absent partition marker is accepted
as table-level for connector compatibility. If a metric is absent, only the following
case-insensitive, numeric DatasetProperties custom-property keys are accepted:

- row count: `row_count`, `rowCount`, `rows`, `num_rows`, `datariver.row_count`
- bytes: `size_in_bytes`, `sizeInBytes`, `size_bytes`, `datariver.size_in_bytes`
- created date: `created_at`, `createdAt`, `created_date`, `creation_date`,
  `table_created_at`, `datariver.created_at`

Typed `DatasetProperties.created` and full-table DatasetProfile values always take precedence.
Sample row counts never become table row counts. Values are parsed only as non-negative safe
integers or valid timestamps and report their metric provenance. Missing values remain unknown;
the adapter never invents zero, current time, or a database-specific estimate.

## Consequences

- Workflow becomes visible as soon as the server accepts a question, including during a slow
  provider call.
- A cold semantic question pays only for its query vector and bounded candidate priming; background
  reconciliation improves later recall without blocking the response.
- Custom properties are a narrow compatibility boundary, not a general metadata pass-through.
- Existing DataHub assets still show unavailable fields until the connector or approved extension
  actually emits an allowlisted observation.
