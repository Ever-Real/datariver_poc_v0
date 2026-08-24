# Cytoscape interaction and force layout refinement — DEV closeout evidence

- Observed at: `2026-08-24T08:14:59Z`
- Starting Product: `4d49a815301a1d4f8d74f02a49601daf7cd9e333`
- Starting Evidence: `035ee45eab74362b7faafbfb1949c996a2477ba7`
- Final Product: `ab6fd454cdbf109c6b82d393a7100e3e38c71f84`
- Worktree: `Ever-Real/CHAT-KG-Router-GPT56-Sol`
- Scope: local DEV/Product only; PREP and OPS were not executed

The final image `datariver-poc:ab6fd454cdbf109c6b82d393a7100e3e38c71f84`
was healthy on `127.0.0.1:39083`, carried the same OCI revision label, and returned HTTP 200
for both `/` and `/healthz`. The persisted dashboard on `127.0.0.1:39090` returned HTTP 200.

## Visual hierarchy and stable selection

The accepted GV1 renderer used 170 x 52 nodes, 10 px padding, 10 px labels, a 4 px root border,
and a 5 px selected border. GV2 keeps the same canonical graph/view adapter and changes only the
read renderer presentation:

- all nodes use fixed 142 x 42 geometry, 6 px padding, 9 px labels and a fixed 2 px border;
- a selected node retains exactly the same width, height, padding, font and border footprint;
- selection is a 2 px Product orange border plus a restrained 12% underlay with 5 px padding;
- canvas labels are exactly two compact lines: a maximum 28-character display label and a maximum
  22-character entity type; the full canonical value remains in the DOM detail panel;
- edges increased from 1.6 px to 2.2 px, use 1.25-scale triangle arrows, and have distinct amber
  upstream and green downstream colors in addition to the textual legend.

Authenticated runtime style inspection on the exact Product observed selected and unselected nodes
with the same `142 / 42 / 6 / 9 / 2` geometry. Selection changed only underlay opacity from 0 to
0.12, moved no nodes, and changed neither zoom nor pan. Light-theme contrast and visible keyboard
focus were verified; the Product does not currently expose a separate dark-theme control.

## Label navigation and bounded body expansion

The existing Cytoscape node is now split by its rendered label bounding box instead of introducing
single/double-click ambiguity:

- label click uses the canonical DataHub URN/asset ID to open the exact Catalog Table detail;
- body click selects the node and requests a bounded directional projection with `depth=2`;
- an upstream-branch node expands `UPSTREAM`, a downstream-branch node expands `DOWNSTREAM`, and an
  ambiguous node requires the existing explicit direction context;
- keyboard users have the equivalent DOM label link and directional two-level expand controls.

On the exact Product, the Catalog `cost_ledger_lithography` lineage opened as a real 7-node / 6-edge
DataHub projection. A downstream body hit sent an authenticated
`direction=DOWNSTREAM&depth=2` request without changing the Catalog query. A label hit on
`manufacturing_lot_lithography` opened that exact Table detail, performed no expansion request,
preserved the query, and browser Back restored the prior detail.

The POC adapter now preserves the existing canonical request contract through its DataHub wrapper.
The server performs authorization-first bounded BFS with depth limited to 1 or 2, 200 nodes, 400
edges and provider concurrency 4. It never sends an eager full graph or continues traversal through
an unauthorized entity.

## Viewport preservation and force interaction

`cytoscape-cola@2.5.1` is an exact pinned, stable, MIT-licensed dependency compatible with
`cytoscape@3.34.1`. It is bundled locally with no CDN and loaded only with the lazy read renderer.
The production build recorded the Cola extension at 84,510 bytes raw / 24,360 bytes gzip and the
existing Cytoscape engine at 435,440 bytes raw / 137,930 bytes gzip. Knowledge Studio remains in its
separate React Flow bundle.

Physics configuration is graph-type driven and contains no domain-specific rule. Both profiles use
`fit=false`, `randomize=false`, `centerGraph=false`, overlap avoidance, bounded simulation and
configuration-owned spacing/edge length. Metadata/semantic graphs use free force interaction.
Lineage uses hop-aware exact horizontal tier gaps so force motion preserves
`upstream -> current -> downstream`; observed upstream and downstream gaps were both 190 px.

Node grab resumes Cola physics, connected nodes respond during drag, release performs a bounded
settle, and the simulation stops. If the visible graph exceeds 90 nodes the physics scope is the
selected closed neighborhood. Initial settle is bounded at 1,500 ms, grab at 900 ms and release at
700 ms; no perpetual simulation remains.

Expand/collapse retains zoom, selected ID, focused entity, filters and direction. It saves the
anchor's rendered screen coordinate, applies an incremental `cy.batch()` update, seeds only new
nodes near the anchor, runs bounded physics with existing nodes locked, and then compensates pan so
the anchor stays at the same screen coordinate. It never calls `fit()` after expand/collapse; Fit is
only an explicit user action after initial presentation.

Actual runtime observations:

- Metadata Master: 48 nodes / 47 edges from the authorized 12,281 / 24,556 Asset; transform 0.2 ms,
  layout 33.0 ms, first usable 33.0 ms, initial settle 1,674.8 ms.
- Metadata two-level expansion: 48 / 47 to 50 / 50; collapse returned to 48 / 47; zoom delta 0,
  pan delta 0 and selected anchor screen-position delta 0 in both directions.
- Metadata drag: 47 connected neighbors moved during drag, all settled, viewport delta 0, and no
  movement remained after the settle window.
- Default Lineage: 15 nodes / 23 edges from the authorized 1,001 / 1,950 Asset; transform 0.0 ms,
  layout 14.9 ms, first usable 14.9 ms.
- Lineage drag: all 14 connected neighbors reacted, the 190 px tier gaps remained after release,
  viewport delta was 0, settle completed in 862.9 ms, and subsequent movement was 0.
- Catalog two-level expansion retained the exact zoom and anchor screen coordinate. Pan was adjusted
  only by the compensating 7.59 px needed to keep that anchor fixed, rather than resetting the view.

Three authenticated GraphRAG open/close cycles observed one read-graph section / three Cytoscape
canvases while open and exactly zero sections / zero canvases after navigation. Focused lifecycle
tests additionally prove layout stop, listener removal, Cytoscape destroy, pending expansion abort,
ResizeObserver cleanup and stale callback fencing.

## Read surfaces, accessibility and Studio boundary

The refined shared renderer is used by Catalog/Search lineage, managed Lineage, Metadata Master,
Knowledge GraphRAG evidence, Change Request impact, and Chat evidence that opens Catalog lineage.
The final browser session exercised Catalog/Search lineage, managed Lineage, Metadata Master,
GraphRAG bounded preview and post-query evidence rendering. The temporary subject had no authorized
Change Request row; the CR impact renderer contract remains covered by the focused passing component
suite and no business fixture was fabricated.

Canvas selection is mirrored into a screen-reader-accessible DOM article and bounded entity list.
All zoom, fit, reset, label navigation and expansion commands are ordinary keyboard-focusable DOM
controls with visible focus. The legend uses text and shapes in addition to color, and long labels,
canonical IDs and provenance remain available outside the canvas.

Knowledge Studio was opened read-only at the T-Box step of an existing draft. Runtime inspection
observed one `.react-flow` authoring instance and zero Cytoscape read instances. The T-Box editing
controls and existing draft state loaded normally; no Studio source file or authoring workflow was
changed and no Studio mutation was performed.

## Authorization and regression

The authenticated read surfaces returned only authorized bounded payloads. The final directional
Catalog lineage endpoint returned HTTP 401 without a session. The final 117-test server suite covers
authorization-first traversal and the shared semantic-node negative, so an authorized Table A cannot
use a shared Tag/Term/Concept to disclose an unauthorized Table B, its metadata, edge, count or
existence. Existing MCP authorization remains unchanged because MCP/Core Knowledge code was not
modified.

Final source gates on the exact Product:

- focused Cytoscape/Catalog/API: 4 files / 54 tests PASS;
- server: 117/117 PASS;
- UI: 90 files / 649 tests PASS;
- ESLint, TypeScript, production build, static verification and `git diff --check`: PASS.

Representative authenticated browser regression passed:

- GENERAL `wafer가 뭐야?`: GENERAL, retrieval not executed, evidence 0;
- VECTOR Default Lineage Asset query: VECTOR, exact managed Asset evidence;
- GRAPH `cost_ledger_lithography` downstream query: GRAPH, Default Lineage selected and actual
  node/relation evidence returned;
- Admin/Profile, Catalog/Search, Change Management navigation and Monitoring loaded normally;
- Knowledge hard reload preserved authentication and reopened both managed graph Assets.

Renderer and bounded Catalog visualization work did not alter the Router semantic contract, managed
graph retrieval, MCP, refresh pipeline or authorization policy. The accepted Router 60/60 and
Boundary 8/8 evidence was therefore preserved and not rerun.

## Cleanup

The disposable `gv2-browser-20260824` credential was disabled with the governed credential command,
its one session was revoked, active sessions were re-observed as zero, and `/poc-api/auth/me`
returned HTTP 401. The clipboard was cleared, no password file remained, all Orca browser tabs were
closed, and temporary screenshots/debug output were absent. No test graph, Asset, CR, refresh or
Studio mutation was created. PREPARING/RUNNING K9 refresh runs remained zero and both canonical
managed graph Assets were preserved.

All GV2 DEV/Product gates are `COMPLETE_RUNTIME_VERIFIED`. PREP and OPS remain unexecuted.
