# Cytoscape.js read-only graph visualization — DEV closeout evidence

- Observed at: `2026-08-24T05:56:36Z`
- Starting Product: `698669d8e1ded3c9a8927415fbdee377d163ed56`
- Starting Evidence: `8b63a041fd7cc4f16feebf20eec0ecab4eea5924`
- Final Product: `4d49a815301a1d4f8d74f02a49601daf7cd9e333`
- Worktree: `Ever-Real/CHAT-KG-Router-GPT56-Sol`
- Scope: local DEV/Product only; PREP and OPS were not executed

The final Product image `datariver-poc:4d49a815301a1d4f8d74f02a49601daf7cd9e333`
was healthy on `127.0.0.1:39083`, carried the same OCI revision label, and returned HTTP 200.
The persistent dashboard on `127.0.0.1:39090` returned HTTP 200. The accepted Knowledge, UX1,
Chat Router, managed graph, and MCP state was preserved.

## Inventory and scope boundary

The read/explore inventory found five renderer paths:

| Surface | Canonical source | Previous renderer | Final renderer |
|---|---|---|---|
| Catalog asset Lineage tab | DataHub lineage API | custom DOM/SVG | Cytoscape.js |
| Managed graph release preview/explorer | canonical Knowledge release snapshot | shared FlowCanvas | Cytoscape.js |
| Knowledge GraphRAG evidence preview | canonical bounded release snapshot | shared FlowCanvas | Cytoscape.js |
| Change Request impact graph | canonical impact graph DTO | shared FlowCanvas | Cytoscape.js |
| Chat catalog evidence lineage | Catalog detail/lineage API | indirect custom DOM/SVG | indirect Cytoscape.js through Catalog detail |

Knowledge Studio was explicitly excluded. Its T-Box GraphBuilder, A-Box Data Enricher, ingestion
authoring canvas, unsaved state, validation and release workflow retain the existing implementation.
Browser inspection opened an existing Studio draft at the T-Box step and observed one `.react-flow`
authoring instance and zero Cytoscape read surfaces. The shared `FlowCanvas` and `@xyflow/react`
dependency remain because Studio still owns them.

## Renderer architecture

`cytoscape@3.34.1` is pinned in the Product lockfile. It is the stable 3.x npm release used here,
is MIT licensed, and is bundled locally with no CDN. The lazy renderer chunk is 435,440 bytes raw
and 136,503 bytes gzip; Cytoscape is not loaded by pages that do not open a read graph.

The backend continues to return canonical renderer-independent Graph DTOs. A frontend
`CytoscapeGraphAdapter` converts canonical nodes and edges into element definitions. Node and edge
identity comes from canonical entity/relation identity, never array position, display label, or a
per-render random value. Invalid duplicates and missing endpoints fail adaptation instead of being
silently rendered. Backend source contains no Cytoscape DTO or renderer coupling.

LINEAGE uses Cytoscape's built-in breadth-first layout in a left-to-right direction. Bounded
METADATA_MASTER and semantic graphs use built-in CoSE. No layout extension was necessary. Layout
selection is graph-type driven and contains no domain-specific rule.

## Bounded Metadata Master explorer

The 12,281-node / 24,556-edge Metadata Master is never eagerly sent to the browser. The initial
request is bounded to 48 nodes, 96 edges and one hop. Authorization is applied before root
resolution and bounded projection. The frontend supports server-side root search, hop depth,
node/relation filters, incremental neighbor expansion, collapse and reset. Its merged view is
bounded to 160 nodes / 320 edges and refuses excess rather than applying an arbitrary sample.
The UI explicitly reports `Showing N / M authorized` counts.

Authenticated runtime observations on the exact Product:

- Initial Metadata Master: 48 nodes / 47 edges, 103,015 transferred bytes, request 385.8 ms,
  transform 0.1 ms, CoSE layout 72.7 ms, first usable render 119.9 ms.
- Remote search `yield_summary_lithography`: a 3-node / 2-edge authorized bounded root result,
  6,284 transferred bytes, request 610.1 ms, layout 5.3 ms, first usable render 14.8 ms.
- Expansion used canonical `root_node_id`; the observed request completed in 345.0 ms.
- The `class.table` node filter returned one node and zero edges without retaining the filter when
  switching to Default Lineage.

## Lineage runtime

The managed Default Lineage Asset remains version 6, READY, DAILY, with 1,001 nodes / 1,950 edges
and last result NO_OP. Its initial read view was an authorized 15-node / 23-edge projection with a
12.5 ms layout and 34.3 ms first usable render. Directional styling, upstream/downstream/direct
relationship highlights, canonical selection, detail, provenance, zoom, fit and reset were present.

The Catalog Lineage tab used real DataHub-derived lineage for
`cost_ledger_lithography`: 4 nodes / 3 edges, request 47.2 ms, layout 3.7 ms and first usable render
17.3 ms. The selected table retained its canonical DataHub URN and linked DOM detail. A hard reload
preserved authentication and both managed Assets, after which Default Lineage reopened as Cytoscape.

## UX, accessibility and lifecycle

Controls are ordinary keyboard-focusable DOM buttons with visible Product focus styles. The canvas
supports `+`, `-` and `0`; selection is mirrored into an accessible DOM entity list and detail panel.
Legend entries carry text labels in addition to color, and node/relation provenance remains in DOM.
Product theme tokens drive graph colors. The current Product exposes one light theme and no separate
dark-mode control, so the accepted light theme was the applicable browser gate.

The renderer owns a dedicated canvas host separate from React's loading/error DOM. This prevents
Cytoscape teardown from removing React-owned nodes. Component tests prove one instance/listener set
per mount, `removeAllListeners()` and `destroy()` on unmount, `ResizeObserver` cleanup, and abort of
in-flight search/expand work. Four authenticated open/close cycles never accumulated surfaces: a
settled close observed 0 sections / 0 hosts / 0 canvases and reopen observed exactly 1 section /
1 host / 3 Cytoscape canvases.

Loading, empty, no-authorized-result, entity-not-found, graph-query/layout failure and partial
expansion failure are represented distinctly; query failure is not converted into an empty graph.

## Authorization

Positive renderer requests contained only server-authorized bounded snapshots and never prefetched
the full graph. The same snapshot endpoint without credentials returned HTTP 401
`SESSION_REQUIRED`. The final 116-test server suite covers the shared semantic-node negative: an
authorized Table A cannot use a shared Term/Concept to reveal an unauthorized Table B, its metadata,
edge, count or existence. Existing MCP authorization uses the same unchanged Core Knowledge Service
and remains PASS.

## Regression gates

- Server: 116/116 PASS
- UI: 90 files / 641 tests PASS
- ESLint: PASS
- TypeScript: PASS
- static verification: PASS
- production build: PASS
- `git diff --check`: PASS

Authenticated exact-Product browser gates passed for the Knowledge registry, Metadata Master,
Default Lineage, Knowledge GraphRAG preview, Catalog lineage, hard reload, Admin/Profile, Search,
Change Management and Monitoring. Change Management had no authorized CR rows in this test account;
the impact renderer contract and migration are covered by the passing component suite.

Representative Chat runtime also passed once after the final Product build:

- GENERAL `wafer가 뭐야?`: GENERAL, internal retrieval 0, evidence 0.
- VECTOR Default Lineage Asset query: VECTOR, one canonical Managed Asset evidence item.
- GRAPH `cost_ledger_lithography` downstream query: GRAPH, Default Lineage selected, actual node and
  `rel.dataset_depends_on` evidence returned.

Renderer work did not change router, retrieval, graph traversal or authorization semantics, so the
accepted 60/60 Router and 8/8 boundary evidence was preserved and the full suite was not rerun.

## Cleanup

The disposable `gv1-browser-20260824` credential was disabled using the governed credential command,
its active session was revoked, active sessions were re-observed as zero, and `/auth/me` returned
HTTP 401. No password file was created, the clipboard was cleared, both Orca browser tabs were
closed, and K9 PREPARING refresh runs remained zero. No test graph, temporary Asset, staging
namespace, debug flag or Product data was created. Canonical DataHub data and both managed graph
Assets were preserved.

All GV1 DEV/Product gates are `COMPLETE_RUNTIME_VERIFIED`. PREP and OPS remain unexecuted.
