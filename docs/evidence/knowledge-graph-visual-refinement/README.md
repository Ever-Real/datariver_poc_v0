# Knowledge Graph visual refinement evidence

This bundle closes the read-only Knowledge Graph visual refinement on Product
`179093643f4cfa2dd808c0c27240f7f49f68063c`, progressing from accepted KG2 Product
`e8040e6fedb3b675c5b26854292d08e2010e2ba8` and Evidence
`84fd42f96592c42ca136f8221fec9ef3b45d4bb9`. The exact Product OCI was deployed only
to the existing DEV `39083` web service; PostgreSQL, Neo4j, Redis, managed graph
projections, refresh scheduling, Router and MCP services were not rebuilt or reset.

## Renderer scope and visual contract

The existing shared `CytoscapeReadGraph` remains the renderer for Catalog/Search
lineage, managed graph exploration, GraphRAG evidence, Change Request impact and the
Catalog lineage detail reused by Chat. The adapter still consumes the canonical graph
DTO and stable canonical node/edge IDs. Knowledge Studio, its React Flow authoring
renderer, T-Box GraphBuilder, A-Box Data Enricher and release workflow were not changed.

All read-only nodes now use one fixed 36 by 36 pixel circle geometry. Selection changes
only the fixed-width border, subtle underlay and label visibility; it does not change
node geometry or the layout footprint. A central platform-generic mapping derives the
visual group and category10-like color from canonical entity types such as Dataset,
View, Column, Glossary Term, Tag, Domain, Unit, Container and Platform. It contains no
business-domain vocabulary or current DataHub entity identity.

Canvas labels are hidden by default. Hover displays only the hovered node's compact
label, keeps direct neighbors and incident edges at full opacity and dims unrelated
elements to 0.14 opacity. Hover-out removes only transient hover classes, preserving
selected node, path/search highlight and expansion state. The accessible DOM entity
list, selection/detail region, keyboard navigation, detail link and bounded expansion
controls remain available independently of hover or color.

Edges use a subtle 2.1 pixel gray base with visible directional arrows. Lineage branch
colors retain upstream/downstream meaning and Cola role constraints retain the verified
horizontal tiers. `cytoscape-cola` remains lazy-loaded and bounded; drag resumes physics,
release performs a bounded settle, and neither hover, drag nor expansion calls `fit()`.
The existing authorization-first and bounded graph API contract remains unchanged.

## Source gates

- Focused graph adapter/renderer tests: 2 files / 20 tests PASS.
- Full UI suite: 90 files / 653 tests PASS.
- ESLint, TypeScript, POC production build, static verification and `git diff --check`:
  PASS.
- Backend, Router, retrieval, authorization and graph DTO source were not changed, so
  the accepted enhanced Router 60/60 and boundary 8/8 evidence was preserved rather
  than rerun.

## Exact-Product browser acceptance

Authenticated Chrome acceptance on `127.0.0.1:39083` used real DataHub-derived graphs.

- Catalog lineage: 7 nodes / 6 edges; transform 0.1 ms, initial layout 46.5 ms,
  initial settle 891.3 ms and post-drag settle 657.8 ms. Default labels were hidden,
  the selected root retained fixed geometry, arrows and horizontal lineage direction
  remained visible, hover dimmed unrelated nodes, and the directional two-level action
  completed without viewport reset.
- Metadata Master Graph: bounded 48 nodes / 47 edges from the 12,336 / 45,775 managed
  graph; transform 0.3 ms, initial layout 48.3 ms, initial settle 1,559.8 ms and
  post-drag settle 765.4 ms. Glossary/business-term and Column colors were distinct,
  hover label/neighborhood highlighting worked, and the canvas did not eager-load the
  full graph.
- Default Lineage Graph: bounded 15 nodes / 23 edges from the 1,001 / 1,950 managed
  graph; transform 0.1 ms, layout 21.3 ms and settle 350.9 ms. Root/upstream/downstream
  tiers and arrow semantics remained intact.
- A hard reload restored the Knowledge Chat route, Metadata Master selection and the
  bounded 48 / 47 graph with the same managed v6 source state.
- Representative main Chat journeys passed: GENERAL skipped retrieval, VECTOR returned
  the canonical Default Lineage managed Asset, and GRAPH selected Default Lineage with
  actual authorized node/relation evidence.
- Knowledge Studio opened in its existing full-screen authoring flow. No Cytoscape
  canvas was present in Studio, and no Studio source file changed. The current account
  had no authorized Change Request row in the bounded date window; the shared impact
  renderer remains covered by the final UI suite and the previously accepted GV2
  runtime baseline.

## Runtime and cleanup

The DEV container was healthy with zero restarts, returned HTTP 200 for `/` and
`/healthz`, and carried exact OCI revision
`179093643f4cfa2dd808c0c27240f7f49f68063c`. Dashboard `39090` remained HTTP 200.
No temporary graph, Asset, credential, environment override or performance flag was
created. The browser used the existing authenticated DEV inspection identity and the
Chat retention policy remained ephemeral/no-store. PREP and OPS were not executed.

Result: `KNOWLEDGE GRAPH VISUAL REFINEMENT — COMPLETE_RUNTIME_VERIFIED`.
