# ADR 0127: K9 Canonical Managed Graph Contracts (PROPOSED)

## Status
PROPOSED (pending independent semantic acceptance)

## Context
Per Knowledge Studio Redesign PRD (Phase 1~5), the `CATALOG_MIRROR` (metadata-lineage) and `CURATED_KNOWLEDGE` (data-glossary) system-managed graph assets require strict separation of source reading from mapping execution. They must be defined via atomic, versioned semantic contracts (T-Boxes), immutable source field projections, and bounded A-Box mapping rules without fallback to Cypher/SQL, arbitrary REST endpoints, or mutating Graph UUID materialization within the definition phase.

## Decisions

### 1. Envelope, Deep Freeze & Hash Separation
All contracts are separated into a lifecycle-bearing recursively frozen PROPOSED envelope (`identity`, `lifecycle`, `version`, `document_hash`) and an immutable canonical document (`contract_kind`, `contract_version`, and rule details). Both envelope and documents are recursively deeply frozen (`Object.freeze`) at definition to prevent implicit mutation. 
The `document_hash` strictly hashes the exact structural blueprint. This cryptographic document hash is uniquely distinct from any future **runtime snapshot hash** (which hashes deterministically the executed data collector output), preventing confusion between the contract definition and a live runtime trace.

### 2. Declarative Source Contracts and Required Product Seams
This proposal defines schemas/pins only and confers no executable runtime, caller-supplied principal, graph-materialization, or publication authority. Current public routes are recorded exactly, including the catalog route's 100-item cap; the separate 250-item boundary belongs only to the private provider scroll. The catalog/lineage routes are inputs to a future module-private `collectLineageInventorySeam(authCtx)` inside existing `poc-server.mjs`, invoked only after `context.principal` and using existing internal DataHub reads. It must emit server-owned exhaustive inventory and per-asset `UPSTREAM`/`DOWNSTREAM` cursor/membership evidence, reconcile each provider total, reject repeated/nonterminal-at-bound cursors and truncation, bind the authority pin, and fail closed.

The glossary public route returns only `{items}` and is explicitly insufficient to prove provider-scroll completeness. A future module-private `collectGlossaryInventorySeam(authCtx)` inside `poc-server.mjs`, also after `context.principal`, must use existing internal DataHub queries and Product classification checks, emit server-owned exhaustive evidence, reject incomplete/repeated/bound-exhausted cursors, bind the authority pin, and rehydrate assignment classification, failing closed on absent/unknown/above-INTERNAL values. Neither seam is implemented or exported by this contract-design slice.

### 3. Completeness, Determinism, and Fixed Bounds
The frozen source contracts declare `FULL_SERVER_INVENTORY_NO_QUERY`, distinct public/provider page limits, fixed per-direction lineage bounds, fixed glossary-assignment bounds, canonical identities, normalized snapshot-hash requirements, total reconciliation, hierarchy-cycle rejection, and other fail-closed semantics. These declarations are requirements for a later Product implementation; they are not proof of runtime completeness. A runtime snapshot may become authoritative only after the future Product-private seam supplies exhaustive server-owned trace evidence under the resolved authority pin. Same source/version/hash, mapping/version/hash, T-Box/version/hash, and managed policy must produce the same canonical result; missing pins, drift, incomplete traversal, hierarchy cycles, classification failure, or bound exhaustion are `NO PUBLISH`.

### 4. Semantic Hierarchy Definitions
GlossaryNode is the sole minimal new class introduced because the accepted vocabulary has no container class; it cannot expand authority and remains strictly compatible with BusinessTerm, Table, Column, HAS_PARENT_NODE, and MAPPED_TO_TERM.
- **Lineage `DEPENDS_ON` Reversal**: The underlying `source_asset_id -> target_asset_id` implies data flow (upstream -> downstream). The T-Box models dataset dependence via `DEPENDS_ON`. Therefore, the `EDGE_LINK` reverses mapping bounds explicitly: the downstream target depends on the upstream source (`edge_source: edges.target_asset_id, edge_target: edges.source_asset_id`).
- **Glossary Direct-Parent Hierarchy**: Parent structures (`parent_terms`) arrive sequentially ordered `root-to-direct-parent`. We derive direct edges specifically (`term_parent_edges` and `node_parent_edges`) by projecting only to the immediately preceding element in the sequence, deduplicating the output securely. Canonical assignments are rejected aggressively if topological cycles or conflicting canonical identities arise. We augment the graph with exactly two distinct graph relations bounding `HAS_PARENT_NODE` exclusively for terminology and nodal nesting without inventing arbitrary ancestor projections.

### 5. Structured Entity Identities and Constraints
The ambiguous global `canonical_entity_identity` (e.g., `'urn'`) is modernized to an exact structured dictionary contract spanning every discrete array projection (`terms`, `parent_nodes`, `term_parent_edges`, `table_assignments`, etc.). Asset assignment identities (`id`) must identically match canonical DataHub patterns representing origin locations exactly: `TABLE:<canonical DataHub Dataset URN>` and `COLUMN:<canonical DataHub Dataset URN>:<nonempty field path>`. Product-projected glossary URNs are prefix-validated and can contain "." or ":" in the identity suffix, rejecting empty suffixes, whitespace/control characters, and over-4096 total lengths.

### 6. Lifecycle Control
These artifacts remain `PROPOSED`. They confer no UUID, DB, graph, scheduler, runtime, acceptance, or publication authority. ADR-0058's existing Studio lifecycle remains authoritative: `DRAFT -> REVIEW -> PUBLISHED`. Only after CONTROL_PLANE and fresh independent semantic acceptance may artifacts enter that existing lifecycle; a `PUBLISHED` T-Box identity/version/immutable checksum, plus immutable source/mapping pins, is required before K9 graph identity/materialization. `document_hash` is not itself a `PUBLISHED` T-Box checksum.
