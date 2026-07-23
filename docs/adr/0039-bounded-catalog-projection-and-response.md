# ADR-0039: Bounded catalog projection and explicit response truncation

- Status: Accepted
- Date: 2026-07-23
- Refines: ADR-0006, ADR-0035

## Context

DataHub descriptions and metadata arrays are provider-controlled. Returning up to 100 unbounded
rows from catalog search can exhaust a low-spec API host or browser even though cursor pagination
limits the row count. A page limit is not a byte or memory limit.

## Decision

The rebuildable `catalog.assets_projection` stores at most 10,000 description characters, 100 tags,
100 glossary terms and 1,000 column paths per asset. The external URN is non-empty and at most
4,096 characters, and every projected array item is a string. DataHub remains canonical. Alembic
`0045` truncates only non-identity projection values, records separate description/tag/term/column
truncation provenance and adds validated CHECK constraints; it rejects an invalid external URN
rather than changing canonical identity. Its compatibility bridge accepts only exact same-name
columns and constraints and fails closed on definition drift.

The HTTP search summary further returns at most 1,000 description characters, 20 tags and 20 terms,
with 240 characters per tag or term. An asset detail remains bounded at 10,000 description
characters, 100 tags and 100 terms, with 1,000 characters per value. The response carries separate
`description_truncated`, `tags_truncated` and `terms_truncated` evidence. Schema-field type,
description, term and tag values carry their own truncation evidence. Clients must surface that
evidence rather than implying completeness.

Search match evidence remains independently bounded. Cache schema versions change whenever the
meaning or shape of cached search/detail/facet/suggestion evidence changes. Cache readers bind
workspace and requested limit and reject oversized or malformed collections. Default search avoids
an exact full-result count: `total_exact=false` declares that `total` is only the page-local proven
lower bound. Facets use the same search-field predicate and one server-ranked PostgreSQL
`GROUPING SETS` aggregation.

## Consequences

- A single catalog page has a deterministic application-level response ceiling independent of
  provider metadata size. The provider transport's eight-MiB response cap remains a separate guard.
- Full canonical metadata is obtained from DataHub through governed provider workflows; the local
  search projection is not an archival copy.
- Existing oversized projection values are shortened during `0045`; operators should schedule the
  update in a maintenance window and rebuild the projection after rollout.
- Pre-0045 values exactly at a new maximum are conservatively marked truncated because their former
  provenance cannot be reconstructed.
- PostgreSQL execution-plan and end-to-end response-size gates still require a representative
  target dataset; source tests cannot establish production latency.
