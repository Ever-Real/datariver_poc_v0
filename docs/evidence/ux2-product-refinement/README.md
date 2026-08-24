# UX2 Product refinement evidence

This bundle closes UX2 on Product
`ced6ffeedc9ee9786abc6d12c41c30540201f600`, progressing from the accepted
Knowledge Graph Visual Refinement Product
`179093643f4cfa2dd808c0c27240f7f49f68063c` and Evidence
`192f26863e89636d33f9d50c7346a92d7dae2aba`. The exact Product OCI was deployed
only to the existing DEV `39083` service. PREP and OPS were not executed.

## UX2-A — Search lineage

Catalog/Search lineage remains Cytoscape.js and now uses the isolated
`SEARCH_LINEAGE_CLASSIC` visual profile. Its rounded-rectangle nodes, readable
Table labels, textual Upstream L2/L1/Current/Downstream L1/L2 legend and role/depth
colors do not alter the D3-like `ORGANIC` profile used by managed Knowledge graphs
and GraphRAG evidence. The existing authorization-first projection remains bounded
to depth two, 200 nodes and 400 edges.

Authenticated browser acceptance proved canonical Table-label navigation, browser
Back/query preservation, body drag/graph interaction, and an actual downstream
`depth=2` request. A direct hard reload initially exposed a real defect: the URL's
`catalogAsset` was only restored on `popstate`. The bounded correction restores it
on initial mount as well. On the final exact Product, hard reload reopened the exact
canonical Table detail and retained the search query. Managed Metadata Master still
reported the `ORGANIC` profile and no `SEARCH_LINEAGE_CLASSIC` instance.

## UX2-B — Change Management detected history

Change Management reuses the existing Monitoring change-history API/read model;
no detector, event source or authorization fallback was added. The browser showed
the Schema/Metadata history panel, date range, All/Schema Change/Metadata Change
controls, count, and the correct empty state without alert or crash. Selecting the
Schema filter reloaded the canonical query and retained the correct empty result.
Monitoring loaded normally afterward.

The final runtime authority facts are:

- Canonical runtime ledger events: **73** (Schema: **17**, Metadata: **56**).
- Authorized Change Management events at final runtime: **0**.
- Reason: active exact Table-to-System mapping = **0**.
- Authorization behavior: **FAIL-CLOSED / PASS**.
- Populated presentation path: **focused integration PASS**.
- Production authorization widened: **NO**.

The focused presentation suite proves Schema and Metadata rows, date/type wiring,
before/after detail and source/provenance through the same canonical API. No event,
mapping, row or detector data was fabricated for browser acceptance.

## UX2-C — Governance editor

The existing Governance document persistence/version contract is retained, with a
Tiptap-based rich editor and safe markup boundary. A disposable TEST-only document
was created through the authenticated Product UI. The following commands changed
the actual editor model rather than only activating a button:

- Heading 1, Heading 2, Heading 3;
- bold, italic, underline and strikethrough;
- bullet list and numbered list;
- blockquote and code block;
- add link, edit link and remove link;
- clear formatting, undo and redo;
- insert table (three rows and nine cells).

Initial Undo/Redo disabled state and active pressed states for inline formatting
were observed. All 26 toolbar buttons exposed a non-empty Product tooltip through
`aria-describedby`; a real pointer hover displayed the Bold tooltip and keyboard
focus displayed the Code Block tooltip. A `javascript:` link was rejected and no
anchor was created.

Save, hard reload and reopen preserved headings, inline marks, both lists, quote,
code block and table in the stored document. The TEST document was then archived
through the governed cleanup action and disappeared from the active list; no existing
Governance document was modified.

## Source and runtime gates

- Focused Catalog hard-reload suite: 1 file / 21 tests PASS.
- Full UI suite: 90 files / 658 tests PASS.
- ESLint, TypeScript, POC production build, static verification and
  `git diff --check`: PASS.
- Backend source was unchanged; the accepted server regression remains applicable
  and was not repeated after the frontend-only hard-reload correction.
- Router, retrieval, KG2 and MCP semantics were unchanged, so the accepted enhanced
  60/60 and Boundary 8/8 suites were preserved rather than rerun.

Authenticated representative regression passed for Admin/Profile, Search, Change
Management, Monitoring, Governance, managed Knowledge graphs and the Knowledge
Studio entry surface. GENERAL completed with no retrieval. Focused production-path
verification passed V18 (VECTOR with canonical managed Asset evidence) and R01
(GRAPH with Default Lineage and actual traversal evidence). Knowledge Studio remained
outside Cytoscape and its authoring source/workflow was unchanged.

The DEV service ran image
`datariver-poc:ced6ffeedc9ee9786abc6d12c41c30540201f600`, carried the same OCI
revision label, was healthy with zero restarts, and returned HTTP 200 on `39083`.
The persisted dashboard on `39090` returned HTTP 200.

## Authorization and cleanup

Authenticated positive paths passed. Search unauthenticated boundaries and
Governance edit/view boundaries remain covered by the final source suite. Change
Detection returned zero rows because its exact mapping authority failed closed;
no unauthorized event or document metadata was exposed.

Disposable DEV identities `ux2-browser-20260825`, `ux2-eval-20260825` and
`ux2-steward-20260825` were disabled, their sessions revoked, and a subsequent login
attempt was denied. Active UX2 test sessions were re-observed as zero. All temporary
password, cookie, response, screenshot and focused-verifier files were removed, all
Orca browser tabs were closed, and no temporary event/mapping/graph fixture remained.
Canonical DataHub, managed graph and Governance content was not deleted.

Result: `UX2 PRODUCT REFINEMENT — COMPLETE_RUNTIME_VERIFIED`.

