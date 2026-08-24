# ADR-0129: Read-only Cytoscape graph visualization boundary

- Status: Accepted for the local DEV/Product slice
- Date: 2026-08-24
- Refines: ADR-0058, ADR-0118, ADR-0127, ADR-0128
- Does not authorize: Knowledge Studio renderer changes, graph-authority changes, PREP/OPS
  promotion, or unrestricted graph export

## Context

The Product has four read/explore graph surfaces implemented by two unrelated renderers: a custom
Catalog lineage SVG/DOM canvas and the shared React Flow `FlowCanvas`. The same `FlowCanvas` is also
used by Knowledge Studio authoring. Replacing that shared component would couple a read-only
visualization migration to editing, validation, unsaved-state, and release workflows that are
explicitly outside this workstream.

The managed Metadata Master graph currently contains more than twelve thousand nodes and twenty-four
thousand edges. Its Registry preview requests the first 200 nodes rather than a focused neighborhood.
That is bounded, but it is neither an entity-focused explorer nor an extensible large-graph UX.
Authorization is already enforced when the canonical managed release is projected for a principal.

## Decision

### 1. Separate read/explore rendering from Studio authoring

Read-only Catalog lineage, Registry preview, Knowledge GraphRAG evidence, and Change Request impact
views use a dedicated Cytoscape.js component. Knowledge Studio's Graph Builder, Data Enricher,
ingestion editor, session state, and shared React Flow component remain unchanged. React Flow remains
a Product dependency while Studio needs it.

The Product pins stable `cytoscape` 3.34.1 in the application lockfile. No CDN, preview release, or
layout extension is introduced. LINEAGE uses the built-in directed breadth-first layout; bounded
METADATA_MASTER and other semantic graphs use the built-in CoSE layout. This keeps the dependency and
bundle boundary smaller while graph-type layout policy remains configuration-driven.

### 2. Preserve canonical APIs and identities

Core services continue to return canonical graph nodes and edges. A frontend view-model adapter maps
those DTOs to Cytoscape element definitions. Nodes use their canonical node id. Edges use their
canonical relation id; Catalog lineage, whose public DTO exposes only endpoints, derives a stable
relationship identity from its canonical source id, target id, and LINEAGE relation type. Array
positions, labels, and per-render random ids are prohibited.

The backend never returns Cytoscape-specific element or style documents. Removing Cytoscape would not
change the graph-service contract.

### 3. Bound managed graph exploration after authorization

The existing managed snapshot read route accepts optional renderer-neutral focus, hop, node/edge cap,
and node/relation type filters. The server first constructs the principal's authorized canonical
release, then resolves the focus and traverses that authorized projection. The response contains only
the bounded canonical snapshot plus bounds metadata. An unauthorized node, edge, name, count, or
existence is never sent for client-side hiding.

Initial managed visualization is root-focused and bounded. Expansion requests one authorized
neighborhood at a time and merges it by canonical identity. Collapse removes that expansion from the
client view; reset returns to the initial bounded root. Limits are explicit and truncation is shown as
“N of M authorized” rather than silently dropping relationships.

### 4. Make renderer lifecycle and non-canvas access explicit

Each mounted read view owns one Cytoscape instance, listeners, resize observer, and layout lifecycle.
Unmount destroys the instance and subscriptions. Selection is stored by canonical id and restored
across layout reruns. Zoom, fit, reset, focus, search/highlight, direction highlighting, expand, and
collapse are available through keyboard-accessible DOM controls.

The canvas is supplemented by a DOM legend and selected node/relation detail. Node type is conveyed by
shape and text as well as color. Loading, empty, no-authorized-result, entity-not-found, graph-query,
layout, and partial-expansion failures remain distinguishable.

## Consequences

- Chat routing, graph traversal, DataHub ingestion, refresh, vector search, MCP, and managed graph
  identities are unchanged.
- Metadata Master never requires the browser to receive the whole 12k/24k graph for first render.
- The Cytoscape chunk is used only by read/explore surfaces; authoring continues on its accepted
  renderer.
- A backend change is limited to a renderer-neutral bounded read-model extension and must retain the
  existing authorization and canonical snapshot semantics.
- Existing Router 60/60 evidence remains valid unless the routing, retrieval, graph traversal, or
  authorization contract changes.

## Verification

1. Adapter tests prove stable ids, canonical endpoints, graph-type layouts, and duplicate rejection.
2. Component tests prove DOM controls/details and one destroy per mounted Cytoscape instance.
3. Managed snapshot tests prove authorization-first root/depth/filter/cap behavior.
4. Authenticated runtime checks cover real Default Lineage and Metadata Master views, GraphRAG and CR
   views, hard reload, representative Chat/UX regression, and Studio authoring non-regression.
5. Performance evidence records request, transform, layout, first usable render, expansion, interaction,
   and repeated open/close lifecycle observations.
