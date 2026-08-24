# ADR-0130: DataHub semantic model V2 for managed metadata and lineage projections

- Status: Accepted for the local DEV/Product slice
- Date: 2026-08-24
- Owners: Data Architecture, Knowledge Platform, Security Architecture, Product
- Refines: ADR-0040, ADR-0058, ADR-0069, ADR-0127, ADR-0128, ADR-0129
- Does not authorize: DataHub mutation, Knowledge Studio model changes, unrestricted graph export,
  PREP/OPS promotion, or a second metadata authority

## Context

The accepted managed projections preserve the exact K9 graph identities and use DataHub as their
source. The active Metadata Master release, however, represents Tags, Domains and source properties
only as strings on Table or Column nodes. Its Glossary hierarchy projects the complete
`parentNodes` ancestry as if every ancestor were a direct parent, and its relations carry no
source-aspect, confidence or observation evidence. The Default Lineage release keeps only Table
endpoints and discards the provider's relationship provenance. The Catalog vector generation is
safe and authorization-scoped, but its lifecycle is independent from the managed refresh receipt.

The current DataHub v1.6.0 environment has Dataset, Schema Field, Glossary Term, Glossary Node, Tag
and Domain metadata. Container, Platform Instance, Structured Property, DataFlow, DataJob and
fine-grained lineage currently have zero rows. The Product must support those provider-generic
types when a different DataHub environment contains them, while never fabricating absent source
facts or adding the current environment's business vocabulary to source code.

## Decision

### 1. One provider-generic source snapshot contract

One managed refresh acquires an exhaustive, deterministic DataHub snapshot under the existing K9
service authority pin. The snapshot records the DataHub version, Catalog generation, observation
time, exhaustive Dataset and Glossary evidence, Table lineage evidence, and optional structured,
fine-grained, DataFlow and DataJob evidence. The two graph projections and semantic index bind the
same deterministic `source_snapshot_id`.

The snapshot is a rebuild input and receipt, not a new authority. DataHub remains canonical and
PostgreSQL remains the active-pointer, policy, receipt and last-known-good authority. The Product
uses supported GraphQL and OpenAPI contracts; it does not scrape the UI or read DataHub backing
storage.

### 2. Typed Metadata Master without pairwise expansion

The V2 projection supports these generic node kinds when source evidence exists:

- Dataset/Table/View and Schema Field/Column;
- Glossary Term and Glossary Term Group;
- Tag, Domain, Container and Data Platform Instance;
- DataFlow and DataJob were evaluated as optional process entities. The current source has none;
  Dataset lineage derived by DataHub from job input/output is still projected, while dedicated
  process nodes remain absent until canonical process evidence and authorization scenarios exist;
- Semantic Concept and Unit of Measure only under the evidence rules below.

Canonical DataHub URNs are node identities. Table and Column compatibility identities remain
`TABLE:<dataset URN>` and `COLUMN:<dataset URN>:<field path>`. Refresh never derives identity from
display text, array position or a random value.

Table-to-Column, assigned Glossary Term, assigned Tag, Domain, Container and Platform Instance
relations are explicit hub relations. Tables sharing a Tag or Term are not connected pairwise.
Semantic similarity stays in vector top-k retrieval by default and is not persisted as a complete
`SIMILAR_TO` graph.

Description and documentation remain bounded properties and semantic documents. Tokens do not
become nodes. A derived Semantic Concept requires bounded confidence, provenance, deterministic
normalization and a degree cap; this increment creates no free-standing concept node from arbitrary
description text.

### 3. Explicit hierarchy and relation provenance

Glossary direct relations come from the entity's explicit outgoing DataHub relationship evidence.
`parentNodes` ancestry is retained as source context but is not projected as multiple direct edges.
Known DataHub schema relations map to the generic `IN_TERM_GROUP`, `CONTAINS_TERM`,
`INHERITS_FROM` or `RELATED_TO` contract. Unknown provider relations are not guessed; a bounded
generic related edge may retain the exact provider relation type as evidence only when both
endpoints are supported glossary entities.

Every projected relation retains:

- `source`, `source_aspect` and exact provider relation type where applicable;
- `explicit_or_inferred`, bounded confidence and source entity URN;
- source observation/audit time when available;
- projection model version and source snapshot identity.

Missing provider audit time remains null. It is not replaced by a fabricated source timestamp.

### 4. Units and aliases remain evidence-bound

Aliases are searchable properties of their canonical entity. Precedence is explicit DataHub
alias/custom/structured metadata, Glossary documentation/relations, business/display name, then a
deterministic normalized naming form. No production synonym dictionary or query-time synonym model
call is introduced.

An explicit Unit of Measure requires a structured/custom property or assigned Tag/Term whose
provider metadata explicitly declares unit semantics. An inferred candidate requires a generic,
configuration-independent marker in source text or another bounded standards-based parser result.
It is stored as inferred with confidence below 1, extraction method and source text. A value is not
accepted merely because it resembles a domain term, and derived values are never written back to
DataHub. If a source environment has no qualifying unit evidence, the metric remains zero.

### 5. Lineage is a provenance-preserving DataHub projection

Default Lineage retains DataHub Dataset lineage as the canonical Table-level source and adds
fine-grained Column lineage when the supported DataHub API returns it. DataHub-projected Dataset
lineage continues to include dependencies derived from DataJob input/output without fabricating
DataFlow/DataJob nodes in an environment where those entities are absent. Each edge records level,
upstream/downstream URNs, provider source aspect,
manual/audit/path/transformation evidence when available and the source snapshot identity.

The refresh computes added, removed and changed semantic edges relative to the previous active
release. It builds a new namespace, validates complete read-back, counts, duplicate/dangling/orphan
sanity, graph hashes and smoke queries, and only then changes the PostgreSQL active pointer. Failure
leaves the prior release serving and cleans failed staging data.

### 6. Quality and vector receipts are versioned read-model evidence

The active manifest records model version, source snapshot, entity and relation counts by type,
explicit/inferred counts, duplicate and orphan counts, degree statistics, top bounded hubs,
pairwise-clique count, semantic/unit counts, lineage levels and source coverage. These fields are
visible in the managed Asset read model but do not change authorization.

The Catalog semantic document includes the same authorized DataHub name, business name,
description, field, Tag, Glossary, Domain and bounded explicit property evidence. Its binding
contract is versioned. Promotion remains generation-fenced and last-known-good; obsolete bindings
may be deleted only after the current binding and generation are verified active. Native Chat and
MCP continue to call the same Core Knowledge functions.

Semantic materialization ownership is fenced across Product processes by one PostgreSQL session
advisory lock derived from the exact `(binding_hash, source_generation)`. A waiting process acquires
the lock only after the current owner exits or finishes, then rechecks the durable active-generation
pointer before performing provider work. It therefore reuses a generation that another process
already promoted instead of embedding the same documents again. The existing process-local promise
remains an optimization only; it is not the cross-process authority. A process crash closes its
dedicated database session and releases the lock.

Fixed DataHub refresh reads use a 60-second request bound and at most one retry for timeout/abort
conditions not caused by the refresh cancellation signal. Other provider errors fail closed. This
does not weaken source completeness or LKG preservation.

### 7. Domain independence is a release gate

Production graph-building, routing, retrieval and unit logic may contain only platform-generic
DataHub aspect/entity/relation mappings. Business vocabulary, current Dataset/Column identities,
test-question mappings, domain synonym dictionaries and graph-trigger keyword tables are forbidden.
Fixtures and evidence may contain the current DataHub data, but those values cannot select a code
path.

## Consequences

- Existing K9 graph UUIDs, Studio pins, Router taxonomy and Cytoscape contracts remain stable.
- A new DataHub environment can populate supported node/edge types without a source edit; absent
  metadata produces honest zero coverage rather than fabricated facts.
- V2 may increase graph edges through explicit Tag/Domain assignments, but not through pairwise
  cliques or all-pairs similarity.
- The active V1 release remains queryable until a V2 staging release passes the full read-back and
  authorization gates.
- Retrieval-source changes require one final 60-question plus boundary regression on the exact
  Product, but GENERAL/VECTOR/GRAPH public semantics do not change.

## Verification

1. Fixed DataHub contract tests cover exhaustive paging, cursor/total drift, optional aspect
   absence and generic entity mapping.
2. Mapper tests cover stable identity, explicit/direct hierarchy, Tag/Term/Domain hubs, no pairwise
   clique, provenance, units, duplicate/dangling rejection and deterministic hashes.
3. Refresh tests cover shared snapshot identity, NO_OP, staging read-back, atomic promotion,
   failure-safe LKG, recovery, orphan cleanup and same-generation producer serialization.
4. Quality evidence reports before/after counts and zero duplicate edges/nodes.
5. Authorization tests prove an allowed semantic hub cannot reveal another denied Dataset or edge;
   MCP and native structured results remain consistent.
6. Runtime acceptance uses actual DataHub lineage and metadata, one bounded V2 refresh, managed UI,
   representative semantic/lineage scenarios, final Router 60 + boundary, hard reload and cleanup.
7. Static source inspection reports `DOMAIN_SPECIFIC_PRODUCTION_HARDCODING = NONE`.
