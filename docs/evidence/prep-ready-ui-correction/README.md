# PREP-ready UI correction evidence

This bounded correction advances Product `0be3551e95755cc7ffb4733ab4a90fd9610b81a3`,
Evidence `8aa70152d0d5d65b8555ee3f0e7f74c0ea2d3e94`, and Handoff
`e208e1b3282d014c82a85add2a7a57436cd7cd2a` to Product
`2eceb8839252200dd67abd6910e1b5ed2541c89c`. No Router, retrieval, KG, MCP,
database schema, deployment environment contract, or PREP/OPS runtime was changed.

## Chat user action container

The question action element is now a Chat-scoped `<div role="group" aria-label="질문 작업">`, not
a semantic `footer` affected by global footer/card styling. The parent `message-user` article and
its direct `chat-message-actions-user` child explicitly have transparent/no background, no
background image, no border, and no shadow. The bubble-to-actions gap is one pixel. Copy/Edit button
hover and focus behavior remains scoped and unchanged.

The exact Product served this minified rule from DEV 39083:

```css
article.message-user>.chat-message-actions-user{box-shadow:none;background:0 0;border:0;justify-content:flex-end;gap:2px;margin-top:1px;padding-top:0}
```

The exact bundle also contains the higher-specificity transparent parent rule. `background:0 0` is
the minifier's equivalent for the explicit transparent/none shorthand; the source separately pins
`background-image:none`.

## Detected Change presentation

The period history table now has exactly seven columns:

`플랫폼 | 스키마 | 변경일 | 변경유형 | 테이블명 | 변경요약 | 변경내용`.

The server list DTO derives bounded presentation fields once from the canonical normalized event:
`target_kind`, nullable `field_name`, `presentation_change_type`, `change_summary`, and up to eight
typed `change_detail` entries. Raw before/after provider documents remain detail-only, so a 50-row
page performs no 50-event detail fan-out. Dataset-properties baseline CREATE is not classified as a
Table creation; Table lifecycle requires the canonical lifecycle entity/status aspect, and Column
creation/deletion requires a schemaMetadata field event.

Focused projection and UI tests cover Table CREATE/DELETE/CHANGE; Column CREATE/DELETE/CHANGE;
description, Tag, Glossary Term, Owner, Domain, Column description/type/nullable; KST
`YYYY-MM-DD`; exact headers; row activation/detail/pagination/filter compatibility; and zero list
calls to the detail transport. The desktop table is fixed at 100% of the parent with controlled
9/13/11/13/16/15/23 percent columns, bounded two-line summary/detail, and horizontal overflow only
below the narrow breakpoint.

The exact Product's Governance chunk served by DEV 39083 contains the new `변경내용` projection.
The current append-only DEV ledger remains 100 events and the retained governed exact
Table-to-System mapping count remains one. No ledger row or mapping was added by this correction.

## Search lineage edge labels

Only `SEARCH_LINEAGE_CLASSIC` displays edge text. Its existing canonical branch is reused:

- `UPSTREAM` -> `Upstream`;
- `DOWNSTREAM` -> `Downstream`;
- neutral non-lineage relationship -> canonical `relationType`, then canonical label;
- neutral generic lineage -> `Lineage`.

The adapter does not change source/target, arrow direction, root-relative branch, horizontal role
tiers, bounded expansion, or Table-name navigation. The ORGANIC profile's default hidden edge-label
contract is unchanged. The Search-only style uses 8.5px autorotated text with a small opaque light
background and padding. The exact Product's Cytoscape chunk served by DEV 39083 contains the
`displayLabel` mapping.

## Verification

- Focused UI: 7 files / 119 tests PASS; final adapter rerun 1 file / 7 tests PASS.
- Focused server projection: 36/36 PASS.
- Full UI: 90 files / 663 tests PASS.
- Node Product server: 132/132 PASS.
- ESLint, TypeScript, standard build, POC build: PASS.
- Ruff: PASS; strict mypy: 588 source files PASS; static verification: PASS.
- PREP deploy/handoff unit contract: 35/35 PASS.
- PREP smoke/bootstrap contract: 9/9 PASS (the canonical split remains 41 deploy/bootstrap and 3
  smoke assertions).
- Isolated Docker fresh/rerun/running/stopped/residual/ambiguous matrix: 1/1 PASS in 202.43s.
- Isolated durable-bootstrap forced-smoke-failure then same-command resume: 1/1 PASS in 199.83s.
- Compose resolves four services and the exact linux/amd64 Product image; 39080 remained down and
  untouched.
- Delta secret scan and final image environment/history proxy leak scan: PASS.
- `git diff --check`: PASS.
- Router/retrieval/reranking/grounding semantics are unchanged; the accepted 60+8 was not repeated.

## Exact DEV runtime

- 39083: HTTP 200, health 200, restart count 0.
- OCI: linux/amd64, revision exactly `2eceb8839252200dd67abd6910e1b5ed2541c89c`, image ID
  `sha256:7107ed3624498502ddfb92947029a49e2ae3bd16b2b901bff705263a52b3aa5a`.
- 39090: HTTP 200.
- 39080: unchanged DOWN.
- Temporary mode-0600 runtime environment file: removed.

## Browser limitation

The required in-app Browser was attempted against `http://127.0.0.1:39083/`. Its installed client
resolved an internal service module from a different cached plugin version and could not initialize.
The complete Browser troubleshooting contract was followed, and no unrelated browser backend was
substituted. Source, tests, exact production bundle, and exact runtime delivery are verified, but
actual pointer/visual acceptance remains `FINAL_BROWSER_ACCEPTANCE_SURFACE_UNAVAILABLE`.

Therefore the Product/Handoff is coherent and PREP-ready, while visual acceptance is truthfully
`PENDING`, not claimed as PASS. Actual PREP and OPS execution: **NOT EXECUTED**.
