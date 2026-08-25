# Remaining Product refinement evidence

This bundle records the Search, Change Management, Chat and Registration refinement on
Product `ed5d5a6e37d509ede85c3c3bd58f331fd8117306`, progressing from the accepted portable
deployment Product `46500c130de9c8bebedd143eca946b5d9166e63b`, Evidence
`7dde689f7c0fe8de71b7fb8b86046a65aaecc504` and Handoff
`6fd9a0f5c5c30ab74af38530e81c06a961ea97de`. The exact Product OCI was built and deployed
only to the existing DEV `39083` service. PREP and OPS were not executed.

## A — Search

- Resource Tree explicit refresh uses the existing authorization-first current DataHub inventory
  reconciliation. It does not hide stale rows in the browser or add polling.
- A canonical default-result locator returns an authorized page/cursor position for a Dataset URN.
  Tree selection preserves the normal page and neighboring rows, selects only the requested row and
  opens its detail. It does not inject the Table name into the query, prepend a row or scan pages in
  the browser.
- A real DEV refresh completed against the current DataHub inventory. The post-refresh root contained
  two authorized platform branches. The default result page contained 25 rows; locate returned the
  exact requested identity and neighboring rows remained present.
- Missing Database metadata remains a truthful compact fallback; current descendants remain reachable.
- Search lineage keeps the isolated `SEARCH_LINEAGE_CLASSIC` Cytoscape profile and canonical label
  navigation. The accessible bounded-entity copy now explains authorization scope, displayed count,
  truncation and provenance without removing those semantics.
- Platform and Database widths were increased and sortable headers are kept on one line.

## B — Change Management

The page now orders `Consolidated Change Overview`, a default-collapsed `Detected Change → CR`
disclosure, then `CHANGE REQUESTS`. Date/filter/refresh controls share one compact row and the
Change Management content is capped at 13px without altering global navigation typography. The
same Monitoring change-history API/read model remains the only detection source.

Runtime RCA remained unchanged and fail-closed:

- canonical ledger events: **73**;
- Schema events: **17**;
- Metadata events: **56**;
- active exact Table-to-System mappings: **0**;
- authorized Change Management rows: **0**;
- authorization result: **FAIL-CLOSED / PASS**;
- production authorization widened: **NO**.

Focused presentation tests prove Schema and Metadata row rendering, date/type filters,
before/after detail and provenance through the canonical API. No fallback scope, fake mapping,
synthetic event or detector was added.

## C — Chat

Existing server-authoritative session/history ownership was reused. Existing unit coverage proves
account-scoped list, message, favorite and archive/delete behavior; no localStorage history or new
history store was added.

- User bubbles contain only question text; Copy and Message edit are in a footer. Edit restores text
  to the composer and sends a new immutable question.
- Stop aborts the browser request and propagates its signal through routing, embedding, managed graph,
  reranking and answer provider calls. The user question remains; no incomplete assistant response or
  partial evidence is persisted as final.
- The composer grows from one through six lines, then scrolls, with no manual resize handle.
- Auto-follow pauses when the user scrolls upward and resumes at the bottom or on a new question.
- Progressive display reveals only the completed, reauthorized server answer in bounded UI chunks;
  raw provider tokens, reasoning and preauthorization evidence are never exposed.
- Evidence uses a header strip instead of a nested rounded card. GRAPH responses render only the
  authorization-filtered bounded nodes/relations actually used by the answer through the existing
  Cytoscape/GraphRAG contract.

Exact production-path representative verification passed G12 GENERAL, V18 VECTOR and R01 GRAPH,
including canonical managed Asset grounding and an actual Default Lineage traversal. Full Router
60/60 and Boundary 8/8 were not repeated because intent, retrieval and reranking semantics were not
changed.

## D — Registration

The top-level workbench now uses `MANUAL | BULK | HISTORY`. HISTORY reuses the existing
`RegistrationRecentPanel` and its canonical read model; the former right-side Activity panel was
removed. Read-only Manager history remains visible while MANUAL/BULK mutation controls remain
disabled. The default MANUAL state always shows truthful empty `Table Properties` and
`Column Schema Specifications` workbench sections. Large Column Specifications use a bounded
vertical/horizontal scroll frame with sticky headers while existing field pagination and source
version fencing remain intact.

## Source and deployment gates

- Focused A-D UI suites: **6 files / 138 tests PASS**; final Chat/Registration check:
  **2 files / 56 tests PASS**.
- Full UI: **90 files / 661 tests PASS**.
- Node Product server: **129/129 PASS**.
- ESLint, TypeScript, standard build, POC build, Ruff lint, strict mypy and static verification: PASS.
- PREP deploy/handoff focused tests: **35/35 PASS**; smoke contract: **3/3 PASS**.
- Compose parsing and exact OCI build: PASS. Docker/Compose/env/database schema/runtime-init inputs
  were unchanged, so the one-command deployment contract has no new operator step.
- `git diff --check` and changed-diff secret scan: PASS.
- Ruff format check reports four unchanged legacy Python test files; the Product delta contains no
  Python changes. The full legacy Python suite reports 3,875 pass, 117 skip and 84 failures caused by
  pre-existing migration/test-contract drift. Relevant Chat ownership and PREP focused Python tests
  pass, and the Product Node server suite is green.

The canonical PREP command remains exactly `./scripts/prep39083 deploy`; `39080` was absent before
and after DEV reconcile and was not touched. Build/runtime proxy separation, retry receipt, volume
safety and OPS no-build promotion files were unchanged.

## Exact DEV runtime and cleanup

The DEV service ran `datariver-poc:ed5d5a6e37d509ede85c3c3bd58f331fd8117306`, carried the
same OCI revision label, was healthy and returned HTTP 200 on `39083`. Dashboard `39090` returned
HTTP 200. A DEV-only external Studio network attachment was restored after web recreation; no Studio,
graph or persistent state was reset.

One disposable admin credential was created through the existing bootstrap boundary. After read-only
runtime checks it was disabled at the current CAS version, two sessions were revoked, subsequent login
returned 401, and active test sessions were re-observed as zero. Temporary host/container password,
session and verifier artifacts were removed. No event, mapping, graph, Governance document or canonical
DataHub asset was created or deleted.

## Browser acceptance limitation

The in-app Browser runtime returned an empty available-browser list after the required connection and
troubleshooting flow. Per the Browser safety contract, no unrelated browser-control backend or
source-inspection substitute was used. Therefore direct pointer/visual browser acceptance of the final
OCI remains **BLOCKED by the local browser-control surface**, although exact Product HTTP/API runtime,
production-path Chat, full UI component interaction suites and build gates pass.

Result: `PRODUCT SOURCE AND DEV RUNTIME VERIFIED; FINAL BROWSER ACCEPTANCE BLOCKED`.

