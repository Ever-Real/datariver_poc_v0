# ADR-0128: Chat knowledge router and managed metadata projections

- Status: Accepted for the local DEV/Product slice
- Date: 2026-08-24
- Refines: ADR-0058, ADR-0085, ADR-0092, ADR-0116, ADR-0118, ADR-0121, ADR-0127
- Does not authorize: PREP/OPS promotion, DataHub mutation, unrestricted graph queries, or a
  second knowledge authority

## Context

The two K9 system-managed graphs are canonically published in Knowledge Studio, but the POC
Registry lists only browser-owned Studio drafts. The K9 runtime projection was deliberately removed
after its earlier isolated acceptance, so the accepted graph identities are neither visible as
managed Assets nor currently queryable through the POC graph store. Creating replacement graph
identities would duplicate canonical state.

The existing DataHub catalog projection already provides complete table and column metadata plus
pgvector embeddings. The existing Chat surface already exposes GENERAL, VECTOR, and GRAPH,
but AUTO uses source-code regular expressions for relationship terms before its bounded model
classifier. That makes a general definition containing a graph-related word indistinguishable from
an internal traversal request. K8 MCP exposes only two exact-release Knowledge tools and must remain
an adapter over the same core services.

## Decision

### 1. Reconcile, never recreate, the managed graph identities

The exact K9 graph, ontology, and Studio Release pins remain canonical. A server-owned managed-Asset
read model joins those pins to the K9 policy and latest durable refresh receipt. Registry and Chat
APIs merge that read model with ordinary Knowledge Assets by graph id. Reconciliation cannot create
a Studio graph, change a graph UUID, or ingest a duplicate namespace.

The user-facing names are Default Lineage Graph for the existing CATALOG_MIRROR graph and
Metadata Master Graph for the existing CURATED_KNOWLEDGE graph. Their canonical Studio slugs,
types, releases, and ids remain unchanged.

### 2. Keep DataHub canonical and projections rebuildable

DataHub remains the source for dataset/table identity, columns, descriptions, business names, tags,
glossary terms, domains, and lineage. The Metadata Master projection extends the already accepted
table/column/term model with bounded source properties; descriptions remain properties and vector
documents rather than token nodes. Glossary terms are the canonical semantic concepts. No source
dictionary or query-time synonym generation is introduced.

Both managed graphs and the semantic vector generation use versioned build, read-back validation,
and atomic active-pointer promotion. A failed build records failure and leaves the last successful
pointer serving. Assets above the configured service ceiling are excluded before mapping and may
not leak through lineage neighbors or MCP results.

The accepted Studio ontology documents remain unchanged. The runtime projection authority ceiling
is a separate Product policy overlay: it may be raised only to a canonical classification supported
by the existing access model, every projected node retains its source classification, the managed
Asset is classified at that ceiling, and the dedicated refresh subject must have an equal or higher
security grade. This permits the real DEV DataHub lineage to be projected without downgrading its
classification or exposing it to lower-grade users.

### 3. Make refresh policy configuration-driven

The existing K9 scheduler, PostgreSQL advisory lock, and durable receipt are retained. Refresh mode,
time zone, hour, and minute are parsed from a closed configuration contract. The default is
DAILY at 02:00 Asia/Seoul. The closed modes are DAILY, HOURLY, MANUAL, and EVENT_DRIVEN;
non-timer modes retain the same manual trigger and unsupported values fail at startup. This is not
a generic scheduler framework.

### 4. Use one semantic planning call

Explicit public modes retain their established behavior; AUTO uses one strict structured planning
call. That call returns the public route,
primary and secondary concepts, entity type hints, and a closed relationship intent. It receives
the currently authorized graph Asset capability metadata.

No source-code graph-trigger keyword table, semiconductor special case, or synonym dictionary is
used. A deterministic Graph Asset resolver maps the returned relationship intent to an authorized
Asset's declared capabilities. VECTOR entity resolution may precede GRAPH traversal without
changing the public route.

GENERAL performs no internal retrieval. VECTOR combines the existing lexical, pgvector, DataHub
metadata, glossary, tag, description, and business-name evidence. GRAPH performs bounded traversal
against the selected active graph projection, with live DataHub lineage used only for entity
resolution/cross-check and last-known-good fallback evidence.

### 5. Keep MCP as a closed adapter

Native Chat and MCP call the same core metadata search, Asset discovery, entity resolution, and
graph traversal functions. MCP adds closed, read-only tool schemas and fixed service
authentication; it contains no duplicated search or lineage algorithm. Internal Chat remains on
the native adapter unless the runtime benchmark shows equivalent authorization/correctness and no
meaningful p95 regression.

### 6. Expose status without exposing secrets

The Registry list and detail drawer show source, default status, semantic capabilities, active
version, node/edge counts, last/next refresh, refresh mode, last result, and vector readiness.
Failure is a visible state while the previous active version remains queryable. Route evidence may
record concepts, selected graph id, retrieval method, latency, and call count, but never provider
tokens, passwords, prompt secrets, or unauthorized entity names.

## Consequences

- The accepted K9 graph UUIDs and Studio publication authority remain stable.
- A missing projection is represented as PENDING or FAILED, not as a fabricated empty success.
- Classifier/provider unavailability remains fail-closed for AUTO; explicit routes retain their
  established behavior.
- Production routing contains no domain vocabulary, test-question map, or graph keyword regex.
- PREP/OPS and the existing G1/G2/G3/G4 and durable-storage HOLDs remain unchanged.

## Verification

1. Registry reconciliation returns each exact managed graph id once and creates no Studio graph.
2. A real authorized DataHub lineage path produces a versioned K9 release and bounded traversal.
3. Metadata Master contains table, column, term and source semantic properties without description
   token explosion.
4. Identical refresh is NO_OP; failed refresh preserves the active pointer.
5. Boundary questions select GENERAL/VECTOR/GRAPH by semantic intent and the curated 60-question
   route set uses the production path.
6. Native and MCP results retain the same authorization and structured provenance; latency is
   measured before selecting the internal adapter.
7. Authenticated browser verification proves managed Asset status, Chat routes, hard reload, and
   failure-state visibility.
